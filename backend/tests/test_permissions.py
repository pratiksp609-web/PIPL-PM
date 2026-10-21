import datetime as dt


def test_team_member_cannot_manage_projects_or_clients(member, project):
    assert member.post("/api/clients", json={"name": "A", "company_name": "B Ltd"}).status_code == 403
    assert member.post("/api/projects", json={"name": "X", "client_id": project["client_id"]}).status_code == 403
    assert member.patch(f"/api/projects/{project['id']}", json={"name": "Hacked"}).status_code == 403


def test_team_member_has_no_finance_access(member, project):
    for url in ("/api/payments", "/api/payments/summary", f"/api/projects/{project['id']}/payments", "/api/client-pos",
                "/api/quotations", "/api/supplier-pos", "/api/procurement/summary"):
        assert member.get(url).status_code == 403, url
    p = member.get(f"/api/projects/{project['id']}").json()
    assert p["project"]["contract_value"] is None and p["project"]["budget"] is None
    assert "receivable" not in p
    d = member.get("/api/dashboard").json()
    assert d.get("finance") in (None, {}) or "outstanding" not in str(d.get("finance"))


def test_team_member_only_sees_assigned_projects(pm, member, users, project):
    other = pm.post("/api/projects", json={"name": "Secret", "client_id": project["client_id"]}).json()
    ids = [p["id"] for p in member.get("/api/projects").json()["items"]]
    assert project["id"] in ids and other["id"] not in ids
    assert member.get(f"/api/projects/{other['id']}").status_code == 404


def test_only_admin_manages_users(pm, admin):
    body = {"email": "new.person@example.com", "username": "newbie", "full_name": "New Person", "role": "team_member", "password": "Passw0rd1"}
    assert pm.post("/api/users", json=body).status_code == 403
    r = admin.post("/api/users", json=body)
    assert r.status_code == 201
    assert "password_hash" not in r.json()
    assert admin.post("/api/users", json=body).status_code == 409


def test_admin_cannot_lock_themselves_out(admin, users):
    r = admin.patch(f"/api/users/{users['admin'].id}", json={"role": "team_member"})
    assert r.status_code == 422


def test_audit_log_restricted(member, pm, project):
    assert member.get("/api/audit-logs").status_code == 403
    logs = pm.get("/api/audit-logs", params={"entity_type": "project"}).json()["items"]
    assert any(l["action"] == "create" for l in logs)


def test_deactivated_user_sessions_revoked(admin, member, users):
    assert admin.patch(f"/api/users/{users['member'].id}", json={"is_active": False}).status_code == 200
    assert member.get("/api/auth/me").status_code == 401
