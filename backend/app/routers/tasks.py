import datetime as dt

from fastapi import APIRouter, Depends, Request
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from .. import models as m
from ..core import (
    MANAGE_ROLES, apply_changes, audit, bad_request, forbidden, get_project_or_404, like, not_found, page_response,
    paginate, snapshot, visible_project_ids_subquery,
)
from ..db import get_db
from ..notify import notify
from ..schemas import TaskIn, TaskUpdate
from ..security import get_current_user, require_roles

router = APIRouter(prefix="/api/tasks", tags=["tasks"])
MEMBER_EDITABLE = {"status", "progress", "description"}


def task_out(t: m.Task) -> dict:
    d = snapshot(t, ["id", "project_id", "title", "description", "assignee_id", "priority", "status", "progress",
                     "start_date", "due_date", "completed_at", "created_at", "updated_at", "created_by_id"])
    d["assignee_name"] = t.assignee.full_name if t.assignee else None
    d["project"] = f"{t.project.code} · {t.project.name}" if t.project else None
    d["is_overdue"] = bool(t.due_date and t.due_date < dt.date.today() and t.status != "completed")
    return d


def _visible_tasks(user: m.User):
    stmt = select(m.Task).options(selectinload(m.Task.assignee), selectinload(m.Task.project)).where(m.Task.deleted_at.is_(None))
    if user.role not in MANAGE_ROLES:
        stmt = stmt.where(or_(m.Task.assignee_id == user.id, m.Task.created_by_id == user.id,
                              m.Task.project_id.in_(visible_project_ids_subquery(user))))
    return stmt


def _get(db: Session, user: m.User, task_id: int) -> m.Task:
    t = db.scalar(_visible_tasks(user).where(m.Task.id == task_id))
    if not t:
        raise not_found("Task")
    return t


def _validate(db: Session, user: m.User, project_id: int | None, assignee_id: int | None):
    if project_id is not None:
        p = get_project_or_404(db, user, project_id)
        if p.archived_at:
            raise bad_request("Cannot add tasks to an archived project")
    if assignee_id is not None:
        a = db.get(m.User, assignee_id)
        if not a or not a.is_active:
            raise bad_request("Assignee does not exist or is inactive")
        if user.role not in MANAGE_ROLES and assignee_id != user.id:
            raise forbidden("Team members can only assign tasks to themselves")


def _apply_status_rules(t: m.Task):
    if t.status == "completed":
        t.progress = 100
        t.completed_at = t.completed_at or dt.datetime.now(dt.timezone.utc)
    else:
        t.completed_at = None
        if t.progress == 100:
            t.progress = 90


@router.get("")
def list_tasks(
    q: str | None = None, project_id: int | None = None, assignee_id: int | None = None, mine: bool = False,
    status: str | None = None, priority: str | None = None, overdue: bool | None = None, due_from: dt.date | None = None,
    due_to: dt.date | None = None, include_completed: bool = True, sort: str = "due", page: int = 1, page_size: int = 50,
    db: Session = Depends(get_db), user: m.User = Depends(get_current_user),
):
    stmt = _visible_tasks(user)
    if q:
        stmt = stmt.where(or_(m.Task.title.ilike(like(q)), m.Task.description.ilike(like(q))))
    if project_id:
        stmt = stmt.where(m.Task.project_id == project_id)
    if mine:
        stmt = stmt.where(m.Task.assignee_id == user.id)
    elif assignee_id:
        stmt = stmt.where(m.Task.assignee_id == assignee_id)
    if status:
        stmt = stmt.where(m.Task.status.in_(status.split(",")))
    elif not include_completed:
        stmt = stmt.where(m.Task.status != "completed")
    if priority:
        stmt = stmt.where(m.Task.priority.in_(priority.split(",")))
    if overdue:
        stmt = stmt.where(m.Task.due_date < dt.date.today(), m.Task.status != "completed")
    if due_from:
        stmt = stmt.where(m.Task.due_date >= due_from)
    if due_to:
        stmt = stmt.where(m.Task.due_date <= due_to)
    from sqlalchemy import case

    prio = case({"critical": 0, "high": 1, "medium": 2, "low": 3}, value=m.Task.priority)
    sorts = {"due": (m.Task.due_date.asc().nulls_last(), prio), "-due": (m.Task.due_date.desc().nulls_last(),),
             "priority": (prio, m.Task.due_date.asc().nulls_last()), "created": (m.Task.created_at.desc(),),
             "title": (m.Task.title,), "status": (m.Task.status, m.Task.due_date.asc().nulls_last())}
    stmt = stmt.order_by(*sorts.get(sort, sorts["due"]), m.Task.id)
    rows, total = paginate(db, stmt, page, page_size)
    return page_response([task_out(t) for t in rows], total, page, page_size)


