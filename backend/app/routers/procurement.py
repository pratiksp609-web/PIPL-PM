"""Suppliers, BOM items, supplier purchase orders and supplier payments (money paid OUT)."""
import datetime as dt
from decimal import Decimal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from .. import models as m
from ..core import (
    FINANCE_ROLES, MANAGE_ROLES, APIError, apply_changes, audit, bad_request, can_view_finance, conflict,
    get_project_or_404, like, not_found, page_response, paginate, snapshot, visible_project_ids_subquery,
)
from ..db import get_db
from ..finance import procurement_summary, q2, recalc_supplier_po
from ..schemas import (
    BOMItemIn, BOMItemUpdate, SupplierIn, SupplierPaymentIn, SupplierPaymentStatusIn, SupplierPOIn, SupplierPOUpdate,
)
from ..security import get_current_user, require_roles
from .projects import ensure_project_editable

router = APIRouter(prefix="/api", tags=["procurement"])


# ---------------------------------------------------------------- suppliers
def supplier_out(s: m.Supplier) -> dict:
    return snapshot(s, ["id", "name", "contact_person", "email", "phone", "address", "gstin", "is_sample", "archived_at", "created_at"])


@router.get("/suppliers")
def list_suppliers(q: str | None = None, include_archived: bool = False, page: int = 1, page_size: int = 100,
                   db: Session = Depends(get_db), user: m.User = Depends(get_current_user)):
    stmt = select(m.Supplier)
    if not include_archived:
        stmt = stmt.where(m.Supplier.archived_at.is_(None))
    if q:
        stmt = stmt.where(or_(m.Supplier.name.ilike(like(q)), m.Supplier.contact_person.ilike(like(q)), m.Supplier.gstin.ilike(like(q))))
    rows, total = paginate(db, stmt.order_by(m.Supplier.name), page, page_size)
    return page_response([supplier_out(s) for s in rows], total, page, page_size)


@router.post("/suppliers", status_code=201)
def create_supplier(body: SupplierIn, request: Request, db: Session = Depends(get_db), user: m.User = Depends(require_roles(*MANAGE_ROLES))):
    existing = db.scalar(select(m.Supplier).where(func.lower(m.Supplier.name) == body.name.lower()))
    if existing:
        raise conflict(f"Supplier '{existing.name}' already exists", {"existing_supplier_id": existing.id})
    s = m.Supplier(**body.model_dump(), created_by_id=user.id, updated_by_id=user.id)
    db.add(s)
    db.flush()
    audit(db, user, "create", "supplier", s.id, changes=body.model_dump(), request=request)
    db.commit()
    return supplier_out(s)


@router.patch("/suppliers/{supplier_id}")
def update_supplier(supplier_id: int, body: SupplierIn, request: Request, db: Session = Depends(get_db), user: m.User = Depends(require_roles(*MANAGE_ROLES))):
    s = db.get(m.Supplier, supplier_id)
    if not s:
        raise not_found("Supplier")
    if db.scalar(select(m.Supplier).where(func.lower(m.Supplier.name) == body.name.lower(), m.Supplier.id != s.id)):
        raise conflict("Another supplier has this name")
    changes = apply_changes(s, body.model_dump())
    audit(db, user, "update", "supplier", s.id, changes=changes, request=request)
    db.commit()
    return supplier_out(s)


@router.post("/suppliers/{supplier_id}/archive")
def archive_supplier(supplier_id: int, request: Request, archived: bool = True, db: Session = Depends(get_db), user: m.User = Depends(require_roles(*MANAGE_ROLES))):
    s = db.get(m.Supplier, supplier_id)
    if not s:
        raise not_found("Supplier")
    s.archived_at = dt.datetime.now(dt.timezone.utc) if archived else None
    audit(db, user, "archive" if archived else "unarchive", "supplier", s.id, request=request)
    db.commit()
    return supplier_out(s)


