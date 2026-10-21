import datetime as dt
from collections import defaultdict
from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import models as m
from ..core import can_view_finance, visible_project_filter
from ..db import get_db
from ..finance import compute_receivables, q2, summarize
from ..security import get_current_user
from .projects import planned_progress

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])
CLOSED = ("completed", "cancelled")


@router.get("")
def dashboard(
    date_from: dt.date | None = None, date_to: dt.date | None = None, client_id: int | None = None,
    project_id: int | None = None, status: str | None = None,
    db: Session = Depends(get_db), user: m.User = Depends(get_current_user),
):
    today = dt.date.today()
    date_to = date_to or today
    date_from = date_from or (date_to.replace(day=1) - dt.timedelta(days=330)).replace(day=1)

    stmt = select(m.Project).where(m.Project.archived_at.is_(None))
    cond = visible_project_filter(user)
    if cond is not None:
        stmt = stmt.where(cond)
    if client_id:
        stmt = stmt.where(m.Project.client_id == client_id)
    if project_id:
        stmt = stmt.where(m.Project.id == project_id)
    if status:
        stmt = stmt.where(m.Project.status.in_(status.split(",")))
    projects = db.scalars(stmt).all()
    ids = [p.id for p in projects]

    overdue = [p for p in projects if p.expected_completion_date and p.expected_completion_date < today and p.status not in CLOSED]
    status_dist: dict[str, int] = defaultdict(int)
    for p in projects:
        status_dist[p.status] += 1

    task_base = select(m.Task).where(m.Task.deleted_at.is_(None), m.Task.status != "completed")
    if user.role == "team_member":
        task_base = task_base.where((m.Task.project_id.in_(ids)) | (m.Task.assignee_id == user.id))
    else:
        if client_id or project_id or status:
            task_base = task_base.where(m.Task.project_id.in_(ids))
    open_tasks = db.scalars(task_base).all()
    overdue_tasks = [t for t in open_tasks if t.due_date and t.due_date < today]

    horizon = today + dt.timedelta(days=30)
    deadlines = []
    for p in projects:
        if p.expected_completion_date and today <= p.expected_completion_date <= horizon and p.status not in CLOSED:
            deadlines.append({"kind": "project", "id": p.id, "project_id": p.id, "title": f"{p.code} · {p.name}",
                              "date": p.expected_completion_date})
    for t in open_tasks:
        if t.due_date and today <= t.due_date <= horizon:
            deadlines.append({"kind": "task", "id": t.id, "project_id": t.project_id, "title": t.title, "date": t.due_date})
    deadlines.sort(key=lambda d: d["date"])

    upd_stmt = (
        select(m.ProjectUpdate)
        .where(m.ProjectUpdate.project_id.in_(ids),
               func.date(m.ProjectUpdate.update_at) >= date_from, func.date(m.ProjectUpdate.update_at) <= date_to)
        .order_by(m.ProjectUpdate.update_at.desc())
        .limit(8)
    )
    recent_updates = [
        {"id": u.id, "project_id": u.project_id, "project": f"{u.project.code} · {u.project.name}", "update_at": u.update_at,
         "author": u.author.full_name if u.author else None, "health": u.health, "progress": u.progress,
         "summary": (u.work_completed or "")[:220]}
        for u in db.scalars(upd_stmt).all()
    ]

    out = {
        "filters": {"date_from": date_from, "date_to": date_to, "client_id": client_id, "project_id": project_id, "status": status},
        "counts": {
            "total_projects": len(projects),
            "active_projects": sum(1 for p in projects if p.status == "active"),
            "completed_projects": sum(1 for p in projects if p.status == "completed"),
            "overdue_projects": len(overdue),
            "pending_tasks": len(open_tasks),
            "overdue_tasks": len(overdue_tasks),
        },
        "overdue_projects": [{"id": p.id, "code": p.code, "name": p.name, "expected_completion_date": p.expected_completion_date,
                              "days_overdue": (today - p.expected_completion_date).days, "progress": p.progress} for p in overdue[:10]],
        "upcoming_deadlines": deadlines[:12],
        "recent_updates": recent_updates,
        "charts": {
            "status_distribution": [{"status": k, "count": v} for k, v in sorted(status_dist.items())],
            "project_progress": sorted(
                [{"id": p.id, "code": p.code, "name": p.name, "progress": p.progress, "planned": planned_progress(p, today)}
                 for p in projects if p.status not in ("cancelled",)],
                key=lambda x: x["code"],
            )[:20],
        },
        "finance_visible": can_view_finance(user),
    }

    if can_view_finance(user):
        rec = compute_receivables(db, ids)
        out["receivables"] = summarize(rec)
        pending_q = db.execute(
            select(m.PaymentReceived.status, func.count(), func.coalesce(func.sum(m.PaymentReceived.amount), 0))
            .where(m.PaymentReceived.project_id.in_(ids), m.PaymentReceived.status.in_(["pending", "recorded"]))
            .group_by(m.PaymentReceived.status)
        ).all()
        out["pending_payments"] = {r[0]: {"count": r[1], "amount": str(q2(r[2]))} for r in pending_q}
        out["counts"]["pending_client_payments"] = sum(r[1] for r in pending_q)
        out["counts"]["overdue_receivables"] = sum(r.overdue_count for r in rec.values())
        out["charts"]["outstanding_by_project"] = sorted(
            [{"id": pid, "code": next(p.code for p in projects if p.id == pid), "currency": r.currency,
              "contract_value": float(r.contract_value), "received": float(r.verified_received), "outstanding": float(r.outstanding)}
             for pid, r in rec.items() if r.contract_value > 0 or r.verified_received > 0],
            key=lambda x: -x["outstanding"],
        )[:15]
        month_rows = db.execute(
            select(func.date_trunc("month", m.PaymentReceived.payment_date).label("mon"), m.Project.currency,
                   func.sum(m.PaymentReceived.amount))
            .join(m.Project, m.Project.id == m.PaymentReceived.project_id)
            .where(m.PaymentReceived.project_id.in_(ids), m.PaymentReceived.status == "verified",
                   m.PaymentReceived.payment_date >= date_from, m.PaymentReceived.payment_date <= date_to)
            .group_by("mon", m.Project.currency).order_by("mon")
        ).all()
        months = _month_range(date_from, date_to)
        series: dict[str, dict[str, Decimal]] = defaultdict(dict)
        for mon, cur, amt in month_rows:
            series[cur][mon.strftime("%Y-%m")] = amt
        out["charts"]["monthly_payments"] = [
            {"month": mo, **{cur: float(vals.get(mo, 0)) for cur, vals in series.items()}} for mo in months
        ]
        out["charts"]["payment_currencies"] = sorted(series.keys())
    return out


def _month_range(start: dt.date, end: dt.date) -> list[str]:
    months, cur = [], start.replace(day=1)
    while cur <= end and len(months) < 60:
        months.append(cur.strftime("%Y-%m"))
        cur = (cur + dt.timedelta(days=32)).replace(day=1)
    return months
