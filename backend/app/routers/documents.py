import datetime as dt

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .. import models as m
from ..core import (
    FINANCE_ROLES, MANAGE_ROLES, APIError, audit, bad_request, can_view_finance, forbidden, get_project_or_404, like,
    not_found, page_response, paginate, visible_project_ids_subquery,
)
from ..db import get_db
from ..security import get_current_user, require_roles
from ..storage import (
    CATEGORIES, docx_preview_html, extract_commercial_fields, extract_text, file_path, safe_download_name, save_bytes,
    validate_upload, xlsx_preview_rows,
)

router = APIRouter(prefix="/api/documents", tags=["documents"])
FINANCIAL_CATEGORIES = ("quotation", "client_po", "supplier_po", "invoice", "payment_proof")
LINK_FIELDS = ("client_id", "supplier_id", "quotation_version_id", "client_po_id", "supplier_po_id", "payment_id",
               "supplier_payment_id", "task_id", "update_id")


def doc_out(d: m.Document) -> dict:
    return {
        "id": d.id, "title": d.title, "description": d.description, "category": d.category,
        "original_filename": d.original_filename, "mime_type": d.mime_type, "extension": d.extension,
        "size_bytes": d.size_bytes, "sha256": d.sha256, "project_id": d.project_id,
        "project": f"{d.project.code} · {d.project.name}" if d.project else None,
        **{f: getattr(d, f) for f in LINK_FIELDS},
        "superseded_by_id": d.superseded_by_id, "uploaded_by": d.uploaded_by.full_name if d.uploaded_by else None,
        "created_at": d.created_at, "previewable": d.extension in ("pdf", "docx", "png", "jpg", "jpeg", "txt", "csv", "xlsx"),
        "has_text": bool(d.extracted_text),
    }


def check_doc_access(user: m.User, category: str) -> None:
    if category in FINANCIAL_CATEGORIES and not can_view_finance(user):
        raise forbidden("Financial documents are restricted to Admins and Project Managers")


def get_doc(db: Session, user: m.User, doc_id: int) -> m.Document:
    d = db.get(m.Document, doc_id)
    if not d or d.deleted_at:
        raise not_found("Document")
    get_project_or_404(db, user, d.project_id)
    check_doc_access(user, d.category)
    return d


def _validate_links(db: Session, project_id: int, links: dict) -> None:
    model_for = {
        "client_id": m.Client, "supplier_id": m.Supplier, "quotation_version_id": m.QuotationVersion,
        "client_po_id": m.ClientPurchaseOrder, "supplier_po_id": m.SupplierPurchaseOrder, "payment_id": m.PaymentReceived,
        "supplier_payment_id": m.SupplierPayment, "task_id": m.Task, "update_id": m.ProjectUpdate,
    }
    for key, value in links.items():
        if value is None:
            continue
        obj = db.get(model_for[key], value)
        if not obj:
            raise bad_request(f"Linked record {key} does not exist")
        if key == "quotation_version_id":
            if obj.quotation.project_id != project_id:
                raise bad_request("Linked quotation belongs to a different project")
        elif hasattr(obj, "project_id") and obj.project_id not in (None, project_id):
            raise bad_request(f"Linked record {key} belongs to a different project")


def store_document(
    db: Session, user: m.User, upload_name: str, data: bytes, project_id: int, category: str,
    title: str | None = None, description: str | None = None, links: dict | None = None,
) -> tuple[m.Document, str]:
    if category not in CATEGORIES:
        raise bad_request(f"Unknown document category '{category}'")
    check_doc_access(user, category)
    project = get_project_or_404(db, user, project_id)
    links = {k: v for k, v in (links or {}).items() if v is not None}
    _validate_links(db, project_id, links)
    ext, mime = validate_upload(upload_name, data)
    stored, digest = save_bytes(ext, data)
    text, method = extract_text(ext, data)
    d = m.Document(
        title=(title or upload_name.rsplit(".", 1)[0])[:255], description=description, category=category,
        original_filename=safe_download_name(upload_name), stored_filename=stored, mime_type=mime, extension=ext,
        size_bytes=len(data), sha256=digest, extracted_text=text[:200000] if text else None, project_id=project.id,
        client_id=links.pop("client_id", None) or (project.client_id if category in ("quotation", "client_po", "invoice", "payment_proof") else None),
        uploaded_by_id=user.id, **links,
    )
    db.add(d)
    db.flush()
    audit(db, user, "upload", "document", d.id, project.id, changes={"filename": d.original_filename, "category": category, "size": len(data)})
    return d, method