# ---------------------------------------------------------------- BOM items
def bom_out(b: m.BOMItem, finance: bool) -> dict:
    d = snapshot(b, ["id", "project_id", "item_name", "description", "specification", "quantity", "unit", "estimated_rate",
                     "actual_rate", "supplier_id", "required_date", "procurement_status", "received_quantity", "remarks", "created_at"])
    d["supplier_name"] = b.supplier.name if b.supplier else None
    d["is_late"] = bool(b.required_date and b.required_date < dt.date.today() and b.procurement_status not in ("received", "cancelled"))
    if finance:
        d["estimated_total"] = str(q2(Decimal(b.quantity) * (b.estimated_rate or 0)))
    else:
        d["estimated_rate"] = d["actual_rate"] = None
    return d


def _check_supplier(db: Session, supplier_id: int | None):
    if supplier_id is not None:
        s = db.get(m.Supplier, supplier_id)
        if not s or s.archived_at:
            raise bad_request("Selected supplier does not exist or is archived")


@router.get("/bom-items")
def list_bom(project_id: int | None = None, status: str | None = None, supplier_id: int | None = None, q: str | None = None,
             late: bool | None = None, page: int = 1, page_size: int = 100,
             db: Session = Depends(get_db), user: m.User = Depends(get_current_user)):
    stmt = select(m.BOMItem).where(m.BOMItem.deleted_at.is_(None), m.BOMItem.project_id.in_(visible_project_ids_subquery(user)))
    if project_id:
        stmt = stmt.where(m.BOMItem.project_id == project_id)
    if status:
        stmt = stmt.where(m.BOMItem.procurement_status.in_(status.split(",")))
    if supplier_id:
        stmt = stmt.where(m.BOMItem.supplier_id == supplier_id)
    if late:
        stmt = stmt.where(m.BOMItem.required_date < dt.date.today(), m.BOMItem.procurement_status.not_in(["received", "cancelled"]))
    if q:
        stmt = stmt.where(or_(m.BOMItem.item_name.ilike(like(q)), m.BOMItem.specification.ilike(like(q)), m.BOMItem.description.ilike(like(q))))
    rows, total = paginate(db, stmt.order_by(m.BOMItem.required_date.asc().nulls_last(), m.BOMItem.id), page, page_size)
    fin = can_view_finance(user)
    return page_response([bom_out(b, fin) for b in rows], total, page, page_size)


@router.post("/bom-items", status_code=201)
def create_bom(body: BOMItemIn, request: Request, db: Session = Depends(get_db), user: m.User = Depends(require_roles(*MANAGE_ROLES))):
    project = get_project_or_404(db, user, body.project_id)
    ensure_project_editable(project)
    _check_supplier(db, body.supplier_id)
    if body.received_quantity > body.quantity:
        raise bad_request("Received quantity cannot exceed the required quantity")
    b = m.BOMItem(**body.model_dump(), created_by_id=user.id, updated_by_id=user.id)
    db.add(b)
    db.flush()
    audit(db, user, "create", "bom_item", b.id, project.id, changes=body.model_dump(mode="json"), request=request)
    db.commit()
    return bom_out(b, True)


@router.patch("/bom-items/{item_id}")
def update_bom(item_id: int, body: BOMItemUpdate, request: Request, db: Session = Depends(get_db), user: m.User = Depends(require_roles(*MANAGE_ROLES))):
    b = db.get(m.BOMItem, item_id)
    if not b or b.deleted_at:
        raise not_found("BOM item")
    project = get_project_or_404(db, user, b.project_id)
    ensure_project_editable(project)
    data = body.model_dump(exclude_unset=True)
    if "supplier_id" in data:
        _check_supplier(db, data["supplier_id"])
    if data.get("quantity") is None:
        data.pop("quantity", None)
    if Decimal(data.get("received_quantity", b.received_quantity) or 0) > Decimal(data.get("quantity", b.quantity)):
        raise bad_request("Received quantity cannot exceed the required quantity")
    changes = apply_changes(b, data)
    b.updated_by_id = user.id
    audit(db, user, "update", "bom_item", b.id, b.project_id, changes=changes, request=request)
    db.commit()
    return bom_out(b, True)


