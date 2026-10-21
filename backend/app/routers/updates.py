import datetime as dt

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from .. import models as m
from ..core import (
    MANAGE_ROLES, audit, bad_request, forbidden, get_project_or_404, like, not_found, page_response, paginate, snapshot,
    visible_project_ids_subquery,
)
from ..db import get_db
from ..schemas import UpdateEdit, UpdateIn
from ..security import get_current_user

router = APIRouter(prefix="/api/updates", tags=["project updates"])
CONTENT_FIELDS = ["health", "work_completed", "progress", "work_in_progress", "blockers", "risks", "materials_required",
                  "next_steps", "planned_completion_date", "remarks"]


def update_out(u: m.ProjectUpdate) -> dict:
    d = snapshot(u, ["id", "project_id", "author_id", "update_at", *CONTENT_FIELDS, "revision_count", "created_at", "edited_at"])
    d["author_name"] = u.author.full_name if u.author else None
    d["project"] = f"{u.project.code} · {u.project.name}" if u.project else None
    d["client_name"] = u.project.client.company_name if u.project and u.project.client else None
    return d


@router.get("")
def list_updates(
    q: str | None = None, project_id: int | None = None, client_id: int | None = None, author_id: int | None = None,
    health: str | None = None, project_status: str | None = None, date_from: dt.date | None = None, date_to: dt.date | None = None,
    order: str = "desc", page: int = 1, page_size: int = 25,
    db: Session = Depends(get_db), user: m.User = Depends(get_current_user),
):
    stmt = select(m.ProjectUpdate).options(selectinload(m.ProjectUpdate.author), selectinload(m.ProjectUpdate.project).selectinload(m.Project.client)) \
        .where(m.ProjectUpdate.project_id.in_(visible_project_ids_subquery(user)))
    if project_id:
        stmt = stmt.where(m.ProjectUpdate.project_id == project_id)
    if client_id or project_status:
        sub = select(m.Project.id)
        if client_id:
            sub = sub.where(m.Project.client_id == client_id)
        if project_status:
            sub = sub.where(m.Project.status.in_(project_status.split(",")))
        stmt = stmt.where(m.ProjectUpdate.project_id.in_(sub))
    if author_id:
        stmt = stmt.where(m.ProjectUpdate.author_id == author_id)
    if health:
        stmt = stmt.where(m.ProjectUpdate.health.in_(health.split(",")))
    if date_from:
        stmt = stmt.where(m.ProjectUpdate.update_at >= dt.datetime.combine(date_from, dt.time.min, dt.timezone.utc))
    if date_to:
        stmt = stmt.where(m.ProjectUpdate.update_at < dt.datetime.combine(date_to + dt.timedelta(days=1), dt.time.min, dt.timezone.utc))
    if q:
        t = like(q)
        stmt = stmt.where(or_(m.ProjectUpdate.work_completed.ilike(t), m.ProjectUpdate.blockers.ilike(t),
                              m.ProjectUpdate.next_steps.ilike(t), m.ProjectUpdate.remarks.ilike(t), m.ProjectUpdate.risks.ilike(t)))
    stmt = stmt.order_by(m.ProjectUpdate.update_at.asc() if order == "asc" else m.ProjectUpdate.update_at.desc(), m.ProjectUpdate.id.desc())
    rows, total = paginate(db, stmt, page, page_size)
    return page_response([update_out(u) for u in rows], total, page, page_size)


@router.post("", status_code=201)
def create_update(body: UpdateIn, request: Request, db: Session = Depends(get_db), user: m.User = Depends(get_current_user)):
    project = get_project_or_404(db, user, body.project_id)
    if project.archived_at:
        raise bad_request("Cannot add updates to an archived project")
    now = dt.datetime.now(dt.timezone.utc)
    when = body.update_at or now
    if when.tzinfo is None:
        raise bad_request("Update time must include a timezone offset")
    if when > now + dt.timedelta(minutes=5):
        raise bad_request("Update time cannot be in the future")
    u = m.ProjectUpdate(**body.model_dump(exclude={"apply_progress_to_project", "update_at"}), update_at=when, author_id=user.id)
    db.add(u)
    db.flush()
    changes = body.model_dump(mode="json")
    if body.apply_progress_to_project and project.progress != body.progress:
        changes["project_progress"] = {"from": project.progress, "to": body.progress}
        project.progress = body.progress
        audit(db, user, "progress_from_update", "project", project.id, project.id, changes={"progress": changes["project_progress"], "update_id": u.id})
    audit(db, user, "create", "project_update", u.id, project.id, changes=changes, request=request)
    db.commit()
    db.refresh(u)
    return update_out(u)


@router.get("/{update_id}")
def get_update(update_id: int, db: Session = Depends(get_db), user: m.User = Depends(get_current_user)):
    u = db.get(m.ProjectUpdate, update_id)
    if not u:
        raise not_found("Update")
    get_project_or_404(db, user, u.project_id)
    revs = db.scalars(select(m.ProjectUpdateRevision).where(m.ProjectUpdateRevision.update_id == u.id)
                      .order_by(m.ProjectUpdateRevision.revision_number.desc())).all()
    editors = {x.id: x.full_name for x in db.scalars(select(m.User).where(m.User.id.in_({r.edited_by_id for r in revs}))).all()}
    docs = db.scalars(select(m.Document).where(m.Document.update_id == u.id, m.Document.deleted_at.is_(None))).all()
    return {
        "update": update_out(u),
        "revisions": [{"revision_number": r.revision_number, "snapshot": r.snapshot, "reason": r.reason,
                       "edited_by": editors.get(r.edited_by_id), "edited_at": r.edited_at} for r in revs],
        "attachments": [{"id": d.id, "title": d.title, "extension": d.extension} for d in docs],
    }


@router.patch("/{update_id}")
def edit_update(update_id: int, body: UpdateEdit, request: Request, db: Session = Depends(get_db), user: m.User = Depends(get_current_user)):
    u = db.get(m.ProjectUpdate, update_id)
    if not u:
        raise not_found("Update")
    get_project_or_404(db, user, u.project_id)
    if user.role not in MANAGE_ROLES and u.author_id != user.id:
        raise forbidden("Only the author or a manager can correct this update")
    data = body.model_dump(exclude_unset=True, exclude={"reason"})
    if data.get("work_completed", "x") is None or data.get("progress", 0) is None:
        raise bad_request("Work completed and progress cannot be empty")
    before = snapshot(u, CONTENT_FIELDS)
    changed = data
    if not changed:
        raise bad_request("No changes supplied")
    rev_no = (db.scalar(select(func.max(m.ProjectUpdateRevision.revision_number)).where(m.ProjectUpdateRevision.update_id == u.id)) or 0) + 1
    db.add(m.ProjectUpdateRevision(update_id=u.id, revision_number=rev_no, snapshot=before, reason=body.reason, edited_by_id=user.id))
    for k, v in changed.items():
        setattr(u, k, v)
    u.revision_count = rev_no
    u.edited_at = dt.datetime.now(dt.timezone.utc)
    u.edited_by_id = user.id
    after = snapshot(u, CONTENT_FIELDS)
    audit(db, user, "correct", "project_update", u.id, u.project_id,
          changes={"reason": body.reason, **{k: {"from": before[k], "to": after[k]} for k in after if before[k] != after[k]}},
          request=request)
    db.commit()
    return update_out(u)
