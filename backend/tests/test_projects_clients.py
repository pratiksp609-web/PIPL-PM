import datetime as dt
import re


def test_duplicate_client_rejected(pm):
    assert pm.post("/api/clients", json={"name": "A", "company_name": "Delta Engineering"}).status_code == 201
    r = pm.post("/api/clients", json={"name": "B", "company_name": "  delta engineering "})
    assert r.status_code == 409
    assert r.json()["error"]["details"]["existing_client_id"]


def test_client_validation(pm):
    r = pm.post("/api/clients", json={"name": "A", "company_name": "Bad GST Ltd", "gstin": "123"})
    assert r.status_code == 422
    assert pm.post("/api/clients", json={"name": "A", "company_name": "Bad Mail", "email": "nope"}).status_code == 422
    assert pm.post("/api/clients", json={"name": "A", "company_name": "Good GST", "gstin": "27abcde1234f1z5"}).json()["gstin"] == "27ABCDE1234F1Z5"


def test_project_gets_unique_id(pm, project):
    assert re.fullmatch(r"PIPL-\d{4}-\d{4}", project["code"])
    second = pm.post("/api/projects", json={"name": "Second", "client_id": project["client_id"]}).json()
    assert second["code"] != project["code"]


def test_project_date_and_progress_validation(pm, project):
    today = dt.date.today()
    r = pm.post("/api/projects", json={"name": "Bad dates", "client_id": project["client_id"],
                                       "start_date": str(today), "expected_completion_date": str(today - dt.timedelta(days=1))})
    assert r.status_code == 422
    assert pm.post("/api/projects", json={"name": "Bad", "client_id": project["client_id"], "progress": 120}).status_code == 422
    assert pm.post("/api/projects", json={"name": "Bad", "client_id": 999999}).status_code in (404, 422)


def test_archived_project_is_read_only(pm, project):
    assert pm.post(f"/api/projects/{project['id']}/archive", params={"archived": True}).status_code == 200
    r = pm.post("/api/tasks", json={"title": "x", "project_id": project["id"]})
    assert r.status_code == 422
    r = pm.patch(f"/api/projects/{project['id']}", json={"name": "Renamed"})
    assert r.status_code in (409, 422)
    ids = [p["id"] for p in pm.get("/api/projects").json()["items"]]
    assert project["id"] not in ids


def test_global_search(pm, project):
    r = pm.get("/api/search", params={"q": "Test Plant"})
    assert r.status_code == 200
    assert "Test Plant" in str(r.json())
