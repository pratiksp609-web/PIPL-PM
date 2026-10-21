import datetime as dt
import secrets

from fastapi import APIRouter, Depends, Request
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session, selectinload

from .. import models as m
from ..core import (
    MANAGE_ROLES, APIError, apply_changes, audit, bad_request, can_view_finance, get_project_or_404, like, not_found,
    page_response, paginate, visible_project_filter,
)
from ..db import get_db
from ..finance import procurement_summary, project_receivable
from ..notify import notify
from ..schemas import ProjectIn, ProjectOut, ProjectUpdateIn, validate_project_dates
from ..security import get_current_user, require_roles

router = APIRouter(prefix="/api/projects", tags=["projects"])
CLOSED = ("completed", "cancelled")


def is_overdue(p: m.Project, today: dt.date | None = None) -> bool:
    today = today or dt.date.today()
    return bool(p.expected_completion_date and p.expected_completion_date < today and p.status not in CLOSED)


def project_out(p: m.Project, user: m.User, task_counts: dict | None = None) -> ProjectOut:
    out = ProjectOut.model_validate(p)
    out.client_name = p.client.company_name if p.client else None
    out.manager_name = p.manager.full_name if p.manager else None
    out.is_overdue = is_overdue(p)
    out.member_ids = [mem.user_id for mem in p.members]
    if task_counts and p.id in task_counts:
        out.open_tasks, out.overdue_tasks = task_counts[p.id]
    if not can_view_finance(user):
        out.budget = None
        out.contract_value = None
    return out


def task_counts_for(db: Session, ids: list[int]) -> dict:
    if not ids:
        return {}
    today = dt.date.today()
    rows = db.execute(
        select(
            m.Task.project_id,
            func.count(case((m.Task.status != "completed", 1))),
            func.count(case((and_(m.Task.status != "completed", m.Task.due_date < today), 1))),
        )
        .where(m.Task.project_id.in_(ids), m.Task.deleted_at.is_(None))
        .group_by(m.Task.project_id)
    ).all()
    return {r[0]: (r[1], r[2]) for r in rows}


def _validate_refs(db: Session, client_id: int | None, manager_id: int | None, member_ids: list[int] | None):
    if client_id is not None:
        c = db.get(m.Client, client_id)
        if not c:
            raise bad_request("Selected client does not exist")
        if c.archived_at:
            raise bad_request("Selected client is archived")
    if manager_id is not None:
        mgr = db.get(m.User, manager_id)
        if not mgr or not mgr.is_active or mgr.role not in MANAGE_ROLES:
            raise bad_request("Project manager must be an active Admin or Project Manager user")
    if member_ids:
        found = db.scalars(select(m.User.id).where(m.User.id.in_(member_ids), m.User.is_active.is_(True))).all()
        if len(set(found)) != len(set(member_ids)):
            raise bad_request("One or more team members do not exist or are inactive")