@router.post("", status_code=201)
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    project_id: int = Form(...),
    category: str = Form("other"),
    title: str | None = Form(None),
    description: str | None = Form(None),
    client_id: int | None = Form(None), supplier_id: int | None = Form(None),
    quotation_version_id: int | None = Form(None), client_po_id: int | None = Form(None),
    supplier_po_id: int | None = Form(None), payment_id: int | None = Form(None),
    supplier_payment_id: int | None = Form(None), task_id: int | None = Form(None), update_id: int | None = Form(None),
    db: Session = Depends(get_db), user: m.User = Depends(get_current_user),
):
    data = await file.read()
    links = dict(client_id=client_id, supplier_id=supplier_id, quotation_version_id=quotation_version_id,
                 client_po_id=client_po_id, supplier_po_id=supplier_po_id, payment_id=payment_id,
                 supplier_payment_id=supplier_payment_id, task_id=task_id, update_id=update_id)
    d, method = store_document(db, user, file.filename or "", data, project_id, category, title, description, links)
    result = {"document": doc_out(d), "text_extraction": method}
    if category in ("quotation", "client_po", "supplier_po"):
        kind = "quotation" if category == "quotation" else "po"
        result["extraction"] = extract_commercial_fields(d.extracted_text or "", kind, d.extension, data)
        result["extraction"]["method"] = method
    db.commit()
    return result


@router.get("")
def list_documents(
    q: str | None = None, project_id: int | None = None, category: str | None = None, client_id: int | None = None,
    supplier_id: int | None = None, uploaded_by_id: int | None = None, date_from: dt.date | None = None,
    date_to: dt.date | None = None, include_superseded: bool = True, page: int = 1, page_size: int = 25,
    db: Session = Depends(get_db), user: m.User = Depends(get_current_user),
):
    stmt = select(m.Document).where(m.Document.deleted_at.is_(None), m.Document.project_id.in_(visible_project_ids_subquery(user)))
    if not can_view_finance(user):
        stmt = stmt.where(m.Document.category.not_in(FINANCIAL_CATEGORIES))
    if project_id:
        stmt = stmt.where(m.Document.project_id == project_id)
    if category:
        stmt = stmt.where(m.Document.category.in_(category.split(",")))
    if client_id:
        stmt = stmt.where(m.Document.client_id == client_id)
    if supplier_id:
        stmt = stmt.where(m.Document.supplier_id == supplier_id)
    if uploaded_by_id:
        stmt = stmt.where(m.Document.uploaded_by_id == uploaded_by_id)
    if date_from:
        stmt = stmt.where(m.Document.created_at >= dt.datetime.combine(date_from, dt.time.min, dt.timezone.utc))
    if date_to:
        stmt = stmt.where(m.Document.created_at < dt.datetime.combine(date_to + dt.timedelta(days=1), dt.time.min, dt.timezone.utc))
    if not include_superseded:
        stmt = stmt.where(m.Document.superseded_by_id.is_(None))
    if q:
        t = like(q)
        stmt = stmt.where(or_(m.Document.title.ilike(t), m.Document.original_filename.ilike(t),
                              m.Document.description.ilike(t), m.Document.extracted_text.ilike(t)))
    rows, total = paginate(db, stmt.order_by(m.Document.created_at.desc(), m.Document.id.desc()), page, page_size)
    return page_response([doc_out(d) for d in rows], total, page, page_size)


