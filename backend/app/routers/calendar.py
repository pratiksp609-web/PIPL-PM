import datetime as dt

from fastapi import APIRouter, Depends, Request
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from .. import models as m
from ..core import (
    MANAGE_ROLES, apply_changes, audit, bad_request, can_view_finance, forbidden, get_project_or_404, not_found, snapshot,
    visible_project_ids_subquery,
)
from ..db import get_db
from ..schemas import EventIn, EventUpdate
from ..security import get_current_user

router = APIRouter(prefix="/api/calendar", tags=["calendar"])
YEARS_RANGE = 50
MAX_SPAN_DAYS = 400
CATEGORIES = ("project_deadline", "task_due", "meeting", "quotation_expiry", "payment_due", "supplier_delivery",
              "reminder", "milestone", "other")
FINANCE_CATEGORIES = {"quotation_expiry", "payment_due", "supplier_delivery"}


def _limits() -> tuple[dt.date, dt.date]:
    t = dt.date.today()
    return t.replace(year=t.year - YEARS_RANGE, day=1), t.replace(year=t.year + YEARS_RANGE, day=28)


def _check_range(d: dt.datetime | dt.date):
    lo, hi = _limits()
    dd = d.date() if isinstance(d, dt.datetime) else d
    if dd < lo or dd > hi:
        raise bad_request(f"Dates must be between {lo} and {hi} (±{YEARS_RANGE} years)")


def event_out(e: m.CalendarEvent) -> dict:
    return {
        "id": f"event-{e.id}", "source_id": e.id, "category": e.event_type if e.event_type in CATEGORIES else "other",
        "title": e.title, "description": e.description, "start": e.start_at.isoformat(),
        "end": e.end_at.isoformat() if e.end_at else None, "all_day": e.all_day, "location": e.location,
        "project_id": e.project_id, "client_id": e.client_id, "task_id": e.task_id,
        "remind_minutes_before": e.remind_minutes_before, "editable": True, "entity_type": "event", "entity_id": e.id,
        "link": f"/projects/{e.project_id}" if e.project_id else None,
    }


def _date_item(kind: str, key: str, title: str, date: dt.date, link: str, entity_type: str, entity_id: int,
               project_id: int | None, extra: dict | None = None) -> dict:
    return {"id": f"{kind}-{key}", "category": kind, "title": title, "start": date.isoformat(), "end": None, "all_day": True,
            "project_id": project_id, "editable": False, "entity_type": entity_type, "entity_id": entity_id, "link": link, **(extra or {})}


