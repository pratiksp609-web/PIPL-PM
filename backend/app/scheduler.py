"""Background scheduler for reminders and rule-based notifications.

Runs inside the API process with APScheduler. A PostgreSQL advisory lock guarantees only one process executes
the checks at a time, so running several API workers does not duplicate work; notification dedupe keys guarantee
the same alert is never created twice.
"""
from __future__ import annotations

import datetime as dt
import logging
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from . import models as m
from .config import get_settings
from .db import SessionLocal, engine
from .notify import deliver_pending_emails, get_rules, notify, user_settings

log = logging.getLogger("pipl.scheduler")
settings = get_settings()
LOCK_ID = 7_310_001


def reminder_slot(s: m.UserSettings, now_utc: dt.datetime) -> str | None:
    """Return the dedupe slot key if a progress reminder is due now for these settings, else None."""
    if not s.reminders_enabled:
        return None
    try:
        tz = ZoneInfo(s.timezone or settings.default_timezone)
    except Exception:
        tz = ZoneInfo(settings.default_timezone)
    local = now_utc.astimezone(tz)
    days = {int(x) for x in (s.work_days or "").split(",") if x.strip() != ""}
    if local.weekday() not in days:
        return None
    t = local.time().replace(tzinfo=None)
    if not (s.work_start <= t < s.work_end):
        return None
    minutes_in = (local.hour * 60 + local.minute) - (s.work_start.hour * 60 + s.work_start.minute)
    slot = minutes_in // s.reminder_interval_minutes
    if slot == 0:
        return None  # first reminder comes one interval after the working day starts
    if s.last_progress_reminder_at and now_utc - s.last_progress_reminder_at < dt.timedelta(minutes=s.reminder_interval_minutes - 1):
        return None
    return f"progress:{local.date().isoformat()}:{s.reminder_interval_minutes}:{slot}"


def progress_reminders(db: Session, now: dt.datetime) -> int:
    sent = 0
    users = db.scalars(select(m.User).where(m.User.is_active.is_(True))).all()
    for u in users:
        s = user_settings(db, u.id)
        slot = reminder_slot(s, now)
        if not slot:
            continue
        open_tasks = db.scalars(select(m.Task).where(m.Task.assignee_id == u.id, m.Task.deleted_at.is_(None),
                                                     m.Task.status != "completed").order_by(m.Task.due_date.asc().nulls_last()).limit(6)).all()
        if not open_tasks:
            continue  # respect completion: nothing open, nothing to report
        names = "; ".join(t.title for t in open_tasks[:5])
        n = notify(db, u.id, "progress_reminder", "Progress report reminder",
                   f"Please update progress on your open tasks: {names}", dedupe_key=slot, link="/tasks?mine=1")
        s.last_progress_reminder_at = now
        if n:
            sent += 1
    return sent


def _project_recipients(db: Session, p: m.Project) -> set[int]:
    if p.manager_id:
        return {p.manager_id}
    return set(db.scalars(select(m.User.id).where(m.User.role == "admin", m.User.is_active.is_(True))).all())


def deadline_checks(db: Session, today: dt.date, rules: dict) -> int:
    count = 0
    warn = today + dt.timedelta(days=rules["deadline_warning_days"])
    tasks = db.scalars(select(m.Task).where(m.Task.deleted_at.is_(None), m.Task.status != "completed",
                                            m.Task.due_date.is_not(None), m.Task.due_date <= warn, m.Task.assignee_id.is_not(None))).all()
    for t in tasks:
        if t.due_date < today:
            key = f"task_overdue:{t.id}:{today.isoformat()}"
            count += bool(notify(db, t.assignee_id, "task_overdue", "Task overdue",
                                 f"'{t.title}' was due on {t.due_date:%d %b %Y}.", key, f"/tasks?task={t.id}", "task", t.id))
        else:
            key = f"task_due_soon:{t.id}:{t.due_date.isoformat()}"
            count += bool(notify(db, t.assignee_id, "task_due_soon", "Task due soon",
                                 f"'{t.title}' is due on {t.due_date:%d %b %Y}.", key, f"/tasks?task={t.id}", "task", t.id))
    projects = db.scalars(select(m.Project).where(m.Project.archived_at.is_(None), m.Project.status.not_in(["completed", "cancelled"]),
                                                  m.Project.expected_completion_date.is_not(None), m.Project.expected_completion_date <= warn)).all()
    for p in projects:
        for uid in _project_recipients(db, p):
            if p.expected_completion_date < today:
                key = f"project_overdue:{p.id}:{today.isoformat()}"
                count += bool(notify(db, uid, "project_overdue", f"{p.code} is overdue",
                                     f"{p.name} passed its expected completion date ({p.expected_completion_date:%d %b %Y}) at {p.progress}% progress.",
                                     key, f"/projects/{p.id}", "project", p.id))
            else:
                key = f"project_deadline:{p.id}:{p.expected_completion_date.isoformat()}"
                count += bool(notify(db, uid, "project_deadline", f"{p.code} deadline approaching",
                                     f"{p.name} is due on {p.expected_completion_date:%d %b %Y} ({p.progress}% complete).",
                                     key, f"/projects/{p.id}", "project", p.id))
    return count


