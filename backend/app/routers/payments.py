import csv
import datetime as dt
import io

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .. import models as m
from ..core import (
    FINANCE_ROLES, APIError, apply_changes, audit, bad_request, conflict, get_project_or_404, like, not_found,
    page_response, paginate, snapshot, visible_project_ids_subquery,
)
from ..db import get_db
from ..finance import compute_receivables, overpayment_check, project_receivable, summarize
from ..schemas import PaymentIn, PaymentStatusIn, PaymentUpdate
from ..security import require_roles
from .projects import ensure_project_editable

router = APIRouter(prefix="/api", tags=["client payments"])
TRANSITIONS = {
    "pending": {"recorded", "verified", "failed"},
    "recorded": {"verified", "failed", "pending"},
    "verified": {"reversed"},
    "failed": set(),
    "reversed": set(),
}


def payment_out(p: m.PaymentReceived, project: m.Project | None = None) -> dict:
    d = snapshot(p)
    if project:
        d["project_code"] = project.code
        d["project_name"] = project.name
        d["currency"] = project.currency
    d["is_overdue"] = bool(p.status == "pending" and p.due_date and p.due_date < dt.date.today())
    return d


def lock_project(db: Session, project_id: int) -> m.Project:
    """Row lock serialises concurrent financial changes for the same project."""
    return db.execute(select(m.Project).where(m.Project.id == project_id).with_for_update()).scalar_one()


def _check_reference(db: Session, ref: str | None, exclude_id: int | None = None):
    if not ref:
        return
    stmt = select(m.PaymentReceived).where(func.lower(m.PaymentReceived.transaction_reference) == ref.lower())
    if exclude_id:
        stmt = stmt.where(m.PaymentReceived.id != exclude_id)
    existing = db.scalar(stmt)
    if existing:
        raise APIError(409, f"Transaction reference '{ref}' is already used by payment #{existing.id}", "duplicate_reference",
                       {"existing_payment_id": existing.id})


def _filtered(user: m.User, project_id=None, client_id=None, status=None, method=None, date_from=None, date_to=None,
              overdue=None, q=None, payment_type=None):
    stmt = select(m.PaymentReceived).where(m.PaymentReceived.project_id.in_(visible_project_ids_subquery(user)))
    if project_id:
        stmt = stmt.where(m.PaymentReceived.project_id == project_id)
    if client_id:
        stmt = stmt.where(m.PaymentReceived.client_id == client_id)
    if status:
        stmt = stmt.where(m.PaymentReceived.status.in_(status.split(",")))
    if method:
        stmt = stmt.where(m.PaymentReceived.method == method)
    if payment_type:
        stmt = stmt.where(m.PaymentReceived.payment_type == payment_type)
    date_col = func.coalesce(m.PaymentReceived.payment_date, m.PaymentReceived.due_date)
    if date_from:
        stmt = stmt.where(date_col >= date_from)
    if date_to:
        stmt = stmt.where(date_col <= date_to)
    if overdue:
        stmt = stmt.where(m.PaymentReceived.status == "pending", m.PaymentReceived.due_date < dt.date.today())
    if q:
        t = like(q)
        stmt = stmt.where(or_(m.PaymentReceived.transaction_reference.ilike(t), m.PaymentReceived.invoice_reference.ilike(t),
                              m.PaymentReceived.bank_reference.ilike(t), m.PaymentReceived.notes.ilike(t),
                              m.PaymentReceived.milestone_label.ilike(t)))
    return stmt


@router.get("/payments")
def list_payments(
    project_id: int | None = None, client_id: int | None = None, status: str | None = None, method: str | None = None,
    payment_type: str | None = None, date_from: dt.date | None = None, date_to: dt.date | None = None,
    overdue: bool | None = None, q: str | None = None, page: int = 1, page_size: int = 25,
    db: Session = Depends(get_db), user: m.User = Depends(require_roles(*FINANCE_ROLES)),
):
    stmt = _filtered(user, project_id, client_id, status, method, date_from, date_to, overdue, q, payment_type)
    stmt = stmt.order_by(func.coalesce(m.PaymentReceived.payment_date, m.PaymentReceived.due_date).desc(), m.PaymentReceived.id.desc())
    rows, total = paginate(db, stmt, page, page_size)
    projects = {p.id: p for p in db.scalars(select(m.Project).where(m.Project.id.in_({r.project_id for r in rows}))).all()}
    return page_response([payment_out(r, projects.get(r.project_id)) for r in rows], total, page, page_size)


