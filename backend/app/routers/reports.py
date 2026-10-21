import datetime as dt
import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import ai
from .. import models as m
from ..config import get_settings
from ..core import APIError, audit, bad_request, can_view_finance, get_project_or_404, not_found, page_response, paginate
from ..db import get_db
from ..exports import report_pdf, xlsx_bytes
from ..notify import get_rules
from ..reports import build_report, resolve_period
from ..schemas import ReportRequest
from ..security import get_current_user

router = APIRouter(prefix="/api/reports", tags=["reports"])
settings = get_settings()


def report_out(r: m.GeneratedReport, full: bool = True) -> dict:
    d = {"id": r.id, "title": r.title, "period_type": r.period_type, "scope": r.scope, "project_id": r.project_id,
         "period_start": r.period_start, "period_end": r.period_end, "filters": r.filters, "ai_status": r.ai_status,
         "ai_error": r.ai_error, "created_at": r.created_at, "generated_by_id": r.generated_by_id}
    if full:
        d["data"] = r.data
        d["ai_analysis"] = r.ai_analysis
    return d


def _run_ai(r: m.GeneratedReport) -> None:
    try:
        r.ai_analysis = ai.analyze(r.data)
        r.ai_status = "success"
        r.ai_error = None
    except ai.AIUnavailable as exc:
        r.ai_status = "not_configured" if not settings.ai_enabled else "failed"
        r.ai_error = str(exc)[:500]
        r.ai_analysis = None


def _get(db: Session, user: m.User, report_id: int) -> m.GeneratedReport:
    r = db.get(m.GeneratedReport, report_id)
    if not r:
        raise not_found("Report")
    if r.project_id:
        get_project_or_404(db, user, r.project_id)
    if r.data.get("finance_included") and not can_view_finance(user):
        raise not_found("Report")
    if r.scope == "company" and r.generated_by_id != user.id and user.role == "team_member":
        raise not_found("Report")
    return r


@router.post("", status_code=201)
def generate(body: ReportRequest, request: Request, db: Session = Depends(get_db), user: m.User = Depends(get_current_user)):
    if body.project_id:
        get_project_or_404(db, user, body.project_id)
    start, end = resolve_period(body.period_type, body.start_date, body.end_date)
    if (end - start).days > 3660:
        raise bad_request("Report period cannot exceed 10 years")
    data = build_report(db, user, period_type=body.period_type, start=start, end=end, scope=body.scope, project_id=body.project_id,
                        client_id=body.client_id, manager_id=body.manager_id, status=body.status,
                        missing_update_days=get_rules(db)["missing_update_days"])
    if body.scope == "project" and not data["projects"]:
        raise bad_request("The selected project is archived or not visible")
    label = {"weekly": "Weekly", "monthly": "Monthly", "quarterly": "Quarterly", "annual": "Annual", "custom": "Custom"}[body.period_type]
    subject = f"{data['projects'][0]['code']} {data['projects'][0]['name']}" if body.scope == "project" else "Company"
    r = m.GeneratedReport(
        title=f"{label} status report · {subject} · {start:%d %b %Y} – {end:%d %b %Y}", period_type=body.period_type, scope=body.scope,
        project_id=body.project_id if body.scope == "project" else None, period_start=start, period_end=end,
        filters=json.loads(body.model_dump_json(exclude={"use_ai"})), data=json.loads(json.dumps(data, default=str)),
        generated_by_id=user.id, ai_status="skipped",
    )
    if body.use_ai:
        _run_ai(r)
    db.add(r)
    db.flush()
    audit(db, user, "generate", "report", r.id, r.project_id, changes={"period": [str(start), str(end)], "ai_status": r.ai_status}, request=request)
    db.commit()
    return report_out(r)


@router.get("")
def list_reports(project_id: int | None = None, period_type: str | None = None, scope: str | None = None, page: int = 1,
                 page_size: int = 20, db: Session = Depends(get_db), user: m.User = Depends(get_current_user)):
    stmt = select(m.GeneratedReport)
    if user.role == "team_member":
        stmt = stmt.where(m.GeneratedReport.generated_by_id == user.id)
    if project_id:
        stmt = stmt.where(m.GeneratedReport.project_id == project_id)
    if period_type:
        stmt = stmt.where(m.GeneratedReport.period_type == period_type)
    if scope:
        stmt = stmt.where(m.GeneratedReport.scope == scope)
    rows, total = paginate(db, stmt.order_by(m.GeneratedReport.created_at.desc()), page, page_size)
    return page_response([report_out(r, full=False) for r in rows], total, page, page_size)


