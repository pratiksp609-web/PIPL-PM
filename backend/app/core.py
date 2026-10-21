"""Shared helpers: errors, pagination, audit logging, role checks and project visibility."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, Request
from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from . import models as m

ROLES = ("admin", "project_manager", "team_member")
FINANCE_ROLES = ("admin", "project_manager")
MANAGE_ROLES = ("admin", "project_manager")


class APIError(HTTPException):
    def __init__(self, status_code: int, message: str, code: str = "error", details: Any = None):
        super().__init__(status_code=status_code, detail=message)
        self.code = code
        self.message = message
        self.details = details


def not_found(entity: str) -> APIError:
    return APIError(404, f"{entity} not found", "not_found")


def forbidden(message: str = "You do not have permission to perform this action") -> APIError:
    return APIError(403, message, "forbidden")


def conflict(message: str, details: Any = None) -> APIError:
    return APIError(409, message, "conflict", details)


def bad_request(message: str, details: Any = None) -> APIError:
    return APIError(422, message, "validation_error", details)


def require_role(user: m.User, *roles: str) -> None:
    if user.role not in roles:
        raise forbidden()


def can_view_finance(user: m.User) -> bool:
    return user.role in FINANCE_ROLES


# ---------------------------------------------------------------- pagination
def paginate(db: Session, stmt: Select, page: int, page_size: int) -> tuple[list, int]:
    page = max(page, 1)
    page_size = min(max(page_size, 1), 200)
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = db.execute(stmt.limit(page_size).offset((page - 1) * page_size)).unique().scalars().all()
    return list(rows), total


def page_response(items: list, total: int, page: int, page_size: int) -> dict:
    return {"items": items, "total": total, "page": page, "page_size": min(max(page_size, 1), 200)}


# ---------------------------------------------------------------- visibility
def visible_project_filter(user: m.User):
    """SQL condition limiting projects to those the user may see. None means unrestricted."""
    if user.role in MANAGE_ROLES:
        return None
    member_ids = select(m.ProjectMember.project_id).where(m.ProjectMember.user_id == user.id)
    task_ids = select(m.Task.project_id).where(m.Task.assignee_id == user.id, m.Task.project_id.is_not(None))
    return or_(m.Project.id.in_(member_ids), m.Project.id.in_(task_ids))


def visible_project_ids_subquery(user: m.User):
    stmt = select(m.Project.id)
    cond = visible_project_filter(user)
    if cond is not None:
        stmt = stmt.where(cond)
    return stmt


def get_project_or_404(db: Session, user: m.User, project_id: int) -> m.Project:
    project = db.get(m.Project, project_id)
    if not project:
        raise not_found("Project")
    cond = visible_project_filter(user)
    if cond is not None:
        allowed = db.scalar(select(func.count()).select_from(m.Project).where(m.Project.id == project_id, cond))
        if not allowed:
            raise not_found("Project")
    return project


# ---------------------------------------------------------------- audit
def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (dt.date, dt.datetime, dt.time)):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def snapshot(obj: Any, fields: list[str] | None = None) -> dict:
    cols = fields or [c.key for c in obj.__table__.columns]
    return {c: _jsonable(getattr(obj, c)) for c in cols}


def diff(before: dict, after: dict) -> dict:
    return {k: {"from": before.get(k), "to": after.get(k)} for k in after if before.get(k) != after.get(k)}


def audit(
    db: Session,
    user: m.User | None,
    action: str,
    entity_type: str,
    entity_id: int | None,
    project_id: int | None = None,
    changes: dict | None = None,
    request: Request | None = None,
) -> None:
    db.add(
        m.AuditLog(
            user_id=user.id if user else None,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            project_id=project_id,
            changes=_jsonable(changes) if changes else None,
            ip_address=request.client.host if request and request.client else None,
        )
    )


def apply_changes(obj: Any, data: dict) -> dict:
    """Set attributes on obj and return a field diff for the audit log."""
    before = {k: _jsonable(getattr(obj, k)) for k in data}
    for k, v in data.items():
        setattr(obj, k, v)
    after = {k: _jsonable(getattr(obj, k)) for k in data}
    return diff(before, after)


def today() -> dt.date:
    return dt.date.today()


def like(term: str) -> str:
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"
