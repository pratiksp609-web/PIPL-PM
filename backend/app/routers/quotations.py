import datetime as dt

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from .. import models as m
from ..core import (
    FINANCE_ROLES, APIError, apply_changes, audit, bad_request, conflict, get_project_or_404, like, not_found, snapshot,
)
from ..db import get_db
from ..schemas import QuotationCreate, QuotationStatusIn, QuotationVersionIn
from ..security import require_roles
from .projects import ensure_project_editable

router = APIRouter(prefix="/api", tags=["quotations"])
VERSION_FIELDS = ("quotation_date", "validity_date", "subtotal", "tax_amount", "total_amount", "currency", "payment_terms",
                  "delivery_terms", "delivery_date", "scope", "line_items", "notes")
TRANSITIONS = {
    "draft": {"submitted", "approved", "rejected"},
    "submitted": {"approved", "rejected", "draft"},
    "rejected": {"draft"},
    "approved": {"rejected"},
    "expired": set(),
    "superseded": set(),
}


def effective_status(v: m.QuotationVersion, today: dt.date | None = None) -> str:
    today = today or dt.date.today()
    if v.status in ("draft", "submitted") and v.validity_date and v.validity_date < today:
        return "expired"
    return v.status


def version_out(v: m.QuotationVersion) -> dict:
    d = snapshot(v, ["id", "quotation_id", "revision_number", "quotation_date", "validity_date", "subtotal", "tax_amount",
                     "total_amount", "currency", "payment_terms", "delivery_terms", "delivery_date", "scope", "line_items",
                     "status", "document_id", "extraction", "extraction_verified", "approved_at", "notes", "created_at"])
    d["effective_status"] = effective_status(v)
    d["document"] = {"id": v.document.id, "title": v.document.title, "extension": v.document.extension,
                     "original_filename": v.document.original_filename} if v.document else None
    d["tax_check"] = _tax_check(v)
    return d


def _tax_check(v) -> str | None:
    if v.subtotal is not None and v.tax_amount is not None and v.total_amount is not None:
        if abs(v.subtotal + v.tax_amount - v.total_amount) > 1:
            return "Subtotal + taxes does not equal the total amount"
    return None


def quotation_out(q: m.Quotation) -> dict:
    versions = [version_out(v) for v in sorted(q.versions, key=lambda v: -v.revision_number)]
    approved = next((v for v in versions if v["status"] == "approved"), None)
    return {
        "id": q.id, "project_id": q.project_id, "client_id": q.client_id, "quotation_number": q.quotation_number,
        "title": q.title, "created_at": q.created_at, "versions": versions,
        "latest": versions[0] if versions else None, "approved_version": approved,
    }


def _check_document(db: Session, document_id: int | None, project_id: int):
    if document_id is None:
        return
    d = db.get(m.Document, document_id)
    if not d or d.deleted_at or d.project_id != project_id:
        raise bad_request("Attached document does not exist or belongs to another project")


def _supersede_previous(db: Session, q: m.Quotation, keep_id: int, user: m.User):
    for v in q.versions:
        if v.id != keep_id and v.status in ("draft", "submitted"):
            v.status = "superseded"
            audit(db, user, "superseded", "quotation_version", v.id, q.project_id, changes={"superseded_by": keep_id})


@router.get("/quotations")
def list_quotations(
    project_id: int | None = None, client_id: int | None = None, status: str | None = None, q: str | None = None,
    db: Session = Depends(get_db), user: m.User = Depends(require_roles(*FINANCE_ROLES)),
):
    stmt = select(m.Quotation).options(selectinload(m.Quotation.versions).selectinload(m.QuotationVersion.document)).order_by(m.Quotation.id.desc())
    if project_id:
        stmt = stmt.where(m.Quotation.project_id == project_id)
    if client_id:
        stmt = stmt.where(m.Quotation.client_id == client_id)
    if q:
        stmt = stmt.where(or_(m.Quotation.quotation_number.ilike(like(q)), m.Quotation.title.ilike(like(q))))
    rows = [quotation_out(x) for x in db.scalars(stmt.limit(500)).all()]
    if status:
        wanted = set(status.split(","))
        rows = [r for r in rows if r["latest"] and r["latest"]["effective_status"] in wanted]
    return {"items": rows, "total": len(rows)}


@router.post("/quotations", status_code=201)
def create_quotation(body: QuotationCreate, request: Request, db: Session = Depends(get_db), user: m.User = Depends(require_roles(*FINANCE_ROLES))):
    project = get_project_or_404(db, user, body.project_id)
    ensure_project_editable(project)
    _check_document(db, body.document_id, project.id)
    exists = db.scalar(select(m.Quotation).where(m.Quotation.client_id == project.client_id,
                                                 func.lower(m.Quotation.quotation_number) == body.quotation_number.lower()))
    if exists:
        raise conflict(f"Quotation {body.quotation_number} already exists for this client. Add a new revision to it instead.",
                       {"quotation_id": exists.id})
    q = m.Quotation(project_id=project.id, client_id=project.client_id, quotation_number=body.quotation_number,
                    title=body.title, created_by_id=user.id, updated_by_id=user.id)
    db.add(q)
    db.flush()
    data = body.model_dump(include=set(VERSION_FIELDS), mode="json")
    data.update(body.model_dump(include={"quotation_date", "validity_date", "delivery_date", "subtotal", "tax_amount", "total_amount"}))
    v = m.QuotationVersion(quotation_id=q.id, revision_number=0, **data, document_id=body.document_id,
                           extraction_verified=bool(body.extraction_verified), created_by_id=user.id, updated_by_id=user.id)
    db.add(v)
    db.flush()
    if body.document_id:
        db.get(m.Document, body.document_id).quotation_version_id = v.id
    audit(db, user, "create", "quotation", q.id, project.id, changes={"quotation_number": q.quotation_number, **data}, request=request)
    db.commit()
    db.refresh(q)
    return quotation_out(q)


