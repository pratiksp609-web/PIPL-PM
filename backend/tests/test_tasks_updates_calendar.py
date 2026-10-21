import datetime as dt


def test_task_lifecycle_and_completion_rules(pm, member, users, project):
    r = pm.post("/api/tasks", json={"title": "Install pumps", "project_id": project["id"], "assignee_id": users["member"].id,
                                    "priority": "high", "due_date": str(dt.date.today() + dt.timedelta(days=3))})
    assert r.status_code == 201
    t = r.json()
    notes = member.get("/api/notifications").json()["items"]
    assert any(n["type"] == "task_assigned" for n in notes)
    r = member.patch(f"/api/tasks/{t['id']}", json={"progress": 100})
    assert r.json()["status"] == "completed" and r.json()["completed_at"]
    r = member.patch(f"/api/tasks/{t['id']}", json={"status": "in_progress"})
    assert r.json()["progress"] < 100 and r.json()["completed_at"] is None


def test_team_member_task_restrictions(pm, member, users, project):
    t = pm.post("/api/tasks", json={"title": "Weld frame", "project_id": project["id"], "assignee_id": users["member"].id}).json()
    assert member.patch(f"/api/tasks/{t['id']}", json={"title": "Renamed"}).status_code == 403
    assert member.patch(f"/api/tasks/{t['id']}", json={"status": "in_progress", "progress": 40}).status_code == 200
    assert member.delete(f"/api/tasks/{t['id']}").status_code == 403
    other = pm.post("/api/tasks", json={"title": "PM only", "project_id": project["id"], "assignee_id": users["pm"].id}).json()
    assert member.patch(f"/api/tasks/{other['id']}", json={"progress": 10}).status_code == 403
    r = member.post("/api/tasks", json={"title": "Mine", "project_id": project["id"], "assignee_id": users["pm"].id})
    assert r.status_code == 403


def test_task_validation_and_overdue_filter(pm, project):
    today = dt.date.today()
    bad = pm.post("/api/tasks", json={"title": "x", "start_date": str(today), "due_date": str(today - dt.timedelta(days=1))})
    assert bad.status_code == 422
    pm.post("/api/tasks", json={"title": "Late", "project_id": project["id"], "due_date": str(today - dt.timedelta(days=2))})
    pm.post("/api/tasks", json={"title": "Fine", "project_id": project["id"], "due_date": str(today + dt.timedelta(days=2))})
    items = pm.get("/api/tasks", params={"overdue": True}).json()["items"]
    assert [i["title"] for i in items] == ["Late"] and items[0]["is_overdue"]


def test_update_edit_keeps_revision_history(pm, member, project):
    r = member.post("/api/updates", json={"project_id": project["id"], "work_completed": "Foundation poured", "progress": 30,
                                          "blockers": "Cement shortage"})
    assert r.status_code == 201
    u = r.json()
    assert u["author_name"] == "Member User" and u["update_at"]
    assert pm.get(f"/api/projects/{project['id']}").json()["project"]["progress"] == 30
    assert member.patch(f"/api/updates/{u['id']}", json={"progress": 35}).status_code == 422  # reason is mandatory
    r = member.patch(f"/api/updates/{u['id']}", json={"progress": 35, "reason": "Miscounted bays"})
    assert r.status_code == 200
    detail = pm.get(f"/api/updates/{u['id']}").json()
    assert detail["update"]["progress"] == 35
    assert detail["revisions"][0]["snapshot"]["progress"] == 30
    assert detail["revisions"][0]["reason"] == "Miscounted bays"


def test_update_cannot_be_in_future(member, project):
    future = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1)).isoformat()
    r = member.post("/api/updates", json={"project_id": project["id"], "work_completed": "x", "progress": 5, "update_at": future})
    assert r.status_code == 422


def test_calendar_range_limits_and_events(pm, project):
    today = dt.date.today()
    ok = pm.get("/api/calendar", params={"start": str(today.replace(day=1)), "end": str(today.replace(day=28))})
    assert ok.status_code == 200
    far = today.replace(year=today.year + 51)
    assert pm.get("/api/calendar", params={"start": str(far), "end": str(far)}).status_code == 422
    assert pm.get("/api/calendar", params={"start": str(today), "end": str(today + dt.timedelta(days=500))}).status_code == 422
    start = dt.datetime.now(dt.timezone.utc).replace(microsecond=0) + dt.timedelta(days=1)
    naive = pm.post("/api/calendar/events", json={"title": "Naive", "start_at": start.replace(tzinfo=None).isoformat()})
    assert naive.status_code == 422
    r = pm.post("/api/calendar/events", json={"title": "Kick-off", "event_type": "meeting", "start_at": start.isoformat(),
                                              "end_at": (start + dt.timedelta(hours=1)).isoformat(), "project_id": project["id"]})
    assert r.status_code == 201
    feed = pm.get("/api/calendar", params={"start": str(today), "end": str(today + dt.timedelta(days=90))}).json()["items"]
    cats = {i["category"] for i in feed}
    assert "meeting" in cats and "project_deadline" in cats
    eid = r.json()["source_id"]
    bad = pm.patch(f"/api/calendar/events/{eid}", json={"end_at": (start - dt.timedelta(hours=2)).isoformat()})
    assert bad.status_code == 422
    assert pm.delete(f"/api/calendar/events/{eid}").status_code == 200


def test_member_calendar_hides_finance_categories(member, pm, project):
    today = dt.date.today()
    feed = member.get("/api/calendar", params={"start": str(today), "end": str(today + dt.timedelta(days=90)),
                                               "categories": "payment_due,quotation_expiry,task_due"}).json()["items"]
    assert all(i["category"] not in ("payment_due", "quotation_expiry", "supplier_delivery") for i in feed)
