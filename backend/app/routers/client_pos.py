import datetime as dt
import difflib
import re
from decimal import Decimal

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .. import models as m
from ..core import (
    FINANCE_ROLES, APIError, apply_changes, audit, bad_request, conflict, get_project_or_404, like, not_found, snapshot,
    visible_project_ids_subquery,
)
from ..db import get_db
from ..schemas import ClientPODecision, ClientPOIn, ClientPOUpdate
from ..security import require_roles
from .projects import ensure_project_editable

router = APIRouter(prefix="/api/client-pos", tags=["client purchase orders"])
TRANSITIONS = {
    "received": {"under_review", "verified", "rejected", "cancelled"},
    "under_review": {"verified", "rejected", "received", "cancelled"},
    "rejected": {"under_review"},
    "verified": {"under_review", "cancelled"},
    "cancelled": set(),
}


def po_out(po: m.ClientPurchaseOrder) -> dict:
    d = snapshot(po)
    d["document"] = {"id": po.document.id, "title": po.document.title, "extension": po.document.extension,
                     "original_filename": po.document.original_filename} if po.document else None
    return d


def _norm(s: str | None) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def _num(v) -> Decimal | None:
    if v is None or v == "":
        return None
    try:
        return Decimal(str(v))
    except Exception:
        return None


def compare(po: m.ClientPurchaseOrder, qv: m.QuotationVersion | None) -> dict:
    """Field-by-field comparison. Discrepancies are reported for manual review, never auto-approved."""
    if qv is None:
        return {"quotation_version_id": None, "rows": [], "line_items": [], "discrepancy_count": 0,
                "message": "No approved quotation found for this project to compare against."}
    rows = []

    def money_row(label, qval, pval):
        qd, pd = _num(qval), _num(pval)
        if qd is None or pd is None:
            status = "missing"
        else:
            status = "match" if abs(qd - pd) <= Decimal("0.5") else "mismatch"
        rows.append({"field": label, "quotation": str(qd) if qd is not None else None, "po": str(pd) if pd is not None else None,
                     "difference": str(pd - qd) if (qd is not None and pd is not None) else None, "status": status})

    def text_row(label, qval, pval):
        if not qval or not pval:
            status = "missing"
            ratio = None
        else:
            ratio = difflib.SequenceMatcher(None, _norm(qval), _norm(pval)).ratio()
            status = "match" if ratio >= 0.9 else "mismatch"
        rows.append({"field": label, "quotation": qval, "po": pval, "similarity": round(ratio, 2) if ratio is not None else None, "status": status})

    money_row("Subtotal / PO value (pre-tax)", qv.subtotal, po.po_value)
    money_row("Taxes", qv.tax_amount, po.tax_amount)
    money_row("Total amount", qv.total_amount, po.total_value)
    rows.append({"field": "Currency", "quotation": qv.currency, "po": po.currency,
                 "status": "match" if qv.currency == po.currency else "mismatch"})
    text_row("Payment terms", qv.payment_terms, po.payment_terms)
    text_row("Delivery terms", qv.delivery_terms, po.delivery_terms)
    qd, pd = qv.delivery_date, po.delivery_date
    rows.append({"field": "Delivery date", "quotation": qd.isoformat() if qd else None, "po": pd.isoformat() if pd else None,
                 "difference": f"{(pd - qd).days} days" if qd and pd else None,
                 "status": "missing" if not (qd and pd) else ("match" if qd == pd else "mismatch")})
    text_row("Scope", qv.scope, po.scope)

    q_items = list(qv.line_items or [])
    p_items = list(po.line_items or [])
    used = set()
    item_rows = []
    for qi in q_items:
        best, best_ratio = None, 0.0
        for idx, pi in enumerate(p_items):
            if idx in used:
                continue
            r = difflib.SequenceMatcher(None, _norm(qi.get("description")), _norm(pi.get("description"))).ratio()
            if r > best_ratio:
                best, best_ratio = idx, r
        if best is not None and best_ratio >= 0.75:
            used.add(best)
            pi = p_items[best]
            diffs = []
            for key in ("quantity", "unit_price", "amount"):
                a, b = _num(qi.get(key)), _num(pi.get(key))
                if a is not None and b is not None and abs(a - b) > Decimal("0.01"):
                    diffs.append({"field": key, "quotation": str(a), "po": str(b)})
            item_rows.append({"description": qi.get("description"), "po_description": pi.get("description"),
                              "status": "mismatch" if diffs else "match", "differences": diffs, "quotation": qi, "po": pi})
        else:
            item_rows.append({"description": qi.get("description"), "status": "missing_in_po", "differences": [], "quotation": qi, "po": None})
    for idx, pi in enumerate(p_items):
        if idx not in used:
            item_rows.append({"description": pi.get("description"), "status": "extra_in_po", "differences": [], "quotation": None, "po": pi})

    discrepancies = sum(1 for r in rows if r["status"] == "mismatch") + sum(1 for r in item_rows if r["status"] != "match")
    return {
        "quotation_version_id": qv.id, "quotation_number": qv.quotation.quotation_number, "revision_number": qv.revision_number,
        "rows": rows, "line_items": item_rows, "discrepancy_count": discrepancies,
        "missing_count": sum(1 for r in rows if r["status"] == "missing"),
        "message": "Differences are shown for manual review. Nothing is approved automatically.",
    }