@router.get("/quotations/{quotation_id}")
def get_quotation(quotation_id: int, db: Session = Depends(get_db), user: m.User = Depends(require_roles(*FINANCE_ROLES))):
    q = db.get(m.Quotation, quotation_id)
    if not q:
        raise not_found("Quotation")
    get_project_or_404(db, user, q.project_id)
    return quotation_out(q)


@router.post("/quotations/{quotation_id}/versions", status_code=201)
def add_revision(quotation_id: int, body: QuotationVersionIn, request: Request, document_id: int | None = None,
                 db: Session = Depends(get_db), user: m.User = Depends(require_roles(*FINANCE_ROLES))):
    q = db.get(m.Quotation, quotation_id)
    if not q:
        raise not_found("Quotation")
    project = get_project_or_404(db, user, q.project_id)
    ensure_project_editable(project)
    _check_document(db, document_id, q.project_id)
    next_rev = (db.scalar(select(func.max(m.QuotationVersion.revision_number)).where(m.QuotationVersion.quotation_id == q.id)) or 0) + 1
    data = body.model_dump(include=set(VERSION_FIELDS), mode="json")
    data.update(body.model_dump(include={"quotation_date", "validity_date", "delivery_date", "subtotal", "tax_amount", "total_amount"}))
    v = m.QuotationVersion(quotation_id=q.id, revision_number=next_rev, **data, document_id=document_id,
                           extraction_verified=bool(body.extraction_verified), created_by_id=user.id, updated_by_id=user.id)
    db.add(v)
    db.flush()
    if document_id:
        db.get(m.Document, document_id).quotation_version_id = v.id
    _supersede_previous(db, q, v.id, user)
    audit(db, user, "create_revision", "quotation_version", v.id, q.project_id, changes={"revision": next_rev, **data}, request=request)
    db.commit()
    db.refresh(q)
    return quotation_out(q)


@router.patch("/quotation-versions/{version_id}")
def edit_version(version_id: int, body: QuotationVersionIn, request: Request, db: Session = Depends(get_db),
                 user: m.User = Depends(require_roles(*FINANCE_ROLES))):
    v = db.get(m.QuotationVersion, version_id)
    if not v:
        raise not_found("Quotation revision")
    project = get_project_or_404(db, user, v.quotation.project_id)
    ensure_project_editable(project)
    if v.status in ("approved", "superseded"):
        raise APIError(409, f"A {v.status} revision cannot be edited. Create a new revision instead.", "locked")
    data = body.model_dump(exclude_unset=True, include=set(VERSION_FIELDS) | {"extraction_verified"})
    if "line_items" in data:
        data["line_items"] = body.model_dump(mode="json")["line_items"]
    changes = apply_changes(v, data)
    v.updated_by_id = user.id
    audit(db, user, "update", "quotation_version", v.id, project.id, changes=changes, request=request)
    db.commit()
    return quotation_out(v.quotation)


@router.post("/quotation-versions/{version_id}/status")
def change_status(version_id: int, body: QuotationStatusIn, request: Request, db: Session = Depends(get_db),
                  user: m.User = Depends(require_roles(*FINANCE_ROLES))):
    v = db.get(m.QuotationVersion, version_id)
    if not v:
        raise not_found("Quotation revision")
    q = v.quotation
    project = get_project_or_404(db, user, q.project_id)
    ensure_project_editable(project)
    current = effective_status(v)
    if body.status not in TRANSITIONS.get(current, set()):
        raise APIError(409, f"Cannot change a {current} quotation to {body.status}", "invalid_transition")
    if body.status == "approved":
        if v.total_amount is None:
            raise bad_request("Enter the total amount before approving")
        if v.extraction and not v.extraction_verified:
            raise bad_request("Automatically extracted values must be verified before approval")
        if _tax_check(v):
            raise bad_request("Subtotal + taxes does not equal the total. Correct the amounts before approving.")
        # only one approved quotation per project: supersede others
        others = db.scalars(
            select(m.QuotationVersion).join(m.Quotation)
            .where(m.Quotation.project_id == q.project_id, m.QuotationVersion.status == "approved", m.QuotationVersion.id != v.id)
        ).all()
        for o in others:
            o.status = "superseded"
            audit(db, user, "superseded", "quotation_version", o.id, q.project_id, changes={"superseded_by": v.id})
        _supersede_previous(db, q, v.id, user)
        v.approved_by_id = user.id
        v.approved_at = dt.datetime.now(dt.timezone.utc)
    old = v.status
    v.status = body.status
    if body.notes:
        v.notes = ((v.notes + "\n") if v.notes else "") + f"[{dt.date.today()} {user.full_name}] {body.notes}"
    audit(db, user, f"status_{body.status}", "quotation_version", v.id, q.project_id,
          changes={"status": {"from": old, "to": body.status}, "notes": body.notes}, request=request)
    db.commit()
    return quotation_out(q)
