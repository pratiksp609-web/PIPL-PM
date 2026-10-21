"""Deterministic status-report builder. Everything here comes from database records; AI analysis is optional on top."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models as m
from .core import can_view_finance, visible_project_filter
from .finance import compute_receivables, procurement_summary, summarize

CLOSED = ("completed", "cancelled")


def resolve_period(period_type: str, start: dt.date | None, end: dt.date | None, today: dt.date | None = None) -> tuple[dt.date, dt.date]:
    today = today or dt.date.today()
    anchor = start or today
    if period_type == "custom":
        return start, end
    if period_type == "weekly":
        if start:
            s = start - dt.timedelta(days=start.weekday())
            return s, s + dt.timedelta(days=6)
        return today - dt.timedelta(days=6), today
    if period_type == "monthly":
        s = anchor.replace(day=1)
        e = (s + dt.timedelta(days=32)).replace(day=1) - dt.timedelta(days=1)
        return s, min(e, today) if not start else e
    if period_type == "quarterly":
        qm = 3 * ((anchor.month - 1) // 3) + 1
        s = anchor.replace(month=qm, day=1)
        e = (s.replace(month=qm + 2, day=1) + dt.timedelta(days=32)).replace(day=1) - dt.timedelta(days=1)
        return s, min(e, today) if not start else e
    if period_type == "annual":
        s = anchor.replace(month=1, day=1)
        e = anchor.replace(month=12, day=31)
        return s, min(e, today) if not start else e
    raise ValueError("Unknown period type")


def planned_progress(p: m.Project, as_of: dt.date) -> int | None:
    if not (p.start_date and p.expected_completion_date) or p.expected_completion_date <= p.start_date:
        return None
    total = (p.expected_completion_date - p.start_date).days
    elapsed = min(max((as_of - p.start_date).days, 0), total)
    return round(elapsed * 100 / total)


def _dtrange(start: dt.date, end: dt.date) -> tuple[dt.datetime, dt.datetime]:
    return (dt.datetime.combine(start, dt.time.min, dt.timezone.utc),
            dt.datetime.combine(end + dt.timedelta(days=1), dt.time.min, dt.timezone.utc))


def build_report(db: Session, user: m.User, *, period_type: str, start: dt.date, end: dt.date, scope: str,
                 project_id: int | None = None, client_id: int | None = None, manager_id: int | None = None,
                 status: str | None = None, missing_update_days: int = 3) -> dict:
    finance = can_view_finance(user)
    today = dt.date.today()
    as_of = min(end, today)
    lo, hi = _dtrange(start, end)

    stmt = select(m.Project).where(m.Project.archived_at.is_(None))
    cond = visible_project_filter(user)
    if cond is not None:
        stmt = stmt.where(cond)
    if scope == "project":
        stmt = stmt.where(m.Project.id == project_id)
    if client_id:
        stmt = stmt.where(m.Project.client_id == client_id)
    if manager_id:
        stmt = stmt.where(m.Project.manager_id == manager_id)
    if status:
        stmt = stmt.where(m.Project.status == status)
    projects = db.scalars(stmt.order_by(m.Project.code)).all()
    ids = [p.id for p in projects]
    receivables = compute_receivables(db, ids, as_of=as_of) if finance else {}

    project_rows = []
    for p in projects:
        tasks = db.scalars(select(m.Task).where(m.Task.project_id == p.id, m.Task.deleted_at.is_(None))).all()
        open_tasks = [t for t in tasks if t.status != "completed"]
        overdue_tasks = [t for t in open_tasks if t.due_date and t.due_date < as_of]
        completed = [t for t in tasks if t.completed_at and lo <= t.completed_at < hi]
        blocked = [t for t in open_tasks if t.status == "blocked"]
        updates = db.scalars(select(m.ProjectUpdate).where(m.ProjectUpdate.project_id == p.id, m.ProjectUpdate.update_at >= lo,
                                                           m.ProjectUpdate.update_at < hi).order_by(m.ProjectUpdate.update_at)).all()
        last_update = db.scalar(select(m.ProjectUpdate).where(m.ProjectUpdate.project_id == p.id, m.ProjectUpdate.update_at < hi)
                                .order_by(m.ProjectUpdate.update_at.desc()).limit(1))
        days_since = (as_of - last_update.update_at.date()).days if last_update else None
        horizon = as_of + dt.timedelta(days=14)
        upcoming = [{"kind": "task", "title": t.title, "date": t.due_date} for t in open_tasks if t.due_date and as_of <= t.due_date <= horizon]
        if p.expected_completion_date and as_of <= p.expected_completion_date <= horizon and p.status not in CLOSED:
            upcoming.append({"kind": "project_deadline", "title": "Project completion", "date": p.expected_completion_date})

        planned = planned_progress(p, as_of)
        is_overdue = bool(p.expected_completion_date and p.expected_completion_date < as_of and p.status not in CLOSED)
        if p.status in CLOSED:
            health = p.status
        elif is_overdue or (last_update and last_update.health in ("delayed", "blocked")):
            health = "delayed"
        elif (planned is not None and planned - p.progress >= 15) or overdue_tasks or (last_update and last_update.health == "at_risk"):
            health = "at_risk"
        else:
            health = "on_track"

        blockers = [{"date": u.update_at.date().isoformat(), "text": u.blockers} for u in updates if u.blockers] + \
                   [{"date": u.update_at.date().isoformat(), "text": f"Risk: {u.risks}"} for u in updates if u.risks]
        issues = data_checks(db, p, tasks, last_update, days_since, receivables.get(p.id), missing_update_days, as_of)
        row = {
            "id": p.id, "code": p.code, "name": p.name, "client": p.client.company_name,
            "manager": p.manager.full_name if p.manager else None, "status": p.status, "priority": p.priority,
            "health": health, "progress": p.progress, "planned_progress": planned,
            "planned_progress_note": "Linear estimate based on start and expected completion dates" if planned is not None else None,
            "start_date": p.start_date, "expected_completion_date": p.expected_completion_date, "is_overdue": is_overdue,
            "open_task_count": len(open_tasks), "overdue_task_count": len(overdue_tasks), "blocked_task_count": len(blocked),
            "completed_tasks": [{"title": t.title, "completed_at": t.completed_at.date().isoformat()} for t in completed],
            "overdue_tasks": [{"title": t.title, "due_date": t.due_date, "assignee": t.assignee.full_name if t.assignee else None,
                               "days_overdue": (as_of - t.due_date).days} for t in overdue_tasks],
            "upcoming": sorted(upcoming, key=lambda x: x["date"]),
            "updates": [{"update_at": u.update_at.strftime("%Y-%m-%d %H:%M"), "author": u.author.full_name if u.author else None,
                         "progress": u.progress, "health": u.health, "work_completed": u.work_completed[:500]} for u in updates],
            "update_count": len(updates), "days_since_last_update": days_since, "blockers": blockers, "data_issues": issues,
        }
        if finance:
            row["receivable"] = receivables[p.id].as_dict()
            proc = procurement_summary(db, p.id, as_of)
            row["procurement"] = proc
            row["approved_quotation"] = _approved_quote(db, p.id)
            row["client_pos"] = [{"po_number": po.po_number, "status": po.status, "total_value": str(po.total_value) if po.total_value is not None else None}
                                 for po in db.scalars(select(m.ClientPurchaseOrder).where(m.ClientPurchaseOrder.project_id == p.id))]
        row["next_actions"] = next_actions(row)
        project_rows.append(row)

    summary = {
        "projects_in_scope": len(project_rows),
        "active": sum(1 for r in project_rows if r["status"] == "active"),
        "completed": sum(1 for r in project_rows if r["status"] == "completed"),
        "on_track": sum(1 for r in project_rows if r["health"] == "on_track"),
        "at_risk": sum(1 for r in project_rows if r["health"] == "at_risk"),
        "delayed": sum(1 for r in project_rows if r["health"] == "delayed"),
        "overdue_projects": sum(1 for r in project_rows if r["is_overdue"]),
        "overdue_tasks": sum(r["overdue_task_count"] for r in project_rows),
        "tasks_completed_in_period": sum(len(r["completed_tasks"]) for r in project_rows),
        "updates_in_period": sum(r["update_count"] for r in project_rows),
        "projects_missing_updates": sum(1 for r in project_rows if any(i["type"] == "missing_update" for i in r["data_issues"])),
        "data_issues": sum(len(r["data_issues"]) for r in project_rows),
    }
    data = {
        "scope": scope, "period_type": period_type, "period": {"start": start.isoformat(), "end": end.isoformat(), "as_of": as_of.isoformat()},
        "filters": {"project_id": project_id, "client_id": client_id, "manager_id": manager_id, "status": status},
        "summary": summary, "projects": project_rows, "finance_included": finance,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    if finance:
        late_deliveries = sum(len(r["procurement"]["late_deliveries"]) for r in project_rows)
        summary["late_supplier_deliveries"] = late_deliveries
        summary["pending_procurement_items"] = sum(r["procurement"]["pending_procurement_count"] for r in project_rows)
        data["financial"] = {
            "totals_by_currency": summarize(receivables),
            "note": "X = approved contract value, Y = verified client payments, Z = outstanding receivable. Supplier payments excluded.",
        }
    data["template_summary"] = template_summary(data)
    return data


def _approved_quote(db: Session, project_id: int) -> dict | None:
    v = db.scalar(select(m.QuotationVersion).join(m.Quotation).where(m.Quotation.project_id == project_id,
                                                                     m.QuotationVersion.status == "approved").limit(1))
    if not v:
        return None
    return {"quotation_number": v.quotation.quotation_number, "revision": v.revision_number,
            "total_amount": str(v.total_amount) if v.total_amount is not None else None, "currency": v.currency}


def data_checks(db: Session, p: m.Project, tasks, last_update, days_since, rec, missing_days: int, as_of: dt.date) -> list[dict]:
    issues = []
    if p.status == "active" and (days_since is None or days_since > missing_days):
        issues.append({"type": "missing_update", "text": "No progress update recorded" if days_since is None
                       else f"No progress update for {days_since} days (rule: {missing_days})"})
    if p.progress == 100 and p.status not in CLOSED:
        issues.append({"type": "inconsistent", "text": "Progress is 100% but the project is not marked completed"})
    open_count = sum(1 for t in tasks if t.status != "completed")
    if p.status == "completed" and open_count:
        issues.append({"type": "inconsistent", "text": f"Project is completed but {open_count} task(s) remain open"})
    if last_update and last_update.progress != p.progress:
        issues.append({"type": "inconsistent", "text": f"Latest update reports {last_update.progress}% but project progress is {p.progress}%"})
    if p.status == "active" and not p.expected_completion_date:
        issues.append({"type": "missing_data", "text": "Active project has no expected completion date"})
    if rec is not None:
        if rec.contract_basis != "verified_client_po" and p.status in ("active", "completed"):
            issues.append({"type": "missing_data", "text": "No verified client PO; contract value is " +
                           ("not set" if rec.contract_basis == "not_set" else f"based on {rec.contract_basis.replace('_', ' ')}")})
        if rec.credit > 0:
            issues.append({"type": "financial", "text": f"Verified payments exceed contract value; credit of {rec.credit} {rec.currency}"})
        if rec.unverified_recorded > 0:
            issues.append({"type": "financial", "text": f"{rec.unverified_recorded} {rec.currency} recorded but not yet verified"})
        missing_docs = db.scalars(select(m.SupplierPurchaseOrder.po_number).where(
            m.SupplierPurchaseOrder.project_id == p.id, m.SupplierPurchaseOrder.document_id.is_(None),
            m.SupplierPurchaseOrder.status != "cancelled")).all()
        if missing_docs:
            issues.append({"type": "missing_document", "text": f"Supplier PO(s) without uploaded document: {', '.join(missing_docs)}"})
        unverified_q = db.scalar(select(m.QuotationVersion.id).join(m.Quotation).where(
            m.Quotation.project_id == p.id, m.QuotationVersion.extraction.is_not(None),
            m.QuotationVersion.extraction_verified.is_(False), m.QuotationVersion.status.in_(["draft", "submitted"])).limit(1))
        if unverified_q:
            issues.append({"type": "needs_verification", "text": "A quotation has automatically extracted values awaiting verification"})
    return issues


def next_actions(row: dict) -> list[str]:
    acts = []
    if row["overdue_task_count"]:
        acts.append(f"Resolve or re-plan {row['overdue_task_count']} overdue task(s).")
    if row["blocked_task_count"]:
        acts.append(f"Unblock {row['blocked_task_count']} blocked task(s).")
    if row["is_overdue"]:
        acts.append("Project is past its expected completion date: agree a revised date with the client.")
    if row["planned_progress"] is not None and row["planned_progress"] - row["progress"] >= 15 and row["status"] not in CLOSED:
        acts.append(f"Progress ({row['progress']}%) trails the linear plan estimate ({row['planned_progress']}%): review resourcing.")
    for i in row["data_issues"]:
        if i["type"] == "missing_update":
            acts.append("Submit a progress update.")
        elif i["type"] == "missing_document":
            acts.append("Upload missing supplier PO documents.")
        elif i["type"] == "needs_verification":
            acts.append("Verify extracted quotation values.")
    rec = row.get("receivable")
    if rec and rec["overdue_count"]:
        acts.append(f"Follow up {rec['overdue_count']} overdue client payment(s) totalling {rec['overdue_pending']} {rec['currency']}.")
    if rec and Decimal(rec["unverified_recorded"]) > 0:
        acts.append("Verify recorded client payments against bank statements.")
    proc = row.get("procurement")
    if proc and proc["late_deliveries"]:
        acts.append(f"Expedite {len(proc['late_deliveries'])} late supplier deliver{'y' if len(proc['late_deliveries']) == 1 else 'ies'}.")
    if proc and proc["pending_procurement_count"]:
        acts.append(f"Raise purchase orders for {proc['pending_procurement_count']} pending BOM item(s).")
    return list(dict.fromkeys(acts))


def template_summary(data: dict) -> list[str]:
    s = data["summary"]
    lines = [
        f"{s['projects_in_scope']} project(s) in scope for {data['period']['start']} to {data['period']['end']}: "
        f"{s['on_track']} on track, {s['at_risk']} at risk, {s['delayed']} delayed.",
        f"{s['tasks_completed_in_period']} task(s) completed and {s['updates_in_period']} progress update(s) submitted in the period.",
    ]
    if s["overdue_tasks"]:
        lines.append(f"{s['overdue_tasks']} task(s) are overdue across {sum(1 for r in data['projects'] if r['overdue_task_count'])} project(s).")
    if s["overdue_projects"]:
        lines.append(f"{s['overdue_projects']} project(s) are past their expected completion date.")
    if s["projects_missing_updates"]:
        lines.append(f"{s['projects_missing_updates']} active project(s) are missing recent progress updates.")
    if data.get("financial"):
        for cur, v in data["financial"]["totals_by_currency"].items():
            lines.append(f"Receivables ({cur}): contract value X {v['contract_value']}, verified received Y {v['verified_received']}, "
                         f"outstanding Z {v['outstanding']}" + (f", credit {v['credit']}" if Decimal(v["credit"]) > 0 else "")
                         + (f"; overdue expected payments {v['overdue_pending']}" if Decimal(v["overdue_pending"]) > 0 else "") + ".")
        if s.get("late_supplier_deliveries"):
            lines.append(f"{s['late_supplier_deliveries']} supplier deliver{'y is' if s['late_supplier_deliveries'] == 1 else 'ies are'} late.")
    if s["data_issues"]:
        lines.append(f"{s['data_issues']} data quality issue(s) flagged for review.")
    return lines
