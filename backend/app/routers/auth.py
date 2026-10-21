import datetime as dt

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .. import models as m
from ..config import get_settings
from ..core import APIError, audit
from ..db import get_db
from ..schemas import LoginIn, PasswordChange, UserOut
from ..security import (
    clear_session_cookies,
    create_session,
    get_current_user,
    get_session_record,
    hash_password,
    limiter,
    validate_password_strength,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])
settings = get_settings()
MAX_FAILED = 5
LOCK_MINUTES = 15


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    ip = request.client.host if request.client else "unknown"
    if not limiter.hit(f"login:{ip}", settings.login_rate_limit_per_minute):
        raise APIError(429, "Too many login attempts. Please wait a minute and try again.", "rate_limited")
    ident = body.identifier.lower()
    user = db.scalar(select(m.User).where(or_(func.lower(m.User.email) == ident, func.lower(m.User.username) == ident)))
    now = dt.datetime.now(dt.timezone.utc)
    if user and user.locked_until and user.locked_until > now:
        raise APIError(423, "Account temporarily locked after repeated failed logins. Try again later.", "locked")
    if not user or not verify_password(body.password, user.password_hash):
        if user:
            user.failed_login_count += 1
            if user.failed_login_count >= MAX_FAILED:
                user.locked_until = now + dt.timedelta(minutes=LOCK_MINUTES)
                user.failed_login_count = 0
            audit(db, user, "login_failed", "user", user.id, request=request)
            db.commit()
        raise APIError(401, "Invalid email/username or password", "invalid_credentials")
    if not user.is_active:
        raise APIError(403, "This account has been deactivated", "inactive")
    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = now
    create_session(db, user, request, response)
    audit(db, user, "login", "user", user.id, request=request)
    db.commit()
    return {"user": UserOut.model_validate(user)}


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db), user: m.User = Depends(get_current_user)):
    record = get_session_record(request, db)
    if record:
        record.revoked_at = dt.datetime.now(dt.timezone.utc)
    audit(db, user, "logout", "user", user.id, request=request)
    db.commit()
    clear_session_cookies(response)
    return {"ok": True}


@router.get("/me")
def me(user: m.User = Depends(get_current_user)):
    return {
        "user": UserOut.model_validate(user),
        "permissions": {
            "finance": user.role in ("admin", "project_manager"),
            "manage_projects": user.role in ("admin", "project_manager"),
            "admin": user.role == "admin",
        },
        "integrations": {"ai": settings.ai_enabled, "email": settings.email_enabled},
    }


@router.post("/change-password")
def change_password(body: PasswordChange, request: Request, db: Session = Depends(get_db), user: m.User = Depends(get_current_user)):
    if not verify_password(body.current_password, user.password_hash):
        raise APIError(422, "Current password is incorrect", "invalid_password")
    validate_password_strength(body.new_password)
    user.password_hash = hash_password(body.new_password)
    # revoke every other session for this user
    current = get_session_record(request, db)
    now = dt.datetime.now(dt.timezone.utc)
    for s in db.scalars(select(m.UserSession).where(m.UserSession.user_id == user.id, m.UserSession.revoked_at.is_(None))):
        if not current or s.id != current.id:
            s.revoked_at = now
    audit(db, user, "password_changed", "user", user.id, request=request)
    db.commit()
    return {"ok": True}
