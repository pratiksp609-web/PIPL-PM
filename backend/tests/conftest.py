"""Test fixtures. Tests run against a dedicated PostgreSQL database (TEST_DATABASE_URL, default pipl_test).

The schema is built with the real Alembic migrations once per session, and every table except `roles`
is truncated between tests so each test starts from an empty database.
"""
import os
import tempfile

TEST_DB = os.environ.get("TEST_DATABASE_URL", "postgresql+psycopg://pipl:pipl@localhost:5432/pipl_test")
os.environ.update(
    APP_ENV="test",
    DATABASE_URL=TEST_DB,
    SECRET_KEY="test-secret-key-not-for-production-0123456789",
    UPLOAD_DIR=tempfile.mkdtemp(prefix="pipl-test-uploads-"),
    LOGIN_RATE_LIMIT_PER_MINUTE="100000",
    API_RATE_LIMIT_PER_MINUTE="1000000",
    ANTHROPIC_API_KEY="",
    SMTP_HOST="",
    SCHEDULER_ENABLED="false",
)

import datetime as dt  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app import models as m  # noqa: E402
from app.db import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.security import hash_password, limiter  # noqa: E402

PASSWORD = "Passw0rd!"
BACKEND = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session", autouse=True)
def _schema():
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    command.upgrade(cfg, "head")
    yield


@pytest.fixture(autouse=True)
def _clean():
    yield
    with engine.begin() as conn:
        tables = [r[0] for r in conn.execute(text(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename NOT IN ('roles','alembic_version')"))]
        conn.execute(text(f"TRUNCATE {', '.join(tables)} RESTART IDENTITY CASCADE"))
    limiter.reset()


@pytest.fixture
def db():
    s = SessionLocal()
    yield s
    s.close()


class Api:
    """Wraps TestClient: keeps the session cookie and sends the CSRF header on unsafe methods."""

    def __init__(self):
        self.c = TestClient(app)

    def _h(self, kw):
        h = kw.pop("headers", {}) or {}
        token = self.c.cookies.get("pipl_csrf")
        if token:
            h["X-CSRF-Token"] = token
        return h

    def login(self, identifier, password=PASSWORD):
        return self.c.post("/api/auth/login", json={"identifier": identifier, "password": password})

    def get(self, url, **kw):
        return self.c.get(url, **kw)

    def post(self, url, **kw):
        return self.c.post(url, headers=self._h(kw), **kw)

    def patch(self, url, **kw):
        return self.c.patch(url, headers=self._h(kw), **kw)

    def put(self, url, **kw):
        return self.c.put(url, headers=self._h(kw), **kw)

    def delete(self, url, **kw):
        return self.c.delete(url, headers=self._h(kw), **kw)


_HASH = None


@pytest.fixture
def users(db):
    global _HASH
    _HASH = _HASH or hash_password(PASSWORD)  # bcrypt is deliberately slow; hash once per session
    out = {}
    for key, role in (("admin", "admin"), ("pm", "project_manager"), ("member", "team_member"), ("other", "team_member")):
        u = m.User(email=f"{key}@test.local", username=key, full_name=f"{key.title()} User", role=role,
                   password_hash=_HASH)
        db.add(u)
        out[key] = u
    db.commit()
    return out


def _logged_in(identifier):
    api = Api()
    r = api.login(identifier)
    assert r.status_code == 200, r.text
    return api


@pytest.fixture
def admin(users):
    return _logged_in("admin")


@pytest.fixture
def pm(users):
    return _logged_in("pm")


@pytest.fixture
def member(users):
    return _logged_in("member")


@pytest.fixture
def anon():
    return Api()


@pytest.fixture
def project(pm, users):
    """A client plus an active project managed by `pm`, with `member` on the team."""
    c = pm.post("/api/clients", json={"name": "Ravi Kumar", "company_name": "Acme Process Ltd"})
    assert c.status_code == 201, c.text
    today = dt.date.today()
    p = pm.post("/api/projects", json={
        "name": "Test Plant", "client_id": c.json()["id"], "manager_id": users["pm"].id, "status": "active",
        "start_date": str(today - dt.timedelta(days=30)), "expected_completion_date": str(today + dt.timedelta(days=60)),
        "member_ids": [users["member"].id],
    })
    assert p.status_code == 201, p.text
    return p.json()


def approve_quotation(api, project_id, total="100000.00", subtotal=None, tax=None, number="Q-1"):
    """Create and approve a quotation so the project has an approved contract value."""
    body = {"project_id": project_id, "quotation_number": number, "total_amount": total, "currency": "INR",
            "quotation_date": str(dt.date.today())}
    if subtotal is not None:
        body.update(subtotal=subtotal, tax_amount=tax)
    r = api.post("/api/quotations", json=body)
    assert r.status_code == 201, r.text
    vid = r.json()["latest"]["id"]
    r = api.post(f"/api/quotation-versions/{vid}/status", json={"status": "approved"})
    assert r.status_code == 200, r.text
    return r.json()


def pay(api, project_id, amount, ref=None, status="recorded", **extra):
    body = {"project_id": project_id, "amount": amount, "status": status, "payment_type": "partial", **extra}
    if status == "recorded":
        body.setdefault("payment_date", str(dt.date.today()))
    else:
        body.setdefault("due_date", str(dt.date.today() + dt.timedelta(days=10)))
    if ref:
        body["transaction_reference"] = ref
    return api.post("/api/payments", json=body)


def receivable(api, project_id):
    r = api.get(f"/api/projects/{project_id}/payments")
    assert r.status_code == 200, r.text
    return r.json()["receivable"]


# A minimal valid PDF with a text layer, used for upload tests.
def make_pdf(text_lines: list[str]) -> bytes:
    from io import BytesIO

    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    y = 800
    for line in text_lines:
        c.drawString(50, y, line)
        y -= 18
    c.save()
    return buf.getvalue()