@router.get("")
def list_projects(
    q: str | None = None, status: str | None = None, client_id: int | None = None, manager_id: int | None = None,
    priority: str | None = None, overdue: bool | None = None, include_archived: bool = False, archived_only: bool = False,
    sort: str = "-updated_at", page: int = 1, page_size: int = 25,
    db: Session = Depends(get_db), user: m.User = Depends(get_current_user),
):
    stmt = select(m.Project).options(selectinload(m.Project.client), selectinload(m.Project.manager), selectinload(m.Project.members))
    cond = visible_project_filter(user)
    if cond is not None:
        stmt = stmt.where(cond)
    if archived_only:
        stmt = stmt.where(m.Project.archived_at.is_not(None))
    elif not include_archived:
        stmt = stmt.where(m.Project.archived_at.is_(None))
    if q:
        t = like(q)
        stmt = stmt.join(m.Client).where(or_(m.Project.name.ilike(t), m.Project.code.ilike(t), m.Project.description.ilike(t),
                                             m.Client.company_name.ilike(t), m.Client.name.ilike(t)))
    if status:
        stmt = stmt.where(m.Project.status.in_(status.split(",")))
    if client_id:
        stmt = stmt.where(m.Project.client_id == client_id)
    if manager_id:
        stmt = stmt.where(m.Project.manager_id == manager_id)
    if priority:
        stmt = stmt.where(m.Project.priority == priority)
    if overdue:
        stmt = stmt.where(m.Project.expected_completion_date < dt.date.today(), m.Project.status.not_in(CLOSED))
    sorts = {
        "name": m.Project.name, "-name": m.Project.name.desc(), "code": m.Project.code, "-code": m.Project.code.desc(),
        "due": m.Project.expected_completion_date.asc().nulls_last(), "-due": m.Project.expected_completion_date.desc().nulls_last(),
        "progress": m.Project.progress, "-progress": m.Project.progress.desc(),
        "updated_at": m.Project.updated_at, "-updated_at": m.Project.updated_at.desc(),
    }
    stmt = stmt.order_by(sorts.get(sort, m.Project.updated_at.desc()), m.Project.id.desc())
    rows, total = paginate(db, stmt, page, page_size)
    counts = task_counts_for(db, [p.id for p in rows])
    return page_response([project_out(p, user, counts) for p in rows], total, page, page_size)


@router.post("", status_code=201)
def create_project(body: ProjectIn, request: Request, db: Session = Depends(get_db), user: m.User = Depends(require_roles(*MANAGE_ROLES))):
    _validate_refs(db, body.client_id, body.manager_id, body.member_ids)
    data = body.model_dump(exclude={"member_ids"})
    if data["status"] == "completed" and not data.get("actual_completion_date"):
        data["actual_completion_date"] = dt.date.today()
    p = m.Project(**data, code=f"TMP-{secrets.token_hex(6)}", created_by_id=user.id, updated_by_id=user.id)
    if p.manager_id is None:
        p.manager_id = user.id
    db.add(p)
    db.flush()
    p.code = f"PIPL-{dt.date.today().year}-{p.id:04d}"
    for uid in set(body.member_ids):
        db.add(m.ProjectMember(project_id=p.id, user_id=uid))
    audit(db, user, "create", "project", p.id, p.id, changes={**data, "code": p.code}, request=request)
    db.commit()
    db.refresh(p)
    return project_out(p, user)


def planned_progress(p: m.Project, today: dt.date) -> int | None:
    """Linear plan estimate: share of scheduled time elapsed. Labelled as an estimate in the UI."""
    if not (p.start_date and p.expected_completion_date) or p.expected_completion_date <= p.start_date:
        return None
    total = (p.expected_completion_date - p.start_date).days
    elapsed = min(max((today - p.start_date).days, 0), total)
    return round(elapsed * 100 / total)


@router.get("/{project_id}")
def get_project(project_id: int, db: Session = Depends(get_db), user: m.User = Depends(get_current_user)):
    p = get_project_or_404(db, user, project_id)
    counts = task_counts_for(db, [p.id])
    latest = db.scalar(select(m.ProjectUpdate).where(m.ProjectUpdate.project_id == p.id).order_by(m.ProjectUpdate.update_at.desc()).limit(1))
    today = dt.date.today()
    upcoming = db.scalars(
        select(m.Task).where(m.Task.project_id == p.id, m.Task.deleted_at.is_(None), m.Task.status != "completed",
                             m.Task.due_date.is_not(None)).order_by(m.Task.due_date).limit(8)
    ).all()
    out = {
        "project": project_out(p, user, counts),
        "latest_update": None,
        "upcoming_tasks": [
            {"id": t.id, "title": t.title, "due_date": t.due_date, "status": t.status, "priority": t.priority,
             "overdue": bool(t.due_date and t.due_date < today), "assignee": t.assignee.full_name if t.assignee else None}
            for t in upcoming
        ],
        "planned_progress": None if p.status in CLOSED else planned_progress(p, today),
        "doc_count": db.scalar(select(func.count()).select_from(m.Document).where(m.Document.project_id == p.id, m.Document.deleted_at.is_(None))),
    }
    if latest:
        out["latest_update"] = {
            "id": latest.id, "update_at": latest.update_at, "author": latest.author.full_name if latest.author else None,
            "health": latest.health, "progress": latest.progress, "work_completed": latest.work_completed,
            "blockers": latest.blockers, "next_steps": latest.next_steps,
        }
        out["days_since_update"] = (dt.datetime.now(dt.timezone.utc) - latest.update_at).days
    if can_view_finance(user):
        out["receivable"] = project_receivable(db, p.id).as_dict()
        out["procurement"] = procurement_summary(db, p.id)
    return out