@router.delete("/bom-items/{item_id}")
def delete_bom(item_id: int, request: Request, db: Session = Depends(get_db), user: m.User = Depends(require_roles(*MANAGE_ROLES))):
    b = db.get(m.BOMItem, item_id)
    if not b or b.deleted_at:
        raise not_found("BOM item")
    get_project_or_404(db, user, b.project_id)
    linked = db.scalar(select(func.count()).select_from(m.SupplierPOItem).join(m.SupplierPurchaseOrder)
                       .where(m.SupplierPOItem.bom_item_id == b.id, m.SupplierPurchaseOrder.status != "cancelled"))
    if linked:
        raise conflict("This BOM item is on an active supplier PO. Cancel the PO line first.")
    b.deleted_at = dt.datetime.now(dt.timezone.utc)
    audit(db, user, "delete", "bom_item", b.id, b.project_id, request=request)
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------- supplier POs
def spo_out(po: m.SupplierPurchaseOrder, db: Session | None = None) -> dict:
    d = snapshot(po, ["id", "project_id", "supplier_id", "po_number", "po_date", "delivery_date", "actual_delivery_date",
                      "subtotal", "tax_amount", "total_amount", "currency", "payment_terms", "status", "document_id", "notes", "created_at"])
    d["supplier_name"] = po.supplier.name if po.supplier else None
    d["items"] = [snapshot(i, ["id", "bom_item_id", "description", "quantity", "unit", "unit_price", "tax_rate", "amount",
                               "received_quantity"]) for i in po.items]
    d["is_late"] = bool(po.delivery_date and po.delivery_date < dt.date.today() and po.status not in ("received", "cancelled", "draft"))
    if db is not None:
        paid = db.scalar(select(func.coalesce(func.sum(m.SupplierPayment.amount), 0))
                         .where(m.SupplierPayment.supplier_po_id == po.id, m.SupplierPayment.status != "reversed"))
        d["paid_amount"] = str(q2(paid))
        d["balance_due"] = str(q2(po.total_amount - Decimal(paid)))
    d["missing_document"] = po.document_id is None
    return d


def _sync_bom_from_po(db: Session, po: m.SupplierPurchaseOrder, extra_bom_ids: set | None = None):
    """Keep BOM procurement status / received quantity / actual rate consistent with supplier POs."""
    bom_ids = {i.bom_item_id for i in po.items if i.bom_item_id} | (extra_bom_ids or set())
    for bid in bom_ids:
        b = db.get(m.BOMItem, bid)
        if not b:
            continue
        lines = db.execute(
            select(m.SupplierPOItem, m.SupplierPurchaseOrder)
            .join(m.SupplierPurchaseOrder).where(m.SupplierPOItem.bom_item_id == bid, m.SupplierPurchaseOrder.status != "cancelled")
        ).all()
        if not lines:
            if b.procurement_status in ("ordered", "partially_received"):
                b.procurement_status = "pending"
            continue
        received = sum((Decimal(li.received_quantity) for li, _ in lines), Decimal(0))
        b.received_quantity = min(received, Decimal(b.quantity))
        latest_line, latest_po = lines[-1]
        b.actual_rate = latest_line.unit_price
        b.supplier_id = latest_po.supplier_id
        if b.procurement_status == "cancelled":
            continue
        if received >= b.quantity:
            b.procurement_status = "received"
        elif received > 0:
            b.procurement_status = "partially_received"
        elif any(p.status == "delayed" or (p.delivery_date and p.delivery_date < dt.date.today()) for _, p in lines):
            b.procurement_status = "delayed"
        else:
            b.procurement_status = "ordered"


def _derive_po_status(po: m.SupplierPurchaseOrder):
    if po.status in ("cancelled", "draft"):
        return
    total_q = sum((Decimal(i.quantity) for i in po.items), Decimal(0))
    recv = sum((Decimal(i.received_quantity) for i in po.items), Decimal(0))
    if total_q and recv >= total_q:
        po.status = "received"
        po.actual_delivery_date = po.actual_delivery_date or dt.date.today()
    elif recv > 0:
        po.status = "partially_received"


def _build_items(db: Session, project_id: int, items_in) -> list[m.SupplierPOItem]:
    items = []
    for it in items_in:
        if it.bom_item_id:
            b = db.get(m.BOMItem, it.bom_item_id)
            if not b or b.deleted_at or b.project_id != project_id:
                raise bad_request(f"BOM item #{it.bom_item_id} does not belong to this project")
        if it.received_quantity > it.quantity:
            raise bad_request(f"Received quantity cannot exceed ordered quantity for '{it.description}'")
        items.append(m.SupplierPOItem(**it.model_dump(), amount=0))
    return items