@router.post("", status_code=201)
def create_task(body: TaskIn, request: Request, db: Session = Depends(get_db), user: m.User = Depends(get_current_user)):
    assignee_id = body.assignee_id if body.assignee_id is not None else (user.id if user.role not in MANAGE_ROLES else None)
    _validate(db, user, body.project_id, assignee_id)
    t = m.Task(**body.model_dump(exclude={"assignee_id"}), assignee_id=assignee_id, created_by_id=user.id, updated_by_id=user.id)
    if t.status == "completed":
        _apply_status_rules(t)
    db.add(t)
    db.flush()
    audit(db, user, "create", "task", t.id, t.project_id, changes=body.model_dump(mode="json"), request=request)
    if t.assignee_id and t.assignee_id != user.id:
        notify(db, t.assignee_id, "task_assigned", "New task assigned", f"{user.full_name} assigned you: {t.title}",
               dedupe_key=f"task_assigned:{t.id}:{t.assignee_id}", link=f"/tasks?task={t.id}", entity_type="task", entity_id=t.id)
    db.commit()
    db.refresh(t)
    return task_out(t)


@router.get("/{task_id}")
def get_task(task_id: int, db: Session = Depends(get_db), user: m.User = Depends(get_current_user)):
    t = _get(db, user, task_id)
    docs = db.scalars(select(m.Document).where(m.Document.task_id == t.id, m.Document.deleted_at.is_(None))).all()
    return {"task": task_out(t), "attachments": [{"id": d.id, "title": d.title, "extension": d.extension, "created_at": d.created_at} for d in docs]}


@router.patch("/{task_id}")
def update_task(task_id: int, body: TaskUpdate, request: Request, db: Session = Depends(get_db), user: m.User = Depends(get_current_user)):
    t = _get(db, user, task_id)
    data = body.model_dump(exclude_unset=True)
    is_owner = t.assignee_id == user.id or t.created_by_id == user.id
    if user.role not in MANAGE_ROLES:
        if not is_owner:
            raise forbidden("You can only update tasks assigned to you")
        if t.created_by_id != user.id and set(data) - MEMBER_EDITABLE:
            raise forbidden("You can update status, progress and description of tasks assigned to you")
    for required in ("title", "status", "priority", "progress"):
        if required in data and data[required] is None:
            raise bad_request(f"{required.capitalize()} cannot be empty")
    if "project_id" in data or "assignee_id" in data:
        _validate(db, user, data.get("project_id"), data.get("assignee_id"))
    start = data.get("start_date", t.start_date)
    due = data.get("due_date", t.due_date)
    if start and due and due < start:
        raise bad_request("Due date cannot be before the start date")
    old_assignee = t.assignee_id
    changes = apply_changes(t, data)
    if "status" in data or "progress" in data:
        if data.get("progress") == 100 and "status" not in data:
            t.status = "completed"
        _apply_status_rules(t)
    t.updated_by_id = user.id
    audit(db, user, "update", "task", t.id, t.project_id, changes=changes, request=request)
    if t.assignee_id and t.assignee_id != old_assignee and t.assignee_id != user.id:
        notify(db, t.assignee_id, "task_assigned", "Task assigned to you", f"{user.full_name} assigned you: {t.title}",
               dedupe_key=f"task_assigned:{t.id}:{t.assignee_id}", link=f"/tasks?task={t.id}", entity_type="task", entity_id=t.id)
    db.commit()
    db.refresh(t)
    return task_out(t)


@router.delete("/{task_id}")
def delete_task(task_id: int, request: Request, db: Session = Depends(get_db), user: m.User = Depends(get_current_user)):
    t = _get(db, user, task_id)
    if user.role not in MANAGE_ROLES and t.created_by_id != user.id:
        raise forbidden("Only managers or the task creator can delete a task")
    t.deleted_at = dt.datetime.now(dt.timezone.utc)
    audit(db, user, "delete", "task", t.id, t.project_id, request=request)
    db.commit()
    return {"ok": True}
