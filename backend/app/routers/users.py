import datetime as dt

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .. import models as m
from ..config import get_settings
from ..core import APIError, apply_changes, audit, conflict, not_found
from ..db import get_db
from ..notify import NOTIFICATION_TYPES, get_rules, user_settings
from ..schemas import SystemRulesIn, UserCreate, UserOut, UserSettingsIn, UserUpdate
from ..security import get_current_user, hash_password, require_roles, validate_password_strength

router = APIRouter(prefix="/api", tags=["users"])
settings = get_settings()


@router.get("/users")
def list_users(db: Session = Depends(get_db), user: m.User = Depends(get_current_user), include_inactive: bool = False):
    stmt = select(m.User).order_by(m.User.full_name)
    if not include_inactive or user.role != "admin":
        stmt = stmt.where(m.User.is_active.is_(True))
    users = db.scalars(stmt).all()
    if user.role != "admin":  # non-admins only need names for assignment pickers
        return {"items": [{"id": u.id, "full_name": u.full_name, "role": u.role, "username": u.username} for u in users]}
    return {"items": [UserOut.model_validate(u) for u in users]}


@router.post("/users", status_code=201)
def create_user(body: UserCreate, request: Request, db: Session = Depends(get_db), admin: m.User = Depends(require_roles("admin"))):
    validate_password_strength(body.password)
    exists = db.scalar(
        select(m.User).where(or_(func.lower(m.User.email) == body.email.lower(), func.lower(m.User.username) == body.username.lower()))
    )
    if exists:
        raise conflict("A user with this email or username already exists")
    u = m.User(email=body.email.lower(), username=body.username, full_name=body.full_name, role=body.role,
               password_hash=hash_password(body.password))
    db.add(u)
    db.flush()
    audit(db, admin, "create", "user", u.id, changes={"email": u.email, "role": u.role}, request=request)
    db.commit()
    return UserOut.model_validate(u)


@router.patch("/users/{user_id}")
def update_user(user_id: int, body: UserUpdate, request: Request, db: Session = Depends(get_db), admin: m.User = Depends(require_roles("admin"))):
    u = db.get(m.User, user_id)
    if not u:
        raise not_found("User")
    data = body.model_dump(exclude_unset=True)
    if u.id == admin.id and (data.get("role") not in (None, "admin") or data.get("is_active") is False):
        raise APIError(422, "You cannot remove your own admin role or deactivate yourself", "self_lockout")
    password = data.pop("password", None)
    changes = apply_changes(u, data)
    if password:
        validate_password_strength(password)
        u.password_hash = hash_password(password)
        changes["password"] = "reset"
    if data.get("is_active") is False or password:
        now = dt.datetime.now(dt.timezone.utc)
        for s in db.scalars(select(m.UserSession).where(m.UserSession.user_id == u.id, m.UserSession.revoked_at.is_(None))):
            s.revoked_at = now
    audit(db, admin, "update", "user", u.id, changes=changes, request=request)
    db.commit()
    return UserOut.model_validate(u)


def _settings_out(s: m.UserSettings) -> dict:
    return {
        "reminders_enabled": s.reminders_enabled,
        "reminder_interval_minutes": s.reminder_interval_minutes,
        "work_start": s.work_start.strftime("%H:%M"),
        "work_end": s.work_end.strftime("%H:%M"),
        "work_days": [int(x) for x in s.work_days.split(",") if x != ""],
        "timezone": s.timezone,
        "notify_email": s.notify_email,
        "disabled_notification_types": s.disabled_notification_types or [],
        "last_progress_reminder_at": s.last_progress_reminder_at,
        "notification_types": NOTIFICATION_TYPES,
        "email_configured": settings.email_enabled,
    }


@router.get("/settings/me")
def get_my_settings(db: Session = Depends(get_db), user: m.User = Depends(get_current_user)):
    s = user_settings(db, user.id)
    db.commit()
    return _settings_out(s)