@router.get("/payments/summary")
def payments_summary(client_id: int | None = None, status: str | None = None, include_archived: bool = False,
                     db: Session = Depends(get_db), user: m.User = Depends(require_roles(*FINANCE_ROLES))):
    stmt = select(m.Project).where(m.Project.id.in_(visible_project_ids_subquery(user)))
    if not include_archived:
        stmt = stmt.where(m.Project.archived_at.is_(None))
    if client_id:
        stmt = stmt.where(m.Project.client_id == client_id)
    if status:
        stmt = stmt.where(m.Project.status.in_(status.split(",")))
    projects = db.scalars(stmt.order_by(m.Project.code)).all()
    rec = compute_receivables(db, [p.id for p in projects])
    return {
        "totals_by_currency": summarize(rec),
        "projects": [{"project_id": p.id, "code": p.code, "name": p.name, "client": p.client.company_name, "status": p.status,
                      **rec[p.id].as_dict()} for p in projects],
        "note": "Client receivables only. Supplier payments are tracked separately under BOM Purchase Orders.",
    }


@router.get("/projects/{project_id}/payments")
def project_payments(project_id: int, db: Session = Depends(get_db), user: m.User = Depends(require_roles(*FINANCE_ROLES))):
    p = get_project_or_404(db, user, project_id)
    rows = db.scalars(select(m.PaymentReceived).where(m.PaymentReceived.project_id == p.id)
                      .order_by(func.coalesce(m.PaymentReceived.payment_date, m.PaymentReceived.due_date).desc(), m.PaymentReceived.id.desc())).all()
    pos = db.scalars(select(m.ClientPurchaseOrder).where(m.ClientPurchaseOrder.project_id == p.id)).all()
    return {
        "receivable": project_receivable(db, p.id).as_dict(),
        "payments": [payment_out(r, p) for r in rows],
        "client_pos": [{"id": po.id, "po_number": po.po_number, "status": po.status, "total_value": po.total_value} for po in pos],
    }


@router.post("/payments", status_code=201)
def create_payment(body: PaymentIn, request: Request, db: Session = Depends(get_db), user: m.User = Depends(require_roles(*FINANCE_ROLES))):
    get_project_or_404(db, user, body.project_id)
    project = lock_project(db, body.project_id)
    ensure_project_editable(project)
    if body.client_po_id:
        po = db.get(m.ClientPurchaseOrder, body.client_po_id)
        if not po or po.project_id != project.id:
            raise bad_request("Selected client PO belongs to a different project")
    _check_reference(db, body.transaction_reference)
    if not body.confirm_possible_duplicate and body.status == "recorded":
        dup = db.scalar(select(m.PaymentReceived).where(
            m.PaymentReceived.project_id == project.id, m.PaymentReceived.amount == body.amount,
            m.PaymentReceived.payment_date == body.payment_date, m.PaymentReceived.status.not_in(["failed", "reversed"])))
        if dup:
            raise APIError(409, f"A payment of the same amount on the same date already exists (#{dup.id}). Confirm if this is a separate payment.",
                           "possible_duplicate", {"existing_payment_id": dup.id})
    if body.status == "recorded" and not body.allow_overpayment:
        warning = overpayment_check(db, project.id, body.amount)
        if warning:
            raise APIError(409, warning + " Confirm to record it; the excess will be shown as credit.", "overpayment",
                           {"receivable": project_receivable(db, project.id).as_dict()})
    data = body.model_dump(exclude={"allow_overpayment", "confirm_possible_duplicate"})
    pay = m.PaymentReceived(**data, client_id=project.client_id, created_by_id=user.id, updated_by_id=user.id)
    db.add(pay)
    db.flush()
    audit(db, user, "create", "payment", pay.id, project.id,
          changes={**body.model_dump(mode="json"), "overpayment_confirmed": body.allow_overpayment}, request=request)
    db.commit()
    return {"payment": payment_out(pay, project), "receivable": project_receivable(db, project.id).as_dict()}


@router.patch("/payments/{payment_id}")
def update_payment(payment_id: int, body: PaymentUpdate, request: Request, db: Session = Depends(get_db),
                   user: m.User = Depends(require_roles(*FINANCE_ROLES))):
    pay = db.get(m.PaymentReceived, payment_id)
    if not pay:
        raise not_found("Payment")
    get_project_or_404(db, user, pay.project_id)
    project = lock_project(db, pay.project_id)
    ensure_project_editable(project)
    if pay.status not in ("recorded", "pending"):
        raise APIError(409, f"A {pay.status} payment cannot be edited. Reverse it and record a corrected payment.", "locked")
    data = body.model_dump(exclude_unset=True, exclude={"allow_overpayment"})
    if "transaction_reference" in data:
        _check_reference(db, data["transaction_reference"], exclude_id=pay.id)
    if data.get("client_po_id"):
        po = db.get(m.ClientPurchaseOrder, data["client_po_id"])
        if not po or po.project_id != pay.project_id:
            raise bad_request("Selected client PO belongs to a different project")
    new_date = data.get("payment_date", pay.payment_date)
    if new_date and new_date > dt.date.today():
        raise bad_request("Payment date cannot be in the future")
    if pay.status == "recorded" and "amount" in data and not body.allow_overpayment:
        warning = overpayment_check(db, pay.project_id, data["amount"], exclude_payment_id=pay.id)
        if warning:
            raise APIError(409, warning, "overpayment")
    changes = apply_changes(pay, data)
    pay.updated_by_id = user.id
    audit(db, user, "update", "payment", pay.id, pay.project_id, changes=changes, request=request)
    db.commit()
    return {"payment": payment_out(pay, project), "receivable": project_receivable(db, pay.project_id).as_dict()}


