from conftest import PASSWORD, Api


def test_login_success_and_me(admin):
    r = admin.get("/api/auth/me")
    assert r.status_code == 200
    body = r.json()
    assert body["user"]["role"] == "admin"
    assert body["permissions"] == {"finance": True, "manage_projects": True, "admin": True}
    assert "password_hash" not in str(body)
    assert body["integrations"]["ai"] is False  # no key configured in tests


def test_login_wrong_password_is_generic(users, anon):
    r = anon.login("admin", "wrong-password1")
    assert r.status_code == 401
    assert "password" in r.json()["error"]["message"].lower() or "invalid" in r.json()["error"]["message"].lower()
    r2 = anon.login("nobody@test.local", "wrong-password1")
    assert r2.status_code == 401
    assert r.json()["error"]["message"] == r2.json()["error"]["message"]  # no user enumeration


def test_account_lockout_after_repeated_failures(users, anon):
    for _ in range(5):
        anon.login("member", "bad-password1")
    r = anon.login("member", PASSWORD)
    assert r.status_code in (401, 423, 429)
    assert r.status_code != 200


def test_unauthenticated_requests_rejected(anon, users):
    for url in ("/api/projects", "/api/dashboard", "/api/payments", "/api/documents", "/api/auth/me"):
        assert anon.get(url).status_code == 401, url


def test_csrf_required_for_unsafe_methods(pm):
    r = pm.c.post("/api/clients", json={"name": "X", "company_name": "No CSRF Ltd"})  # raw client, no header
    assert r.status_code == 403
    r = pm.post("/api/clients", json={"name": "X", "company_name": "With CSRF Ltd"})
    assert r.status_code == 201


def test_logout_revokes_session(member):
    cookie = member.c.cookies.get("pipl_session")
    assert member.post("/api/auth/logout").status_code == 200
    replay = Api()
    replay.c.cookies.set("pipl_session", cookie)
    assert replay.get("/api/auth/me").status_code == 401


def test_change_password(member):
    r = member.post("/api/auth/change-password", json={"current_password": "wrong", "new_password": "NewPassw0rd"})
    assert r.status_code in (400, 401, 422)
    r = member.post("/api/auth/change-password", json={"current_password": PASSWORD, "new_password": "short"})
    assert r.status_code == 422
    r = member.post("/api/auth/change-password", json={"current_password": PASSWORD, "new_password": "NewPassw0rd"})
    assert r.status_code == 200
    assert Api().login("member", "NewPassw0rd").status_code == 200


def test_security_headers(admin):
    r = admin.get("/api/health")
    assert r.headers.get("x-content-type-options") == "nosniff"
    assert "x-request-id" in r.headers