@router.get("/{doc_id}")
def get_document(doc_id: int, db: Session = Depends(get_db), user: m.User = Depends(get_current_user)):
    d = get_doc(db, user, doc_id)
    history = []
    prev = db.scalars(select(m.Document).where(m.Document.superseded_by_id == d.id)).all()
    while prev:
        history.extend(doc_out(p) for p in prev)
        prev = db.scalars(select(m.Document).where(m.Document.superseded_by_id.in_([p.id for p in prev]))).all()
    return {"document": doc_out(d), "previous_versions": history}


@router.get("/{doc_id}/download")
def download(doc_id: int, request: Request, db: Session = Depends(get_db), user: m.User = Depends(get_current_user)):
    d = get_doc(db, user, doc_id)
    path = file_path(d.stored_filename)
    audit(db, user, "download", "document", d.id, d.project_id, request=request)
    db.commit()
    return FileResponse(path, media_type="application/octet-stream", filename=d.original_filename,
                        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"})


@router.get("/{doc_id}/preview")
def preview(doc_id: int, db: Session = Depends(get_db), user: m.User = Depends(get_current_user)):
    d = get_doc(db, user, doc_id)
    path = file_path(d.stored_filename)
    headers = {"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store",
               "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; img-src data:; sandbox"}
    if d.extension in ("pdf", "png", "jpg", "jpeg"):
        return FileResponse(path, media_type=d.mime_type, headers={**headers, "Content-Disposition": "inline"})
    data = path.read_bytes()
    try:
        if d.extension == "docx":
            return {"type": "html", "html": docx_preview_html(data)}
        if d.extension == "xlsx":
            return {"type": "table", "rows": xlsx_preview_rows(data)}
        if d.extension in ("txt", "csv"):
            return {"type": "text", "text": (d.extracted_text or "")[:200000]}
    except Exception:
        raise APIError(422, "This document could not be rendered for preview. Download it instead.", "preview_failed")
    raise APIError(415, "Preview is not available for this file type. Download it instead.", "preview_unsupported")


@router.post("/{doc_id}/replace", status_code=201)
async def replace_document(doc_id: int, request: Request, file: UploadFile = File(...), db: Session = Depends(get_db),
                           user: m.User = Depends(get_current_user)):
    old = get_doc(db, user, doc_id)
    if user.role not in MANAGE_ROLES and old.uploaded_by_id != user.id:
        raise forbidden("Only the uploader or a manager can replace this document")
    data = await file.read()
    links = {f: getattr(old, f) for f in LINK_FIELDS}
    new, method = store_document(db, user, file.filename or "", data, old.project_id, old.category, old.title, old.description, links)
    old.superseded_by_id = new.id
    # keep commercial records pointing at the current file
    for model in (m.QuotationVersion, m.ClientPurchaseOrder, m.SupplierPurchaseOrder):
        for rec in db.scalars(select(model).where(model.document_id == old.id)):
            rec.document_id = new.id
    audit(db, user, "replace", "document", old.id, old.project_id, changes={"replaced_by": new.id}, request=request)
    db.commit()
    return {"document": doc_out(new), "text_extraction": method}


@router.delete("/{doc_id}")
def delete_document(doc_id: int, request: Request, db: Session = Depends(get_db), user: m.User = Depends(require_roles(*MANAGE_ROLES))):
    d = get_doc(db, user, doc_id)
    d.deleted_at = dt.datetime.now(dt.timezone.utc)
    audit(db, user, "delete", "document", d.id, d.project_id, request=request)
    db.commit()
    return {"ok": True}


@router.get("/{doc_id}/extract")
def re_extract(doc_id: int, kind: str = "quotation", db: Session = Depends(get_db), user: m.User = Depends(require_roles(*FINANCE_ROLES))):
    d = get_doc(db, user, doc_id)
    data = file_path(d.stored_filename).read_bytes() if d.extension == "docx" else None
    return extract_commercial_fields(d.extracted_text or "", "quotation" if kind == "quotation" else "po", d.extension, data)