@router.put("/settings/me")
def update_my_settings(body: UserSettingsIn, request: Request, db: Session = Depends(get_db), user: m.User = Depends(get_current_user)):
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    s = user_settings(db, user.id)
    data = body.model_dump(exclude_unset=True)
    if "timezone" in data and data["timezone"]:
        try:
            ZoneInfo(data["timezone"])
        except (ZoneInfoNotFoundError, ValueError):
            raise APIError(422, f"Unknown timezone '{data['timezone']}'", "validation_error")
    if "work_days" in data and data["work_days"] is not None:
        if not data["work_days"]:
            raise APIError(422, "Select at least one working day", "validation_error")
        data["work_days"] = ",".join(str(d) for d in sorted(set(data["work_days"])))
    if "disabled_notification_types" in data and data["disabled_notification_types"] is not None:
        unknown = set(data["disabled_notification_types"]) - set(NOTIFICATION_TYPES)
        if unknown:
            raise APIError(422, f"Unknown notification types: {', '.join(sorted(unknown))}", "validation_error")
    start = data.get("work_start", s.work_start)
    end = data.get("work_end", s.work_end)
    if start >= end:
        raise APIError(422, "Working hours must end after they start", "validation_error")
    changes = apply_changes(s, data)
    audit(db, user, "update", "user_settings", user.id, changes=changes, request=request)
    db.commit()
    return _settings_out(s)


@router.get("/settings/system")
def get_system(db: Session = Depends(get_db), user: m.User = Depends(get_current_user)):
    last_runs = db.execute(
        select(m.JobRun.job_name, func.max(m.JobRun.finished_at)).group_by(m.JobRun.job_name)
    ).all()
    return {
        "rules": get_rules(db),
        "notification_types": NOTIFICATION_TYPES,
        "integrations": {
            "ai": {"configured": settings.ai_enabled, "model": settings.ai_model if settings.ai_enabled else None},
            "email": {"configured": settings.email_enabled},
            "scheduler": {"enabled": settings.scheduler_enabled, "interval_minutes": settings.scheduler_interval_minutes,
                          "last_runs": {r[0]: r[1] for r in last_runs}},
            "ocr": {"configured": _ocr()},
        },
        "upload_limit_mb": settings.max_upload_mb,
        "environment": settings.app_env,
    }


def _ocr() -> bool:
    from ..storage import _ocr_available

    return _ocr_available()


@router.put("/settings/system/rules")
def update_rules(body: SystemRulesIn, request: Request, db: Session = Depends(get_db), admin: m.User = Depends(require_roles("admin"))):
    current = get_rules(db)
    data = body.model_dump(exclude_unset=True)
    if "enabled_rules" in data and data["enabled_rules"] is not None:
        unknown = set(data["enabled_rules"]) - set(NOTIFICATION_TYPES)
        if unknown:
            raise APIError(422, f"Unknown rules: {', '.join(sorted(unknown))}", "validation_error")
    new = {**current, **{k: v for k, v in data.items() if v is not None}}
    row = db.get(m.SystemSetting, "notification_rules")
    if row:
        row.value = new
        row.updated_by_id = admin.id
    else:
        db.add(m.SystemSetting(key="notification_rules", value=new, updated_by_id=admin.id))
    audit(db, admin, "update", "system_settings", None, changes={"notification_rules": new}, request=request)
    db.commit()
    return {"rules": new}


@router.get("/audit-logs")
def audit_logs(
    entity_type: str | None = None, entity_id: int | None = None, project_id: int | None = None,
    page: int = 1, page_size: int = 50,
    db: Session = Depends(get_db), user: m.User = Depends(require_roles("admin", "project_manager")),
):
    stmt = select(m.AuditLog).order_by(m.AuditLog.created_at.desc(), m.AuditLog.id.desc())
    if entity_type:
        stmt = stmt.where(m.AuditLog.entity_type == entity_type)
    if entity_id:
        stmt = stmt.where(m.AuditLog.entity_id == entity_id)
    if project_id:
        stmt = stmt.where(m.AuditLog.project_id == project_id)
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    page_size = min(max(page_size, 1), 200)
    rows = db.scalars(stmt.limit(page_size).offset((max(page, 1) - 1) * page_size)).all()
    return {
        "items": [
            {"id": r.id, "action": r.action, "entity_type": r.entity_type, "entity_id": r.entity_id,
             "project_id": r.project_id, "changes": r.changes, "user": r.user.full_name if r.user else None,
             "created_at": r.created_at}
            for r in rows
        ],
        "total": total, "page": page, "page_size": page_size,
    }