@router.get("")
def calendar_feed(start: dt.date, end: dt.date, categories: str | None = None, project_id: int | None = None,
                  q: str | None = None, db: Session = Depends(get_db), user: m.User = Depends(get_current_user)):
    _check_range(start)
    _check_range(end)
    if end < start:
        raise bad_request("End date cannot be before start date")
    if (end - start).days > MAX_SPAN_DAYS:
        raise bad_request(f"A calendar request can cover at most {MAX_SPAN_DAYS} days")
    wanted = set(categories.split(",")) if categories else set(CATEGORIES)
    if not can_view_finance(user):
        wanted -= FINANCE_CATEGORIES
    visible = visible_project_ids_subquery(user)
    items: list[dict] = []
    term = (q or "").lower().strip()

    if "project_deadline" in wanted:
        stmt = select(m.Project).where(m.Project.id.in_(visible), m.Project.archived_at.is_(None),
                                       m.Project.expected_completion_date.between(start, end))
        if project_id:
            stmt = stmt.where(m.Project.id == project_id)
        for p in db.scalars(stmt):
            overdue = p.expected_completion_date < dt.date.today() and p.status not in ("completed", "cancelled")
            items.append(_date_item("project_deadline", str(p.id), f"Deadline: {p.code} {p.name}", p.expected_completion_date,
                                    f"/projects/{p.id}", "project", p.id, p.id, {"overdue": overdue, "status": p.status}))
    if "task_due" in wanted:
        stmt = select(m.Task).where(m.Task.deleted_at.is_(None), m.Task.due_date.between(start, end))
        if user.role not in MANAGE_ROLES:
            stmt = stmt.where(or_(m.Task.assignee_id == user.id, m.Task.project_id.in_(visible)))
        if project_id:
            stmt = stmt.where(m.Task.project_id == project_id)
        for t in db.scalars(stmt):
            items.append(_date_item("task_due", str(t.id), f"Task: {t.title}", t.due_date, f"/tasks?task={t.id}", "task", t.id,
                                    t.project_id, {"status": t.status, "overdue": t.due_date < dt.date.today() and t.status != "completed"}))
    if "quotation_expiry" in wanted:
        stmt = select(m.QuotationVersion, m.Quotation).join(m.Quotation).where(
            m.Quotation.project_id.in_(visible), m.QuotationVersion.validity_date.between(start, end),
            m.QuotationVersion.status.in_(["draft", "submitted", "approved"]))
        if project_id:
            stmt = stmt.where(m.Quotation.project_id == project_id)
        for v, qn in db.execute(stmt):
            items.append(_date_item("quotation_expiry", str(v.id), f"Quotation expires: {qn.quotation_number} R{v.revision_number}",
                                    v.validity_date, f"/projects/{qn.project_id}?tab=quotation", "quotation", qn.id, qn.project_id))
    if "payment_due" in wanted:
        stmt = select(m.PaymentReceived).where(m.PaymentReceived.project_id.in_(visible), m.PaymentReceived.status == "pending",
                                               m.PaymentReceived.due_date.between(start, end))
        if project_id:
            stmt = stmt.where(m.PaymentReceived.project_id == project_id)
        for pay in db.scalars(stmt):
            label = pay.milestone_label or pay.payment_type
            items.append(_date_item("payment_due", str(pay.id), f"Payment due: {label} ({pay.amount})", pay.due_date,
                                    f"/projects/{pay.project_id}?tab=payments", "payment", pay.id, pay.project_id,
                                    {"overdue": pay.due_date < dt.date.today()}))
    if "supplier_delivery" in wanted:
        stmt = select(m.SupplierPurchaseOrder).where(m.SupplierPurchaseOrder.project_id.in_(visible),
                                                     m.SupplierPurchaseOrder.delivery_date.between(start, end),
                                                     m.SupplierPurchaseOrder.status != "cancelled")
        if project_id:
            stmt = stmt.where(m.SupplierPurchaseOrder.project_id == project_id)
        for po in db.scalars(stmt):
            items.append(_date_item("supplier_delivery", str(po.id), f"Delivery: {po.po_number} ({po.supplier.name})", po.delivery_date,
                                    f"/projects/{po.project_id}?tab=bom", "supplier_po", po.id, po.project_id,
                                    {"status": po.status, "overdue": po.delivery_date < dt.date.today() and po.status not in ("received",)}))
    manual_types = wanted & {"meeting", "reminder", "milestone", "other"}
    if manual_types:
        lo = dt.datetime.combine(start, dt.time.min, dt.timezone.utc) - dt.timedelta(days=1)
        hi = dt.datetime.combine(end, dt.time.max, dt.timezone.utc) + dt.timedelta(days=1)
        stmt = select(m.CalendarEvent).where(
            m.CalendarEvent.event_type.in_(manual_types),
            m.CalendarEvent.start_at <= hi,
            or_(m.CalendarEvent.end_at >= lo, and_(m.CalendarEvent.end_at.is_(None), m.CalendarEvent.start_at >= lo)),
            or_(m.CalendarEvent.project_id.is_(None), m.CalendarEvent.project_id.in_(visible)),
        )
        if user.role not in MANAGE_ROLES:
            stmt = stmt.where(or_(m.CalendarEvent.project_id.is_not(None), m.CalendarEvent.created_by_id == user.id))
        if project_id:
            stmt = stmt.where(m.CalendarEvent.project_id == project_id)
        for e in db.scalars(stmt):
            out = event_out(e)
            out["editable"] = user.role in MANAGE_ROLES or e.created_by_id == user.id
            items.append(out)
    if term:
        items = [i for i in items if term in i["title"].lower() or term in (i.get("description") or "").lower()]
    items.sort(key=lambda i: i["start"])
    return {"items": items, "range": {"start": start, "end": end}, "limits": dict(zip(("min", "max"), _limits()))}