def _approved_quotation(db: Session, project_id: int) -> m.QuotationVersion | None:
    return db.scalar(
        select(m.QuotationVersion).join(m.Quotation)
        .where(m.Quotation.project_id == project_id, m.QuotationVersion.status == "approved")
        .order_by(m.QuotationVersion.approved_at.desc()).limit(1)
    )


def _qv_for(db: Session, po: m.ClientPurchaseOrder) -> m.QuotationVersion | None:
    if po.quotation_version_id:
        return db.get(m.QuotationVersion, po.quotation_version_id)
    return _approved_quotation(db, po.project_id)


@router.get("")
def list_pos(project_id: int | None = None, client_id: int | None = None, status: str | None = None, q: str | None = None,
             db: Session = Depends(get_db), user: m.User = Depends(require_roles(*FINANCE_ROLES))):
    stmt = select(m.ClientPurchaseOrder).where(m.ClientPurchaseOrder.project_id.in_(visible_project_ids_subquery(user)))
    if project_id:
        stmt = stmt.where(m.ClientPurchaseOrder.project_id == project_id)
    if client_id:
        stmt = stmt.where(m.ClientPurchaseOrder.client_id == client_id)
    if status:
        stmt = stmt.where(m.ClientPurchaseOrder.status.in_(status.split(",")))
    if q:
        stmt = stmt.where(or_(m.ClientPurchaseOrder.po_number.ilike(like(q)), m.ClientPurchaseOrder.scope.ilike(like(q))))
    rows = db.scalars(stmt.order_by(m.ClientPurchaseOrder.id.desc()).limit(500)).all()
    return {"items": [po_out(p) for p in rows], "total": len(rows)}


@router.post("", status_code=201)
def create_po(body: ClientPOIn, request: Request, db: Session = Depends(get_db), user: m.User = Depends(require_roles(*FINANCE_ROLES))):
    project = get_project_or_404(db, user, body.project_id)
    ensure_project_editable(project)
    if db.scalar(select(m.ClientPurchaseOrder).where(m.ClientPurchaseOrder.client_id == project.client_id,
                                                     func.lower(m.ClientPurchaseOrder.po_number) == body.po_number.lower())):
        raise conflict(f"Client PO {body.po_number} already exists for this client")
    if body.document_id:
        d = db.get(m.Document, body.document_id)
        if not d or d.project_id != project.id or d.deleted_at:
            raise bad_request("Attached document does not exist or belongs to another project")
    if body.quotation_version_id:
        qv = db.get(m.QuotationVersion, body.quotation_version_id)
        if not qv or qv.quotation.project_id != project.id:
            raise bad_request("Selected quotation belongs to a different project")
    data = body.model_dump(exclude={"project_id", "line_items", "extraction_verified"})
    po = m.ClientPurchaseOrder(project_id=project.id, client_id=project.client_id, **data,
                               line_items=body.model_dump(mode="json")["line_items"],
                               extraction_verified=bool(body.extraction_verified), created_by_id=user.id, updated_by_id=user.id)
    db.add(po)
    db.flush()
    if body.document_id:
        db.get(m.Document, body.document_id).client_po_id = po.id
    audit(db, user, "create", "client_po", po.id, project.id, changes=body.model_dump(mode="json"), request=request)
    db.commit()
    return po_out(po)


