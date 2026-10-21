"""Notification creation (deduplicated), email delivery and configurable notification rules."""
from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from . import models as m
from .config import get_settings

log = logging.getLogger("pipl.notify")
settings = get_settings()

NOTIFICATION_TYPES = {
    "progress_reminder": "Progress report reminders",
    "task_overdue": "Overdue tasks",
    "task_due_soon": "Approaching task deadlines",
    "task_assigned": "Task assignments",
    "project_deadline": "Approaching project deadlines",
    "project_overdue": "Overdue projects",
    "quotation_expiry": "Quotation expiries",
    "payment_overdue": "Overdue client payments",
    "pending_approval": "Pending approvals",
    "supplier_delay": "Delayed supplier deliveries",
    "missing_update": "Missing project updates",
    "event_reminder": "Calendar event reminders",
    "project_change": "Important project changes",
}

DEFAULT_RULES = {
    "deadline_warning_days": 3,
    "quotation_expiry_warning_days": 7,
    "missing_update_days": 3,
    "supplier_delay_grace_days": 0,
    "enabled_rules": [k for k in NOTIFICATION_TYPES],
}


def get_rules(db: Session) -> dict:
    row = db.get(m.SystemSetting, "notification_rules")
    rules = dict(DEFAULT_RULES)
    if row and isinstance(row.value, dict):
        rules.update({k: v for k, v in row.value.items() if k in DEFAULT_RULES})
    return rules


def user_settings(db: Session, user_id: int) -> m.UserSettings:
    s = db.get(m.UserSettings, user_id)
    if not s:
        s = m.UserSettings(user_id=user_id, timezone=settings.default_timezone, disabled_notification_types=[])
        db.add(s)
        db.flush()
    return s


def notify(
    db: Session,
    user_id: int,
    type_: str,
    title: str,
    message: str,
    dedupe_key: str,
    link: str | None = None,
    entity_type: str | None = None,
    entity_id: int | None = None,
    respect_rules: bool = True,
) -> m.Notification | None:
    """Create an in-app notification unless an identical one (same dedupe key) already exists.

    Returns the new notification, or None if it was a duplicate or disabled by preferences/rules.
    """
    if respect_rules and type_ not in get_rules(db)["enabled_rules"]:
        return None
    prefs = user_settings(db, user_id)
    if type_ in (prefs.disabled_notification_types or []):
        return None
    stmt = (
        insert(m.Notification)
        .values(
            user_id=user_id, type=type_, title=title[:255], message=message, link=link,
            entity_type=entity_type, entity_id=entity_id, dedupe_key=dedupe_key[:160],
            email_status="not_requested",
        )
        .on_conflict_do_nothing(constraint="uq_notification_dedupe")
        .returning(m.Notification.id)
    )
    new_id = db.execute(stmt).scalar()
    if new_id is None:
        return None
    notif = db.get(m.Notification, new_id)
    if prefs.notify_email:
        notif.email_status = "pending" if settings.email_enabled else "not_configured"
    return notif


def send_email(to: str, subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["From"] = settings.smtp_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as smtp:
        if settings.smtp_use_tls:
            smtp.starttls(context=ssl.create_default_context())
        if settings.smtp_username:
            smtp.login(settings.smtp_username, settings.smtp_password or "")
        smtp.send_message(msg)


def deliver_pending_emails(db: Session, limit: int = 100) -> dict:
    """Send queued email notifications. Status becomes 'sent' only after the SMTP server accepts the message."""
    if not settings.email_enabled:
        return {"sent": 0, "failed": 0, "skipped": "email not configured"}
    rows = db.scalars(select(m.Notification).where(m.Notification.email_status == "pending").limit(limit)).all()
    sent = failed = 0
    for n in rows:
        user = db.get(m.User, n.user_id)
        if not user or not user.is_active:
            n.email_status = "failed"
            n.email_error = "recipient inactive"
            failed += 1
            continue
        try:
            send_email(user.email, f"[PIPL] {n.title}", f"{n.message}\n\nOpen in PIPL: {n.link or '/'}")
            n.email_status = "sent"
            sent += 1
        except (smtplib.SMTPException, OSError) as exc:
            n.email_status = "failed"
            n.email_error = str(exc)[:255]
            failed += 1
            log.warning("email delivery failed", extra={"notification_id": n.id, "error": str(exc)})
    db.commit()
    return {"sent": sent, "failed": failed}