@router.get("/supplier-pos")
def list_spos(project_id: int | None = None, supplier_id: int | None = None, status: str | None = None, late: bool | None = None,
              missing_document: bool | None = None, q: str | None = None, page: int = 1, page_size: int = 50,
              db: Session = Depends(get_db), user: m.User = Depends(require_roles(*FINANCE_ROLES))):
    stmt = select(m.SupplierPurchaseOrder).options(selectinload(m.SupplierPurchaseOrder.items), selectinload(m.SupplierPurchaseOrder.supplier)) \
        .where(m.SupplierPurchaseOrder.project_id.in_(visible_project_ids_subquery(user)))
    if project_id:
        stmt = stmt.where(m.SupplierPurchaseOrder.project_id == project_id)
    if supplier_id:
        stmt = stmt.where(m.SupplierPurchaseOrder.supplier_id == supplier_id)
    if status:
        stmt = stmt.where(m.SupplierPurchaseOrder.status.in_(status.split(",")))
    if late:
        stmt = stmt.where(m.SupplierPurchaseOrder.delivery_date < dt.date.today(),
                          m.SupplierPurchaseOrder.status.not_in(["received", "cancelled", "draft"]))
    if missing_document:
        stmt = stmt.where(m.SupplierPurchaseOrder.document_id.is_(None))
    if q:
        stmt = stmt.join(m.Supplier).where(or_(m.SupplierPurchaseOrder.po_number.ilike(like(q)), m.Supplier.name.ilike(like(q))))
    rows, total = paginate(db, stmt.order_by(m.SupplierPurchaseOrder.id.desc()), page, page_size)
    return page_response([spo_out(p, db) for p in rows], total, page, page_size)


@router.post("/supplier-pos", status_code=201)
def create_spo(body: SupplierPOIn, request: Request, db: Session = Depends(get_db), user: m.User = Depends(require_roles(*FINANCE_ROLES))):
    project = get_project_or_404(db, user, body.project_id)
    ensure_project_editable(project)
    _check_supplier(db, body.supplier_id)
    if db.scalar(select(m.SupplierPurchaseOrder).where(m.SupplierPurchaseOrder.supplier_id == body.supplier_id,
                                                       func.lower(m.SupplierPurchaseOrder.po_number) == body.po_number.lower())):
        raise conflict(f"Supplier PO {body.po_number} already exists for this supplier")
    if body.document_id:
        d = db.get(m.Document, body.document_id)
        if not d or d.project_id != project.id or d.deleted_at:
            raise bad_request("Attached document does not exist or belongs to another project")
    po = m.SupplierPurchaseOrder(**body.model_dump(exclude={"items"}), created_by_id=user.id, updated_by_id=user.id)
    po.items = _build_items(db, project.id, body.items)
    recalc_supplier_po(po)
    _derive_po_status(po)
    db.add(po)
    db.flush()
    if body.document_id:
        doc = db.get(m.Document, body.document_id)
        doc.supplier_po_id = po.id
        doc.supplier_id = po.supplier_id
    _sync_bom_from_po(db, po)
    audit(db, user, "create", "supplier_po", po.id, project.id, changes=body.model_dump(mode="json"), request=request)
    db.commit()
    return spo_out(po, db)


@router.get("/supplier-pos/{po_id}")
def get_spo(po_id: int, db: Session = Depends(get_db), user: m.User = Depends(require_roles(*FINANCE_ROLES))):
    po = db.get(m.SupplierPurchaseOrder, po_id)
    if not po:
        raise not_found("Supplier PO")
    get_project_or_404(db, user, po.project_id)
    pays = db.scalars(select(m.SupplierPayment).where(m.SupplierPayment.supplier_po_id == po.id).order_by(m.SupplierPayment.payment_date.desc())).all()
    docs = db.scalars(select(m.Document).where(m.Document.supplier_po_id == po.id, m.Document.deleted_at.is_(None))).all()
    return {"po": spo_out(po, db), "payments": [snapshot(p) for p in pays],
            "documents": [{"id": d.id, "title": d.title, "category": d.category, "extension": d.extension} for d in docs]}