def quotation_checks(db: Session, today: dt.date, rules: dict) -> int:
    count = 0
    expiring = db.execute(select(m.QuotationVersion, m.Quotation).join(m.Quotation).where(
        m.QuotationVersion.status.in_(["draft", "submitted"]), m.QuotationVersion.validity_date.is_not(None),
        m.QuotationVersion.validity_date <= today + dt.timedelta(days=rules["quotation_expiry_warning_days"]))).all()
    for v, q in expiring:
        p = db.get(m.Project, q.project_id)
        if v.validity_date < today:
            v.status = "expired"
            db.add(m.AuditLog(action="auto_expired", entity_type="quotation_version", entity_id=v.id, project_id=q.project_id,
                              changes={"validity_date": v.validity_date.isoformat()}))
            msg, key = f"Quotation {q.quotation_number} R{v.revision_number} expired on {v.validity_date:%d %b %Y}.", f"quote_expired:{v.id}"
        else:
            msg, key = (f"Quotation {q.quotation_number} R{v.revision_number} expires on {v.validity_date:%d %b %Y}.",
                        f"quote_expiring:{v.id}:{v.validity_date.isoformat()}")
        for uid in _project_recipients(db, p):
            count += bool(notify(db, uid, "quotation_expiry", "Quotation expiry", msg, key, f"/projects/{p.id}?tab=quotation", "quotation", q.id))
    return count


def payment_checks(db: Session, today: dt.date) -> int:
    count = 0
    overdue = db.scalars(select(m.PaymentReceived).where(m.PaymentReceived.status == "pending", m.PaymentReceived.due_date < today)).all()
    for pay in overdue:
        p = db.get(m.Project, pay.project_id)
        for uid in _project_recipients(db, p):
            count += bool(notify(db, uid, "payment_overdue", f"Client payment overdue · {p.code}",
                                 f"{pay.milestone_label or pay.payment_type.capitalize()} payment of {pay.amount} {p.currency} was due "
                                 f"{pay.due_date:%d %b %Y}.", f"payment_overdue:{pay.id}:{today.isoformat()}",
                                 f"/projects/{p.id}?tab=payments", "payment", pay.id))
    return count


def approval_checks(db: Session, today: dt.date) -> int:
    count = 0
    pending_q = db.execute(select(m.QuotationVersion, m.Quotation).join(m.Quotation).where(m.QuotationVersion.status == "submitted")).all()
    for v, q in pending_q:
        p = db.get(m.Project, q.project_id)
        for uid in _project_recipients(db, p):
            count += bool(notify(db, uid, "pending_approval", "Quotation awaiting approval",
                                 f"{q.quotation_number} R{v.revision_number} for {p.code} is submitted and awaiting a decision.",
                                 f"approval_q:{v.id}:{today.isoformat()}", f"/projects/{p.id}?tab=quotation", "quotation", q.id))
    pending_po = db.scalars(select(m.ClientPurchaseOrder).where(m.ClientPurchaseOrder.status.in_(["received", "under_review"]))).all()
    for po in pending_po:
        p = db.get(m.Project, po.project_id)
        for uid in _project_recipients(db, p):
            count += bool(notify(db, uid, "pending_approval", "Client PO awaiting verification",
                                 f"Client PO {po.po_number} for {p.code} needs review against the approved quotation.",
                                 f"approval_po:{po.id}:{today.isoformat()}", f"/projects/{p.id}?tab=client-po", "client_po", po.id))
    return count


def supplier_checks(db: Session, today: dt.date, rules: dict) -> int:
    count = 0
    cutoff = today - dt.timedelta(days=rules["supplier_delay_grace_days"])
    late = db.scalars(select(m.SupplierPurchaseOrder).where(
        m.SupplierPurchaseOrder.status.in_(["ordered", "partially_received", "delayed"]),
        m.SupplierPurchaseOrder.delivery_date < cutoff)).all()
    for po in late:
        p = db.get(m.Project, po.project_id)
        for uid in _project_recipients(db, p):
            count += bool(notify(db, uid, "supplier_delay", f"Supplier delivery late · {p.code}",
                                 f"{po.supplier.name} PO {po.po_number} was due {po.delivery_date:%d %b %Y} ({(today - po.delivery_date).days} days late).",
                                 f"supplier_delay:{po.id}:{today.isoformat()}", f"/projects/{p.id}?tab=bom", "supplier_po", po.id))
    return count


