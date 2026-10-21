import datetime as dt

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models as m
from ..core import (
    MANAGE_ROLES, apply_changes, audit, can_view_finance, conflict, like, not_found, page_response, paginate,
    visible_project_ids_subquery,
)
from ..db import get_db
from ..finance import compute_receivables, summarize
from ..schemas import ClientIn, ClientOut, ClientUpdate
from ..security import get_current_user, require_roles

router = APIRouter(prefix="/api/clients", tags=["clients"])


def _duplicate_check(db: Session, body, exclude_id: int | None = None):
    conds = []
    if body.company_name:
        conds.append(func.lower(m.Client.company_name) == body.company_name.lower())
    if body.gstin:
        conds.append(m.Client.gstin == body.gstin)
    if getattr(body, "email", None):
        conds.append(func.lower(m.Client.email) == body.email.lower())
    if not conds:
        return
    stmt = select(m.Client).where(or_(*conds))
    if exclude_id:
        stmt = stmt.where(m.Client.id != exclude_id)
    existing = db.scalar(stmt)
    if existing:
        raise conflict(
            f"A client with the same company name, GSTIN or email already exists: {existing.company_name}",
            {"existing_client_id": existing.id},
        )


@router.get("")
def list_clients(
    q: str | None = None, include_archived: bool = False, page: int = 1, page_size: int = 25,
    sort: str = "company_name", db: Session = Depends(get_db), user: m.User = Depends(get_current_user),
):
    count_sq = (
        select(m.Project.client_id, func.count().label("n")).where(m.Project.archived_at.is_(None)).group_by(m.Project.client_id).subquery()
    )
    stmt = select(m.Client)
    if user.role not in MANAGE_ROLES:
        stmt = stmt.where(m.Client.id.in_(select(m.Project.client_id).where(m.Project.id.in_(visible_project_ids_subquery(user)))))
    if not include_archived:
        stmt = stmt.where(m.Client.archived_at.is_(None))
    if q:
        t = like(q)
        stmt = stmt.where(or_(m.Client.name.ilike(t), m.Client.company_name.ilike(t), m.Client.contact_person.ilike(t),
                              m.Client.email.ilike(t), m.Client.gstin.ilike(t)))
    order = {"company_name": m.Client.company_name, "name": m.Client.name, "created_at": m.Client.created_at.desc()}.get(sort, m.Client.company_name)
    rows, total = paginate(db, stmt.order_by(order), page, page_size)
    counts = dict(db.execute(select(count_sq.c.client_id, count_sq.c.n).where(count_sq.c.client_id.in_([c.id for c in rows]))).all())
    items = []
    for c in rows:
        out = ClientOut.model_validate(c)
        out.project_count = counts.get(c.id, 0)
        items.append(out)
    return page_response(items, total, page, page_size)


@router.post("", status_code=201)
def create_client(body: ClientIn, request: Request, db: Session = Depends(get_db), user: m.User = Depends(require_roles(*MANAGE_ROLES))):
    _duplicate_check(db, body)
    c = m.Client(**body.model_dump(), created_by_id=user.id, updated_by_id=user.id)
    db.add(c)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise conflict("A client with this company name or GSTIN already exists")
    audit(db, user, "create", "client", c.id, changes=body.model_dump(), request=request)
    db.commit()
    return ClientOut.model_validate(c)


@router.get("/{client_id}")
def get_client(client_id: int, db: Session = Depends(get_db), user: m.User = Depends(get_current_user)):
    c = db.get(m.Client, client_id)
    if not c:
        raise not_found("Client")
    proj_stmt = select(m.Project).where(m.Project.client_id == client_id).order_by(m.Project.created_at.desc())
    if user.role not in MANAGE_ROLES:
        proj_stmt = proj_stmt.where(m.Project.id.in_(visible_project_ids_subquery(user)))
    projects = db.scalars(proj_stmt).all()
    if user.role not in MANAGE_ROLES and not projects:
        raise not_found("Client")
    out = {
        "client": ClientOut.model_validate(c),
        "projects": [
            {"id": p.id, "code": p.code, "name": p.name, "status": p.status, "progress": p.progress,
             "expected_completion_date": p.expected_completion_date, "archived_at": p.archived_at}
            for p in projects
        ],
    }
    if can_view_finance(user):
        pids = [p.id for p in projects]
        rec = compute_receivables(db, pids)
        out["receivables"] = {pid: r.as_dict() for pid, r in rec.items()}
        out["receivables_total"] = summarize(rec)
        qvs = db.execute(
            select(m.Quotation, m.QuotationVersion)
            .join(m.QuotationVersion, m.QuotationVersion.quotation_id == m.Quotation.id)
            .where(m.Quotation.client_id == client_id)
            .order_by(m.Quotation.id.desc(), m.QuotationVersion.revision_number.desc())
        ).all()
        out["quotations"] = [
            {"quotation_id": q.id, "version_id": v.id, "project_id": q.project_id, "quotation_number": q.quotation_number,
             "revision_number": v.revision_number, "status": v.status, "total_amount": v.total_amount,
             "currency": v.currency, "quotation_date": v.quotation_date}
            for q, v in qvs
        ]
        pos = db.scalars(select(m.ClientPurchaseOrder).where(m.ClientPurchaseOrder.client_id == client_id).order_by(m.ClientPurchaseOrder.id.desc())).all()
        out["purchase_orders"] = [
            {"id": p.id, "project_id": p.project_id, "po_number": p.po_number, "issue_date": p.issue_date,
             "total_value": p.total_value, "currency": p.currency, "status": p.status}
            for p in pos
        ]
        pays = db.scalars(select(m.PaymentReceived).where(m.PaymentReceived.client_id == client_id).order_by(m.PaymentReceived.id.desc()).limit(200)).all()
        out["payments"] = [
            {"id": p.id, "project_id": p.project_id, "amount": p.amount, "payment_date": p.payment_date,
             "due_date": p.due_date, "status": p.status, "invoice_reference": p.invoice_reference,
             "transaction_reference": p.transaction_reference}
            for p in pays
        ]
        invoices = sorted({p.invoice_reference for p in pays if p.invoice_reference})
        out["invoices"] = invoices
    return out


@router.patch("/{client_id}")
def update_client(client_id: int, body: ClientUpdate, request: Request, db: Session = Depends(get_db), user: m.User = Depends(require_roles(*MANAGE_ROLES))):
    c = db.get(m.Client, client_id)
    if not c:
        raise not_found("Client")
    data = body.model_dump(exclude_unset=True)
    for required in ("name", "company_name"):
        if required in data and not data[required]:
            data.pop(required)
    _duplicate_check(db, ClientUpdate(**{**data}), exclude_id=client_id)
    changes = apply_changes(c, data)
    c.updated_by_id = user.id
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise conflict("A client with this company name or GSTIN already exists")
    audit(db, user, "update", "client", c.id, changes=changes, request=request)
    db.commit()
    return ClientOut.model_validate(c)


@router.post("/{client_id}/archive")
def archive_client(client_id: int, request: Request, archived: bool = True, db: Session = Depends(get_db), user: m.User = Depends(require_roles(*MANAGE_ROLES))):
    c = db.get(m.Client, client_id)
    if not c:
        raise not_found("Client")
    c.archived_at = dt.datetime.now(dt.timezone.utc) if archived else None
    audit(db, user, "archive" if archived else "unarchive", "client", c.id, request=request)
    db.commit()
    return ClientOut.model_validate(c)