@router.get("/{po_id}")
def get_po(po_id: int, db: Session = Depends(get_db), user: m.User = Depends(require_roles(*FINANCE_ROLES))):
    po = db.get(m.ClientPurchaseOrder, po_id)
    if not po:
        raise not_found("Client PO")
    get_project_or_404(db, user, po.project_id)
    history = db.scalars(select(m.AuditLog).where(m.AuditLog.entity_type == "client_po", m.AuditLog.entity_id == po.id)
                         .order_by(m.AuditLog.id.desc())).all()
    return {
        "po": po_out(po),
        "comparison": compare(po, _qv_for(db, po)),
        "history": [{"action": h.action, "changes": h.changes, "user": h.user.full_name if h.user else None,
                     "created_at": h.created_at} for h in history],
    }


@router.patch("/{po_id}")
def update_po(po_id: int, body: ClientPOUpdate, request: Request, db: Session = Depends(get_db), user: m.User = Depends(require_roles(*FINANCE_ROLES))):
    po = db.get(m.ClientPurchaseOrder, po_id)
    if not po:
        raise not_found("Client PO")
    project = get_project_or_404(db, user, po.project_id)
    ensure_project_editable(project)
    if po.status in ("verified", "cancelled"):
        raise APIError(409, f"A {po.status} PO cannot be edited. Move it back to review first.", "locked")
    data = body.model_dump(exclude_unset=True)
    if "line_items" in data:
        data["line_items"] = body.model_dump(mode="json")["line_items"]
    if data.get("po_number") and data["po_number"].lower() != po.po_number.lower():
        if db.scalar(select(m.ClientPurchaseOrder).where(m.ClientPurchaseOrder.client_id == po.client_id,
                                                         func.lower(m.ClientPurchaseOrder.po_number) == data["po_number"].lower())):
            raise conflict("Another PO with this number exists for the client")
    changes = apply_changes(po, data)
    po.updated_by_id = user.id
    audit(db, user, "update", "client_po", po.id, po.project_id, changes=changes, request=request)
    db.commit()
    return po_out(po)


@router.post("/{po_id}/decision")
def decide(po_id: int, body: ClientPODecision, request: Request, acknowledge_discrepancies: bool = False,
           db: Session = Depends(get_db), user: m.User = Depends(require_roles(*FINANCE_ROLES))):
    po = db.get(m.ClientPurchaseOrder, po_id)
    if not po:
        raise not_found("Client PO")
    project = get_project_or_404(db, user, po.project_id)
    ensure_project_editable(project)
    if body.status not in TRANSITIONS.get(po.status, set()):
        raise APIError(409, f"Cannot move a {po.status} PO to {body.status}", "invalid_transition")
    comparison = None
    if body.status == "verified":
        if po.total_value is None:
            raise bad_request("Enter the total approved value before verifying the PO")
        if po.extraction and not po.extraction_verified:
            raise bad_request("Automatically extracted values must be verified before the PO can be verified")
        comparison = compare(po, _qv_for(db, po))
        if comparison["discrepancy_count"] and not (acknowledge_discrepancies and body.review_notes):
            raise APIError(409, f"The PO has {comparison['discrepancy_count']} discrepancies against the approved quotation. "
                                "Review them and add review notes to confirm verification.", "discrepancies",
                           {"discrepancy_count": comparison["discrepancy_count"]})
        po.verified_by_id = user.id
        po.verified_at = dt.datetime.now(dt.timezone.utc)
    old = po.status
    po.status = body.status
    if body.review_notes:
        po.review_notes = ((po.review_notes + "\n") if po.review_notes else "") + f"[{dt.date.today()} {user.full_name}] {body.review_notes}"
    audit(db, user, f"decision_{body.status}", "client_po", po.id, po.project_id,
          changes={"status": {"from": old, "to": body.status}, "notes": body.review_notes,
                   "discrepancies": comparison["discrepancy_count"] if comparison else None}, request=request)
    db.commit()
    return po_out(po)