def missing_update_checks(db: Session, now: dt.datetime, rules: dict) -> int:
    count = 0
    threshold = now - dt.timedelta(days=rules["missing_update_days"])
    projects = db.scalars(select(m.Project).where(m.Project.status == "active", m.Project.archived_at.is_(None))).all()
    for p in projects:
        last = db.scalar(select(m.ProjectUpdate.update_at).where(m.ProjectUpdate.project_id == p.id).order_by(m.ProjectUpdate.update_at.desc()).limit(1))
        if last and last >= threshold:
            continue
        since = f"since {last:%d %b %Y}" if last else "yet"
        for uid in _project_recipients(db, p):
            count += bool(notify(db, uid, "missing_update", f"Missing project update · {p.code}",
                                 f"No progress update has been submitted for {p.name} {since}.",
                                 f"missing_update:{p.id}:{now.date().isoformat()}", f"/updates?project={p.id}", "project", p.id))
    return count


def event_reminders(db: Session, now: dt.datetime) -> int:
    count = 0
    events = db.scalars(select(m.CalendarEvent).where(m.CalendarEvent.remind_minutes_before.is_not(None),
                                                      m.CalendarEvent.reminder_sent_at.is_(None),
                                                      m.CalendarEvent.start_at > now - dt.timedelta(hours=1),
                                                      m.CalendarEvent.start_at <= now + dt.timedelta(days=30))).all()
    for e in events:
        if e.start_at - dt.timedelta(minutes=e.remind_minutes_before) > now:
            continue
        recipients = {e.created_by_id} if e.created_by_id else set()
        if e.project_id:
            p = db.get(m.Project, e.project_id)
            recipients |= _project_recipients(db, p) | {mem.user_id for mem in p.members}
        for uid in recipients:
            count += bool(notify(db, uid, "event_reminder", f"Upcoming: {e.title}",
                                 f"{e.title} starts {e.start_at:%d %b %Y %H:%M} UTC" + (f" at {e.location}" if e.location else "") + ".",
                                 f"event:{e.id}:{e.start_at.isoformat()}", "/calendar", "event", e.id))
        e.reminder_sent_at = now
    return count


def run_all_checks(now: dt.datetime | None = None) -> dict:
    now = now or dt.datetime.now(dt.timezone.utc)
    with engine.connect() as lock_conn:  # dedicated connection holds the session-level advisory lock
        if not lock_conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": LOCK_ID}).scalar():
            return {"skipped": "another process is running checks"}
        try:
            return _run_checks(now)
        finally:
            lock_conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": LOCK_ID})
            lock_conn.commit()


def _run_checks(now: dt.datetime) -> dict:
    today = now.date()
    db = SessionLocal()
    try:
        run = m.JobRun(job_name="notification_checks")
        db.add(run)
        db.commit()
        rules = get_rules(db)
        results = {}
        for name, fn in (
            ("progress_reminders", lambda: progress_reminders(db, now)),
            ("deadlines", lambda: deadline_checks(db, today, rules)),
            ("quotations", lambda: quotation_checks(db, today, rules)),
            ("payments", lambda: payment_checks(db, today)),
            ("approvals", lambda: approval_checks(db, today)),
            ("supplier_delays", lambda: supplier_checks(db, today, rules)),
            ("missing_updates", lambda: missing_update_checks(db, now, rules)),
            ("event_reminders", lambda: event_reminders(db, now)),
        ):
            try:
                results[name] = fn()
                db.commit()
            except Exception as exc:  # one failing check must not stop the others
                db.rollback()
                results[name] = f"error: {exc}"
                log.exception("scheduled check failed", extra={"check": name})
        results["email"] = deliver_pending_emails(db)
        failed = any(isinstance(v, str) and v.startswith("error") for v in results.values())
        run.status = "partial" if failed else "success"
        run.finished_at = dt.datetime.now(dt.timezone.utc)
        run.details = results
        db.commit()
        log.info("scheduled checks finished", extra={"results": results})
        return results
    finally:
        db.close()


def start_scheduler() -> BackgroundScheduler:
    sched = BackgroundScheduler(timezone="UTC", job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 300})
    sched.add_job(run_all_checks, "interval", minutes=settings.scheduler_interval_minutes, id="notification_checks",
                  next_run_time=dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=20))
    sched.start()
    log.info("scheduler started", extra={"interval_minutes": settings.scheduler_interval_minutes})
    return sched
