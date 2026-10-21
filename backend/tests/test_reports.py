import datetime as dt
from types import SimpleNamespace

import pytest

from app import ai
from app.config import get_settings
from conftest import approve_quotation, pay


@pytest.fixture
def report_project(pm, member, users, project):
    approve_quotation(pm, project["id"], total="100000.00")
    p = pay(pm, project["id"], "40000.00", ref="T1").json()["payment"]
    pm.post(f"/api/payments/{p['id']}/status", json={"status": "verified"})
    pm.post("/api/tasks", json={"title": "Late item", "project_id": project["id"], "assignee_id": users["member"].id,
                                "due_date": str(dt.date.today() - dt.timedelta(days=2))})
    member.post("/api/updates", json={"project_id": project["id"], "work_completed": "Erection 40% done", "progress": 40})
    return project


def test_report_without_ai_uses_template_fallback(pm, report_project):
    r = pm.post("/api/reports", json={"period_type": "weekly", "scope": "company", "use_ai": True})
    assert r.status_code == 201, r.text
    rep = r.json()
    assert rep["ai_status"] == "not_configured" and rep["ai_analysis"] is None
    data = rep["data"]
    assert data["summary"]["overdue_tasks"] == 1 and data["summary"]["updates_in_period"] == 1
    assert any("Receivables (INR)" in line and "outstanding Z 60000.00" in line for line in data["template_summary"])
    proj = data["projects"][0]
    assert proj["planned_progress_note"].startswith("Linear estimate")
    assert any("overdue" in a for a in proj["next_actions"])
    assert pm.post(f"/api/reports/{rep['id']}/ai").status_code == 503


@pytest.mark.parametrize("period", ["weekly", "monthly", "quarterly", "annual"])
def test_report_periods(pm, report_project, period):
    r = pm.post("/api/reports", json={"period_type": period, "scope": "project", "project_id": report_project["id"]})
    assert r.status_code == 201
    d = r.json()
    assert d["period_start"] <= str(dt.date.today()) <= d["period_end"]


def test_custom_period_validation(pm, report_project):
    today = dt.date.today()
    assert pm.post("/api/reports", json={"period_type": "custom"}).status_code == 422
    bad = pm.post("/api/reports", json={"period_type": "custom", "start_date": str(today), "end_date": str(today - dt.timedelta(days=1))})
    assert bad.status_code == 422
    ok = pm.post("/api/reports", json={"period_type": "custom", "start_date": str(today - dt.timedelta(days=10)), "end_date": str(today)})
    assert ok.status_code == 201


def test_ai_failure_falls_back(pm, report_project, monkeypatch):
    monkeypatch.setattr(get_settings(), "anthropic_api_key", "test-key")

    def boom(_):
        raise ai.AIUnavailable("Could not reach the AI provider")

    monkeypatch.setattr(ai, "analyze", boom)
    rep = pm.post("/api/reports", json={"period_type": "weekly"}).json()
    assert rep["ai_status"] == "failed" and "reach" in rep["ai_error"]
    assert rep["data"]["template_summary"]  # deterministic summary still present


def test_ai_success_is_stored_separately(pm, report_project, monkeypatch):
    monkeypatch.setattr(get_settings(), "anthropic_api_key", "test-key")
    fake = {"overall_health": "at_risk", "summary": "One overdue task.", "confirmed_facts": ["1 task overdue"],
            "estimates": ["Completion likely slips ~1 week (based on overdue task)"], "risks": [], "data_issues": [],
            "recommendations": ["Re-plan the overdue task"], "project_notes": [], "model": "test-model"}
    monkeypatch.setattr(ai, "analyze", lambda data: fake)
    rep = pm.post("/api/reports", json={"period_type": "weekly"}).json()
    assert rep["ai_status"] == "success"
    assert rep["ai_analysis"]["confirmed_facts"] == ["1 task overdue"]
    assert rep["ai_analysis"]["estimates"] and rep["ai_analysis"]["recommendations"]


def test_ai_client_errors_become_unavailable(monkeypatch):
    import anthropic
    import httpx

    monkeypatch.setattr(get_settings(), "anthropic_api_key", "test-key")

    class FakeMessages:
        def parse(self, **kw):
            assert kw["model"] == get_settings().ai_model
            raise anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"))

    monkeypatch.setattr(anthropic, "Anthropic", lambda **kw: SimpleNamespace(messages=FakeMessages()))
    with pytest.raises(ai.AIUnavailable):
        ai.analyze({"summary": {}})


def test_ai_refusal_becomes_unavailable(monkeypatch):
    import anthropic

    monkeypatch.setattr(get_settings(), "anthropic_api_key", "test-key")
    resp = SimpleNamespace(stop_reason="refusal", parsed_output=None)
    monkeypatch.setattr(anthropic, "Anthropic", lambda **kw: SimpleNamespace(messages=SimpleNamespace(parse=lambda **k: resp)))
    with pytest.raises(ai.AIUnavailable):
        ai.analyze({})


def test_report_exports(pm, report_project):
    rid = pm.post("/api/reports", json={"period_type": "monthly"}).json()["id"]
    pdf = pm.get(f"/api/reports/{rid}/export", params={"format": "pdf"})
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
    xlsx = pm.get(f"/api/reports/{rid}/export", params={"format": "xlsx"})
    assert xlsx.status_code == 200 and xlsx.content[:2] == b"PK"


def test_member_report_excludes_finance(member, report_project):
    rep = member.post("/api/reports", json={"period_type": "weekly", "scope": "project", "project_id": report_project["id"]}).json()
    assert rep["data"]["finance_included"] is False
    assert "receivable" not in rep["data"]["projects"][0] and "financial" not in rep["data"]