@router.patch("/supplier-pos/{po_id}")
def update_spo(po_id: int, body: SupplierPOUpdate, request: Request, db: Session = Depends(get_db), user: m.User = Depends(require_roles(*FINANCE_ROLES))):
    po = db.get(m.SupplierPurchaseOrder, po_id)
    if not po:
        raise not_found("Supplier PO")
    project = get_project_or_404(db, user, po.project_id)
    ensure_project_editable(project)
    if po.status == "cancelled":
        raise APIError(409, "A cancelled PO cannot be edited", "locked")
    data = body.model_dump(exclude_unset=True, exclude={"items"})
    if data.get("po_number") and data["po_number"].lower() != po.po_number.lower():
        if db.scalar(select(m.SupplierPurchaseOrder).where(m.SupplierPurchaseOrder.supplier_id == po.supplier_id,
                                                           func.lower(m.SupplierPurchaseOrder.po_number) == data["po_number"].lower())):
            raise conflict("Another PO with this number exists for the supplier")
    changes = apply_changes(po, data)
    if body.items is not None:
        old_bom = {i.bom_item_id for i in po.items if i.bom_item_id}
        po.items.clear()
        db.flush()
        po.items.extend(_build_items(db, po.project_id, body.items))
        changes["items"] = body.model_dump(mode="json")["items"]
        recalc_supplier_po(po)
        paid = db.scalar(select(func.coalesce(func.sum(m.SupplierPayment.amount), 0))
                         .where(m.SupplierPayment.supplier_po_id == po.id, m.SupplierPayment.status != "reversed"))
        if Decimal(paid) > po.total_amount:
            raise bad_request(f"New PO total {po.total_amount} is below the {q2(paid)} already paid to the supplier")
    if po.status not in ("cancelled", "draft", "delayed") or "items" in changes:
        _derive_po_status(po)
    db.flush()
    _sync_bom_from_po(db, po, old_bom if body.items is not None else None)
    po.updated_by_id = user.id
    audit(db, user, "update", "supplier_po", po.id, po.project_id, changes=changes, request=request)
    db.commit()
    return spo_out(po, db)


class ReceiveIn(BaseModel):
    item_id: int
    received_quantity: Decimal = Field(ge=0)


@router.post("/supplier-pos/{po_id}/receive")
def receive_items(po_id: int, lines: list[ReceiveIn], request: Request, db: Session = Depends(get_db),
                  user: m.User = Depends(require_roles(*MANAGE_ROLES))):
    po = db.get(m.SupplierPurchaseOrder, po_id)
    if not po:
        raise not_found("Supplier PO")
    get_project_or_404(db, user, po.project_id)
    if po.status in ("cancelled", "draft"):
        raise APIError(409, f"Cannot receive against a {po.status} PO", "invalid_state")
    by_id = {i.id: i for i in po.items}
    changes = {}
    for ln in lines:
        item = by_id.get(ln.item_id)
        if not item:
            raise bad_request(f"Line #{ln.item_id} is not on this PO")
        if ln.received_quantity > item.quantity:
            raise bad_request(f"Received quantity for '{item.description}' exceeds the ordered quantity")
        changes[item.id] = {"from": str(item.received_quantity), "to": str(ln.received_quantity)}
        item.received_quantity = ln.received_quantity
    _derive_po_status(po)
    db.flush()
    _sync_bom_from_po(db, po)
    audit(db, user, "receive", "supplier_po", po.id, po.project_id, changes=changes, request=request)
    db.commit()
    return spo_out(po, db)


# ---------------------------------------------------------------- supplier payments
@router.get("/supplier-payments")
def list_supplier_payments(project_id: int | None = None, supplier_id: int | None = None, supplier_po_id: int | None = None,
                           page: int = 1, page_size: int = 50, db: Session = Depends(get_db),
                           user: m.User = Depends(require_roles(*FINANCE_ROLES))):
    stmt = select(m.SupplierPayment).where(m.SupplierPayment.project_id.in_(visible_project_ids_subquery(user)))
    if project_id:
        stmt = stmt.where(m.SupplierPayment.project_id == project_id)
    if supplier_id:
        stmt = stmt.where(m.SupplierPayment.supplier_id == supplier_id)
    if supplier_po_id:
        stmt = stmt.where(m.SupplierPayment.supplier_po_id == supplier_po_id)
    rows, total = paginate(db, stmt.order_by(m.SupplierPayment.payment_date.desc(), m.SupplierPayment.id.desc()), page, page_size)
    return page_response([snapshot(r) for r in rows], total, page, page_size)


