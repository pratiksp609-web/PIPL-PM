"""Server-side financial calculations.

Client receivables:  X - Y = Z
  X = approved contract value (sum of verified client POs; else the approved quotation; else the
      project's manually approved contract value)
  Y = total *verified* client payments received
  Z = outstanding receivable (never negative; any excess is reported separately as credit)

Supplier-side money (supplier POs and supplier payments) is calculated separately and is never
included in client receivables.
"""
from __future__ import annotations

import datetime as dt
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from decimal import Decimal

from sqlalchemy import and_, case, func, select
from sqlalchemy.orm import Session

from . import models as m

ZERO = Decimal("0.00")


def q2(v) -> Decimal:
    return (Decimal(v) if v is not None else ZERO).quantize(Decimal("0.01"))


@dataclass
class Receivable:
    project_id: int
    currency: str = "INR"
    contract_value: Decimal = ZERO  # X
    contract_basis: str = "not_set"
    verified_received: Decimal = ZERO  # Y
    outstanding: Decimal = ZERO  # Z
    credit: Decimal = ZERO  # overpayment, shown separately
    unverified_recorded: Decimal = ZERO
    expected_pending: Decimal = ZERO
    overdue_pending: Decimal = ZERO
    overdue_count: int = 0
    failed_or_reversed: Decimal = ZERO
    payment_count: int = 0
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        d = asdict(self)
        for k, v in d.items():
            if isinstance(v, Decimal):
                d[k] = str(q2(v))
        d["formula"] = "X - Y = Z"
        return d


def compute_receivables(db: Session, project_ids: list[int] | None = None, as_of: dt.date | None = None) -> dict[int, Receivable]:
    as_of = as_of or dt.date.today()
    proj_stmt = select(m.Project.id, m.Project.currency, m.Project.contract_value)
    if project_ids is not None:
        if not project_ids:
            return {}
        proj_stmt = proj_stmt.where(m.Project.id.in_(project_ids))
    projects = db.execute(proj_stmt).all()
    ids = [p.id for p in projects]
    result: dict[int, Receivable] = {p.id: Receivable(project_id=p.id, currency=p.currency) for p in projects}
    if not ids:
        return result

    po_rows = db.execute(
        select(m.ClientPurchaseOrder.project_id, func.sum(m.ClientPurchaseOrder.total_value), func.count())
        .where(m.ClientPurchaseOrder.project_id.in_(ids), m.ClientPurchaseOrder.status == "verified")
        .group_by(m.ClientPurchaseOrder.project_id)
    ).all()
    po_totals = {r[0]: (r[1], r[2]) for r in po_rows}

    approved_rows = db.execute(
        select(m.Quotation.project_id, func.max(m.QuotationVersion.total_amount))
        .join(m.QuotationVersion, m.QuotationVersion.quotation_id == m.Quotation.id)
        .where(m.Quotation.project_id.in_(ids), m.QuotationVersion.status == "approved")
        .group_by(m.Quotation.project_id)
    ).all()
    approved = {r[0]: r[1] for r in approved_rows}

    for p in projects:
        r = result[p.id]
        if p.id in po_totals and po_totals[p.id][0] is not None:
            r.contract_value = q2(po_totals[p.id][0])
            r.contract_basis = "verified_client_po"
        elif approved.get(p.id) is not None:
            r.contract_value = q2(approved[p.id])
            r.contract_basis = "approved_quotation"
            r.notes.append("No verified client PO yet; contract value uses the approved quotation.")
        elif p.contract_value is not None:
            r.contract_value = q2(p.contract_value)
            r.contract_basis = "project_contract_value"
            r.notes.append("No verified client PO or approved quotation; using the project's approved contract value.")
        else:
            r.notes.append("Contract value not set: verify a client PO, approve a quotation, or set the project contract value.")

    pay = m.PaymentReceived
    pay_rows = db.execute(
        select(
            pay.project_id,
            func.coalesce(func.sum(case((pay.status == "verified", pay.amount))), 0),
            func.coalesce(func.sum(case((pay.status == "recorded", pay.amount))), 0),
            func.coalesce(func.sum(case((pay.status == "pending", pay.amount))), 0),
            func.coalesce(func.sum(case((and_(pay.status == "pending", pay.due_date < as_of), pay.amount))), 0),
            func.count(case((and_(pay.status == "pending", pay.due_date < as_of), 1))),
            func.coalesce(func.sum(case((pay.status.in_(["failed", "reversed"]), pay.amount))), 0),
            func.count(),
        )
        .where(pay.project_id.in_(ids))
        .group_by(pay.project_id)
    ).all()
    for row in pay_rows:
        r = result[row[0]]
        r.verified_received = q2(row[1])
        r.unverified_recorded = q2(row[2])
        r.expected_pending = q2(row[3])
        r.overdue_pending = q2(row[4])
        r.overdue_count = int(row[5])
        r.failed_or_reversed = q2(row[6])
        r.payment_count = int(row[7])

    for r in result.values():
        diff = r.contract_value - r.verified_received
        if diff >= 0:
            r.outstanding = q2(diff)
        else:
            r.outstanding = ZERO
            r.credit = q2(-diff)
            r.notes.append("Verified payments exceed the contract value; the excess is shown as credit/overpayment.")
    return result


def project_receivable(db: Session, project_id: int) -> Receivable:
    return compute_receivables(db, [project_id])[project_id]