def _validate_links(db: Session, user: m.User, data: dict):
    if data.get("project_id"):
        get_project_or_404(db, user, data["project_id"])
    if data.get("client_id") and not db.get(m.Client, data["client_id"]):
        raise bad_request("Client does not exist")
    if data.get("task_id") and not db.get(m.Task, data["task_id"]):
        raise bad_request("Task does not exist")


@router.post("/events", status_code=201)
def create_event(body: EventIn, request: Request, db: Session = Depends(get_db), user: m.User = Depends(get_current_user)):
    _check_range(body.start_at)
    if body.end_at:
        _check_range(body.end_at)
    _validate_links(db, user, body.model_dump())
    e = m.CalendarEvent(**body.model_dump(), created_by_id=user.id, updated_by_id=user.id)
    db.add(e)
    db.flush()
    audit(db, user, "create", "calendar_event", e.id, e.project_id, changes=body.model_dump(mode="json"), request=request)
    db.commit()
    return event_out(e)


def _get_editable(db: Session, user: m.User, event_id: int) -> m.CalendarEvent:
    e = db.get(m.CalendarEvent, event_id)
    if not e:
        raise not_found("Event")
    if e.project_id:
        get_project_or_404(db, user, e.project_id)
    if user.role not in MANAGE_ROLES and e.created_by_id != user.id:
        raise forbidden("Only the creator or a manager can change this event")
    return e


@router.get("/events/{event_id}")
def get_event(event_id: int, db: Session = Depends(get_db), user: m.User = Depends(get_current_user)):
    e = db.get(m.CalendarEvent, event_id)
    if not e:
        raise not_found("Event")
    if e.project_id:
        get_project_or_404(db, user, e.project_id)
    elif user.role not in MANAGE_ROLES and e.created_by_id != user.id:
        raise not_found("Event")
    return event_out(e)


@router.patch("/events/{event_id}")
def update_event(event_id: int, body: EventUpdate, request: Request, db: Session = Depends(get_db), user: m.User = Depends(get_current_user)):
    e = _get_editable(db, user, event_id)
    data = body.model_dump(exclude_unset=True)
    for k in ("start_at", "end_at"):
        if data.get(k):
            if data[k].tzinfo is None:
                raise bad_request("Datetimes must include a timezone offset")
            _check_range(data[k])
    if "title" in data and not data["title"]:
        raise bad_request("Title cannot be empty")
    if data.get("start_at") is None:
        data.pop("start_at", None)
    start = data.get("start_at", e.start_at)
    end = data.get("end_at", e.end_at)
    if end and end < start:
        raise bad_request("End time cannot be before the start time")
    _validate_links(db, user, data)
    if "start_at" in data or "remind_minutes_before" in data:
        e.reminder_sent_at = None
    changes = apply_changes(e, data)
    e.updated_by_id = user.id
    audit(db, user, "update", "calendar_event", e.id, e.project_id, changes=changes, request=request)
    db.commit()
    return event_out(e)


@router.delete("/events/{event_id}")
def delete_event(event_id: int, request: Request, db: Session = Depends(get_db), user: m.User = Depends(get_current_user)):
    e = _get_editable(db, user, event_id)
    audit(db, user, "delete", "calendar_event", e.id, e.project_id, changes=snapshot(e), request=request)
    db.delete(e)
    db.commit()
    return {"ok": True}