@router.post("/supplier-payments", status_code=201)
def create_supplier_payment(body: SupplierPaymentIn, request: Request, db: Session = Depends(get_db),
                            user: m.User = Depends(require_roles(*FINANCE_ROLES))):
    po = db.execute(select(m.SupplierPurchaseOrder).where(m.SupplierPurchaseOrder.id == body.supplier_po_id).with_for_update()).scalar_one_or_none()
    if not po:
        raise bad_request("Supplier PO does not exist")
    get_project_or_404(db, user, po.project_id)
    if po.status == "cancelled":
        raise APIError(409, "Cannot pay against a cancelled PO", "invalid_state")
    if body.reference and db.scalar(select(m.SupplierPayment).where(func.lower(m.SupplierPayment.reference) == body.reference.lower())):
        raise APIError(409, f"Supplier payment reference '{body.reference}' already exists", "duplicate_reference")
    paid = db.scalar(select(func.coalesce(func.sum(m.SupplierPayment.amount), 0))
                     .where(m.SupplierPayment.supplier_po_id == po.id, m.SupplierPayment.status != "reversed"))
    if Decimal(paid) + body.amount > po.total_amount:
        raise APIError(409, f"Payment exceeds the PO balance. PO total {po.total_amount}, already paid {q2(paid)}.", "overpayment")
    sp = m.SupplierPayment(**body.model_dump(), supplier_id=po.supplier_id, project_id=po.project_id,
                           created_by_id=user.id, updated_by_id=user.id)
    db.add(sp)
    db.flush()
    audit(db, user, "create", "supplier_payment", sp.id, po.project_id, changes=body.model_dump(mode="json"), request=request)
    db.commit()
    return {"payment": snapshot(sp), "po": spo_out(po, db)}


@router.post("/supplier-payments/{payment_id}/status")
def supplier_payment_status(payment_id: int, body: SupplierPaymentStatusIn, request: Request, db: Session = Depends(get_db),
                            user: m.User = Depends(require_roles(*FINANCE_ROLES))):
    sp = db.get(m.SupplierPayment, payment_id)
    if not sp:
        raise not_found("Supplier payment")
    get_project_or_404(db, user, sp.project_id)
    allowed = {"recorded": {"verified", "reversed"}, "verified": {"reversed"}, "reversed": set()}
    if body.status not in allowed[sp.status]:
        raise APIError(409, f"Cannot change a {sp.status} supplier payment to {body.status}", "invalid_transition")
    old = sp.status
    sp.status = body.status
    audit(db, user, f"status_{body.status}", "supplier_payment", sp.id, sp.project_id,
          changes={"status": {"from": old, "to": body.status}}, request=request)
    db.commit()
    return snapshot(sp)


# ---------------------------------------------------------------- summaries
@router.get("/projects/{project_id}/procurement")
def project_procurement(project_id: int, db: Session = Depends(get_db), user: m.User = Depends(require_roles(*FINANCE_ROLES))):
    get_project_or_404(db, user, project_id)
    return procurement_summary(db, project_id)


@router.get("/procurement/summary")
def company_procurement(db: Session = Depends(get_db), user: m.User = Depends(require_roles(*FINANCE_ROLES))):
    projects = db.scalars(select(m.Project).where(m.Project.id.in_(visible_project_ids_subquery(user)), m.Project.archived_at.is_(None))
                          .order_by(m.Project.code)).all()
    out = []
    for p in projects:
        s = procurement_summary(db, p.id)
        if s["bom_item_count"] or s["supplier_po_count"]:
            out.append({"project_id": p.id, "code": p.code, "name": p.name, "currency": p.currency, **s})
    return {"projects": out, "note": "Supplier-side costs only. Never combined with client receivables."}