@router.patch("/{project_id}")
def update_project(project_id: int, body: ProjectUpdateIn, request: Request, db: Session = Depends(get_db), user: m.User = Depends(require_roles(*MANAGE_ROLES))):
    p = get_project_or_404(db, user, project_id)
    ensure_project_editable(p)
    data = body.model_dump(exclude_unset=True)
    member_ids = data.pop("member_ids", None)
    for required in ("name", "client_id", "currency", "status", "priority", "progress"):
        if required in data and data[required] is None:
            raise bad_request(f"{required.replace('_', ' ').capitalize()} cannot be empty")
    _validate_refs(db, data.get("client_id"), data.get("manager_id"), member_ids)
    if data.get("status") == "completed" and not (data.get("actual_completion_date") or p.actual_completion_date):
        data["actual_completion_date"] = dt.date.today()
    try:
        validate_project_dates(
            data.get("start_date", p.start_date), data.get("expected_completion_date", p.expected_completion_date),
            data.get("actual_completion_date", p.actual_completion_date),
        )
    except ValueError as exc:
        raise bad_request(str(exc))
    old_status = p.status
    changes = apply_changes(p, data)
    p.updated_by_id = user.id
    if member_ids is not None:
        p.members.clear()
        db.flush()
        for uid in set(member_ids):
            p.members.append(m.ProjectMember(project_id=p.id, user_id=uid))
        changes["member_ids"] = sorted(set(member_ids))
    audit(db, user, "update", "project", p.id, p.id, changes=changes, request=request)
    if "status" in data and data["status"] != old_status:
        recipients = {p.manager_id, *[mem.user_id for mem in p.members]} - {None, user.id}
        for uid in recipients:
            notify(db, uid, "project_change", f"{p.code} status changed",
                   f"{p.name} moved from {old_status} to {p.status} by {user.full_name}.",
                   dedupe_key=f"project_status:{p.id}:{p.status}:{dt.datetime.now().timestamp():.0f}",
                   link=f"/projects/{p.id}", entity_type="project", entity_id=p.id)
    db.commit()
    db.refresh(p)
    return project_out(p, user, task_counts_for(db, [p.id]))


@router.post("/{project_id}/archive")
def archive_project(project_id: int, request: Request, archived: bool = True, db: Session = Depends(get_db), user: m.User = Depends(require_roles(*MANAGE_ROLES))):
    p = get_project_or_404(db, user, project_id)
    p.archived_at = dt.datetime.now(dt.timezone.utc) if archived else None
    audit(db, user, "archive" if archived else "unarchive", "project", p.id, p.id, request=request)
    db.commit()
    return project_out(p, user)


@router.get("/{project_id}/audit")
def project_audit(project_id: int, db: Session = Depends(get_db), user: m.User = Depends(require_roles(*MANAGE_ROLES))):
    get_project_or_404(db, user, project_id)
    rows = db.scalars(select(m.AuditLog).where(m.AuditLog.project_id == project_id).order_by(m.AuditLog.id.desc()).limit(200)).all()
    return {"items": [{"id": r.id, "action": r.action, "entity_type": r.entity_type, "entity_id": r.entity_id,
                       "changes": r.changes, "user": r.user.full_name if r.user else None, "created_at": r.created_at} for r in rows]}


def ensure_project_editable(p: m.Project) -> None:
    if p.archived_at:
        raise APIError(409, "This project is archived. Restore it before making changes.", "archived")
