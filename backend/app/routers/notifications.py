import datetime as dt

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from .. import models as m
from ..core import not_found, page_response, paginate
from ..db import get_db
from ..security import get_current_user, require_roles

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


def notif_out(n: m.Notification) -> dict:
    return {"id": n.id, "type": n.type, "title": n.title, "message": n.message, "link": n.link, "entity_type": n.entity_type,
            "entity_id": n.entity_id, "read_at": n.read_at, "email_status": n.email_status, "email_error": n.email_error,
            "created_at": n.created_at}


@router.get("")
def list_notifications(unread: bool = False, type: str | None = None, page: int = 1, page_size: int = 30,
                       db: Session = Depends(get_db), user: m.User = Depends(get_current_user)):
    stmt = select(m.Notification).where(m.Notification.user_id == user.id)
    if unread:
        stmt = stmt.where(m.Notification.read_at.is_(None))
    if type:
        stmt = stmt.where(m.Notification.type.in_(type.split(",")))
    rows, total = paginate(db, stmt.order_by(m.Notification.created_at.desc(), m.Notification.id.desc()), page, page_size)
    return page_response([notif_out(n) for n in rows], total, page, page_size)


@router.get("/unread-count")
def unread_count(db: Session = Depends(get_db), user: m.User = Depends(get_current_user)):
    n = db.scalar(select(func.count()).select_from(m.Notification).where(m.Notification.user_id == user.id, m.Notification.read_at.is_(None)))
    return {"count": n}


@router.post("/{notification_id}/read")
def mark_read(notification_id: int, read: bool = True, db: Session = Depends(get_db), user: m.User = Depends(get_current_user)):
    n = db.get(m.Notification, notification_id)
    if not n or n.user_id != user.id:
        raise not_found("Notification")
    n.read_at = dt.datetime.now(dt.timezone.utc) if read else None
    db.commit()
    return notif_out(n)


@router.post("/read-all")
def mark_all_read(db: Session = Depends(get_db), user: m.User = Depends(get_current_user)):
    res = db.execute(update(m.Notification).where(m.Notification.user_id == user.id, m.Notification.read_at.is_(None))
                     .values(read_at=dt.datetime.now(dt.timezone.utc)))
    db.commit()
    return {"updated": res.rowcount}


@router.post("/run-checks")
def run_checks_now(db: Session = Depends(get_db), user: m.User = Depends(require_roles("admin"))):
    """Run the scheduled notification checks immediately (admin)."""
    from ..scheduler import run_all_checks

    return run_all_checks()