def summarize(receivables: dict[int, Receivable]) -> dict:
    """Company-wide totals grouped by currency (amounts in different currencies are never summed)."""
    by_cur: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(lambda: ZERO))
    for r in receivables.values():
        t = by_cur[r.currency]
        t["contract_value"] += r.contract_value
        t["verified_received"] += r.verified_received
        t["outstanding"] += r.outstanding
        t["credit"] += r.credit
        t["unverified_recorded"] += r.unverified_recorded
        t["expected_pending"] += r.expected_pending
        t["overdue_pending"] += r.overdue_pending
    return {cur: {k: str(q2(v)) for k, v in vals.items()} for cur, vals in by_cur.items()}


def overpayment_check(db: Session, project_id: int, amount: Decimal, exclude_payment_id: int | None = None) -> str | None:
    """Return a warning if received payments (verified + recorded) plus `amount` would exceed X."""
    r = project_receivable(db, project_id)
    received = r.verified_received + r.unverified_recorded
    if exclude_payment_id:
        p = db.get(m.PaymentReceived, exclude_payment_id)
        if p and p.status in ("verified", "recorded"):
            received -= p.amount
    if r.contract_value == 0:
        return "No approved contract value exists for this project yet, so this payment cannot be checked against X."
    new_total = received + Decimal(amount)
    if new_total > r.contract_value:
        return (
            f"This payment would bring received payments to {q2(new_total)} {r.currency}, exceeding the approved "
            f"contract value of {r.contract_value} {r.currency} by {q2(new_total - r.contract_value)}."
        )
    return None


# ---------------------------------------------------------------- procurement (supplier side)
def recalc_supplier_po(po: m.SupplierPurchaseOrder) -> None:
    subtotal = ZERO
    tax = ZERO
    for item in po.items:
        amount = q2(Decimal(item.quantity) * Decimal(item.unit_price))
        item.amount = amount
        subtotal += amount
        tax += q2(amount * Decimal(item.tax_rate) / Decimal(100))
    po.subtotal = q2(subtotal)
    po.tax_amount = q2(tax)
    po.total_amount = q2(subtotal + tax)


def procurement_summary(db: Session, project_id: int, as_of: dt.date | None = None) -> dict:
    as_of = as_of or dt.date.today()
    items = db.scalars(select(m.BOMItem).where(m.BOMItem.project_id == project_id, m.BOMItem.deleted_at.is_(None))).all()
    estimated = sum((q2(Decimal(i.quantity) * (i.estimated_rate or 0)) for i in items if i.procurement_status != "cancelled"), ZERO)
    pos = db.scalars(select(m.SupplierPurchaseOrder).where(m.SupplierPurchaseOrder.project_id == project_id)).all()
    active_pos = [p for p in pos if p.status not in ("cancelled", "draft")]
    committed = sum((p.total_amount for p in active_pos), ZERO)
    committed_pre_tax = sum((p.subtotal for p in active_pos), ZERO)
    paid = db.scalar(
        select(func.coalesce(func.sum(m.SupplierPayment.amount), 0)).where(
            m.SupplierPayment.project_id == project_id, m.SupplierPayment.status != "reversed"
        )
    )
    late = [
        p for p in active_pos
        if p.delivery_date and p.delivery_date < as_of and p.status not in ("received",)
    ]
    linked_bom_ids = set(
        db.scalars(
            select(m.SupplierPOItem.bom_item_id)
            .join(m.SupplierPurchaseOrder)
            .where(m.SupplierPurchaseOrder.project_id == project_id, m.SupplierPurchaseOrder.status != "cancelled",
                   m.SupplierPOItem.bom_item_id.is_not(None))
        ).all()
    )
    pending_items = [i for i in items if i.procurement_status in ("pending", "rfq") and i.id not in linked_bom_ids]
    late_items = [
        i for i in items
        if i.required_date and i.required_date < as_of and i.procurement_status not in ("received", "cancelled")
    ]
    status_counts: dict[str, int] = defaultdict(int)
    for i in items:
        status_counts[i.procurement_status] += 1
    return {
        "bom_item_count": len(items),
        "status_counts": dict(status_counts),
        "estimated_cost": str(q2(estimated)),
        "committed_cost": str(q2(committed)),
        "committed_cost_pre_tax": str(q2(committed_pre_tax)),
        "variance_pre_tax": str(q2(committed_pre_tax - estimated)),
        "supplier_paid": str(q2(paid)),
        "supplier_outstanding": str(q2(committed - Decimal(paid))),
        "supplier_po_count": len(pos),
        "pending_procurement_count": len(pending_items),
        "pending_procurement": [{"id": i.id, "item_name": i.item_name, "required_date": i.required_date} for i in pending_items[:20]],
        "late_deliveries": [
            {"id": p.id, "po_number": p.po_number, "supplier": p.supplier.name if p.supplier else None,
             "delivery_date": p.delivery_date, "days_late": (as_of - p.delivery_date).days}
            for p in late
        ],
        "late_bom_items": [{"id": i.id, "item_name": i.item_name, "required_date": i.required_date} for i in late_items[:20]],
        "pos_missing_documents": [{"id": p.id, "po_number": p.po_number} for p in pos if not p.document_id and p.status != "cancelled"],
        "note": "Committed cost comes from supplier POs only (BOM actual rates are informational) to avoid double counting.",
    }
