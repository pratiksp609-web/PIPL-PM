"""Password hashing, session cookies, CSRF protection, rate limiting and auth dependencies."""
from __future__ import annotations

import datetime as dt
import hmac
import secrets
import threading
import time
from collections import defaultdict, deque

import bcrypt
import jwt
from fastapi import Depends, Request, Response
from sqlalchemy.orm import Session

from . import models as m
from .config import get_settings
from .core import APIError
from .db import get_db

settings = get_settings()
SESSION_COOKIE = "pipl_session"
CSRF_COOKIE = "pipl_csrf"
CSRF_HEADER = "x-csrf-token"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode())
    except ValueError:
        return False


def validate_password_strength(password: str) -> None:
    if len(password) < 8 or not any(c.isdigit() for c in password) or not any(c.isalpha() for c in password):
        raise APIError(422, "Password must be at least 8 characters and contain letters and numbers", "weak_password")


def create_session(db: Session, user: m.User, request: Request, response: Response) -> m.UserSession:
    jti = secrets.token_urlsafe(32)
    expires = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=settings.session_hours)
    session = m.UserSession(
        id=jti,
        user_id=user.id,
        expires_at=expires,
        ip_address=request.client.host if request.client else None,
        user_agent=(request.headers.get("user-agent") or "")[:255],
    )
    db.add(session)
    token = jwt.encode({"sub": str(user.id), "jti": jti, "exp": expires}, settings.secret_key, algorithm="HS256")
    max_age = settings.session_hours * 3600
    response.set_cookie(
        SESSION_COOKIE, token, max_age=max_age, httponly=True, secure=settings.cookie_secure, samesite="lax", path="/"
    )
    response.set_cookie(
        CSRF_COOKIE,
        secrets.token_urlsafe(32),
        max_age=max_age,
        httponly=False,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    return session


def clear_session_cookies(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")


def _decode(token: str) -> dict | None:
    try:
        return jwt.decode(token, settings.secret_key, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None


def get_session_record(request: Request, db: Session) -> m.UserSession | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    payload = _decode(token)
    if not payload:
        return None
    record = db.get(m.UserSession, payload.get("jti"))
    if not record or record.revoked_at or record.expires_at < dt.datetime.now(dt.timezone.utc):
        return None
    if str(record.user_id) != payload.get("sub"):
        return None
    return record


def check_csrf(request: Request) -> None:
    if request.method in SAFE_METHODS:
        return
    cookie = request.cookies.get(CSRF_COOKIE)
    header = request.headers.get(CSRF_HEADER)
    if not cookie or not header or not hmac.compare_digest(cookie, header):
        raise APIError(403, "Missing or invalid CSRF token. Refresh the page and try again.", "csrf_failed")


def get_current_user(request: Request, db: Session = Depends(get_db)) -> m.User:
    record = get_session_record(request, db)
    if not record:
        raise APIError(401, "Authentication required", "unauthenticated")
    user = db.get(m.User, record.user_id)
    if not user or not user.is_active:
        raise APIError(401, "Account is inactive", "unauthenticated")
    check_csrf(request)
    request.state.user_id = user.id
    return user


def require_roles(*roles: str):
    def dep(user: m.User = Depends(get_current_user)) -> m.User:
        if user.role not in roles:
            raise APIError(403, "You do not have permission to perform this action", "forbidden")
        return user

    return dep


# ---------------------------------------------------------------- rate limiting (in-process sliding window)
class RateLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def hit(self, key: str, limit: int, window: float = 60.0) -> bool:
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > window:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            return True

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = RateLimiter()