@router.get("/ai-status")
def ai_status(user: m.User = Depends(get_current_user)):
    return {"configured": settings.ai_enabled, "model": settings.ai_model if settings.ai_enabled else None,
            "message": None if settings.ai_enabled else
            "AI analysis is unavailable because no AI provider is configured. Reports use deterministic, template-based analysis."}


@router.get("/{report_id}")
def get_report(report_id: int, db: Session = Depends(get_db), user: m.User = Depends(get_current_user)):
    return report_out(_get(db, user, report_id))


@router.post("/{report_id}/ai")
def rerun_ai(report_id: int, request: Request, db: Session = Depends(get_db), user: m.User = Depends(get_current_user)):
    r = _get(db, user, report_id)
    if not settings.ai_enabled:
        raise APIError(503, "AI analysis is unavailable: no AI provider is configured on the server.", "ai_unavailable")
    _run_ai(r)
    audit(db, user, "ai_analysis", "report", r.id, r.project_id, changes={"ai_status": r.ai_status}, request=request)
    db.commit()
    return report_out(r)


@router.get("/{report_id}/export")
def export_report(report_id: int, format: str = "pdf", db: Session = Depends(get_db), user: m.User = Depends(get_current_user)):
    r = _get(db, user, report_id)
    name = f"pipl-report-{r.id}-{r.period_start}-{r.period_end}"
    if format == "pdf":
        content = report_pdf(report_out(r) | {"created_at": r.created_at.strftime("%Y-%m-%d %H:%M UTC")})
        return StreamingResponse(iter([content]), media_type="application/pdf",
                                 headers={"Content-Disposition": f'attachment; filename="{name}.pdf"'})
    if format != "xlsx":
        raise bad_request("Format must be pdf or xlsx")
    data = r.data
    projects = data["projects"]
    sheets = [
        ("Summary", ["Metric", "Value"], [[k, v] for k, v in data["summary"].items()] + [["Note", line] for line in data["template_summary"]]),
        ("Projects", ["Code", "Name", "Client", "Manager", "Status", "Health", "Progress %", "Planned % (linear est.)", "Expected completion",
                      "Open tasks", "Overdue tasks", "Updates in period", "Days since update"],
         [[p["code"], p["name"], p["client"], p["manager"], p["status"], p["health"], p["progress"], p["planned_progress"],
           p["expected_completion_date"], p["open_task_count"], p["overdue_task_count"], p["update_count"], p["days_since_last_update"]]
          for p in projects]),
        ("Overdue tasks", ["Project", "Task", "Due", "Days overdue", "Assignee"],
         [[p["code"], t["title"], t["due_date"], t["days_overdue"], t["assignee"]] for p in projects for t in p["overdue_tasks"]]),
        ("Data issues", ["Project", "Type", "Issue"], [[p["code"], i["type"], i["text"]] for p in projects for i in p["data_issues"]]),
        ("Next actions", ["Project", "Action"], [[p["code"], a] for p in projects for a in p["next_actions"]]),
    ]
    if data.get("finance_included"):
        sheets.insert(2, ("Receivables", ["Code", "Currency", "X contract value", "Basis", "Y verified received", "Z outstanding", "Credit",
                                          "Recorded unverified", "Expected pending", "Overdue pending"],
                          [[p["code"], p["receivable"]["currency"], float(p["receivable"]["contract_value"]), p["receivable"]["contract_basis"],
                            float(p["receivable"]["verified_received"]), float(p["receivable"]["outstanding"]), float(p["receivable"]["credit"]),
                            float(p["receivable"]["unverified_recorded"]), float(p["receivable"]["expected_pending"]),
                            float(p["receivable"]["overdue_pending"])] for p in projects]))
        sheets.insert(3, ("Procurement", ["Code", "BOM items", "Estimated", "Committed (POs)", "Supplier paid", "Supplier outstanding",
                                          "Pending items", "Late deliveries"],
                          [[p["code"], p["procurement"]["bom_item_count"], float(p["procurement"]["estimated_cost"]),
                            float(p["procurement"]["committed_cost"]), float(p["procurement"]["supplier_paid"]),
                            float(p["procurement"]["supplier_outstanding"]), p["procurement"]["pending_procurement_count"],
                            len(p["procurement"]["late_deliveries"])] for p in projects]))
    if r.ai_status == "success" and r.ai_analysis:
        a = r.ai_analysis
        rows = [["Overall health", a.get("overall_health")], ["Summary", a.get("summary")]]
        for key in ("confirmed_facts", "estimates", "risks", "data_issues", "recommendations"):
            rows += [[key.replace("_", " ").capitalize(), x] for x in a.get(key, [])]
        sheets.append(("AI analysis", ["Section", "Text"], rows))
    content = xlsx_bytes(sheets)
    return StreamingResponse(iter([content]), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition": f'attachment; filename="{name}.xlsx"'})