@router.post("/payments/{payment_id}/status")
def change_payment_status(payment_id: int, body: PaymentStatusIn, request: Request, db: Session = Depends(get_db),
                          user: m.User = Depends(require_roles(*FINANCE_ROLES))):
    pay = db.get(m.PaymentReceived, payment_id)
    if not pay:
        raise not_found("Payment")
    get_project_or_404(db, user, pay.project_id)
    project = lock_project(db, pay.project_id)
    ensure_project_editable(project)
    if body.status not in TRANSITIONS.get(pay.status, set()):
        raise APIError(409, f"Cannot change a {pay.status} payment to {body.status}", "invalid_transition")
    if body.status in ("recorded", "verified"):
        if body.payment_date:
            if body.payment_date > dt.date.today():
                raise bad_request("Payment date cannot be in the future")
            pay.payment_date = body.payment_date
        if not pay.payment_date:
            raise bad_request("Enter the date the payment was received")
        if pay.status == "pending" and not body.allow_overpayment:
            warning = overpayment_check(db, pay.project_id, pay.amount, exclude_payment_id=pay.id)
            if warning:
                raise APIError(409, warning + " Confirm to continue; the excess will be shown as credit.", "overpayment")
    if body.status == "verified":
        pay.verified_by_id = user.id
        pay.verified_at = dt.datetime.now(dt.timezone.utc)
    old = pay.status
    pay.status = body.status
    if body.notes:
        pay.notes = ((pay.notes + "\n") if pay.notes else "") + f"[{dt.date.today()} {user.full_name}] {body.notes}"
    audit(db, user, f"status_{body.status}", "payment", pay.id, pay.project_id,
          changes={"status": {"from": old, "to": body.status}, "amount": str(pay.amount), "notes": body.notes}, request=request)
    db.commit()
    return {"payment": payment_out(pay, project), "receivable": project_receivable(db, pay.project_id).as_dict()}


@router.get("/payments/export")
def export_payments(
    format: str = "xlsx", project_id: int | None = None, client_id: int | None = None, status: str | None = None,
    date_from: dt.date | None = None, date_to: dt.date | None = None,
    db: Session = Depends(get_db), user: m.User = Depends(require_roles(*FINANCE_ROLES)),
):
    stmt = _filtered(user, project_id, client_id, status, None, date_from, date_to).order_by(m.PaymentReceived.id)
    rows = db.scalars(stmt).all()
    projects = {p.id: p for p in db.scalars(select(m.Project).where(m.Project.id.in_({r.project_id for r in rows}))).all()}
    header = ["ID", "Project", "Client", "Amount", "Currency", "Status", "Type", "Milestone", "Payment date", "Due date",
              "Method", "Transaction ref", "Bank ref", "Invoice ref", "Notes"]
    data = [[r.id, projects[r.project_id].code, projects[r.project_id].client.company_name, float(r.amount),
             projects[r.project_id].currency, r.status, r.payment_type, r.milestone_label or "", r.payment_date, r.due_date,
             r.method or "", r.transaction_reference or "", r.bank_reference or "", r.invoice_reference or "", r.notes or ""]
            for r in rows]
    stamp = dt.date.today().isoformat()
    if format == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(header)
        for row in data:
            w.writerow(["" if v is None else _csv_safe(v) for v in row])
        return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                                 headers={"Content-Disposition": f'attachment; filename="client-payments-{stamp}.csv"'})
    from ..exports import xlsx_bytes

    summary = summarize(compute_receivables(db, list(projects)))
    content = xlsx_bytes([("Payments", header, data),
                          ("Summary", ["Currency", "Contract value (X)", "Verified received (Y)", "Outstanding (Z)", "Credit"],
                           [[c, float(v["contract_value"]), float(v["verified_received"]), float(v["outstanding"]), float(v["credit"])]
                            for c, v in summary.items()])])
    return StreamingResponse(iter([content]), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition": f'attachment; filename="client-payments-{stamp}.xlsx"'})


def _csv_safe(v):
    """Neutralise spreadsheet formula injection."""
    if isinstance(v, str) and v[:1] in ("=", "+", "-", "@"):
        return "'" + v
    return v
