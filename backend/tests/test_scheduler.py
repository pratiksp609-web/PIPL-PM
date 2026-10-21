import datetime as dt
from types import SimpleNamespace

from app import models as m
from app.scheduler import reminder_slot, run_all_checks

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


def _s(**kw):
    base = dict(reminders_enabled=True, reminder_interval_minutes=120, work_start=dt.time(9, 0), work_end=dt.time(18, 0),
                work_days="0,1,2,3,4,5", timezone="Asia/Kolkata", last_progress_reminder_at=None)
    base.update(kw)
    return SimpleNamespace(**base)


def at(y, mo, d, h, mi=0):
    return dt.datetime(y, mo, d, h, mi, tzinfo=IST).astimezone(dt.timezone.utc)


def test_reminder_slots_follow_working_hours():
    # 2026-10-21 is a Wednesday
    assert reminder_slot(_s(), at(2026, 10, 21, 9, 30)) is None          # first interval not yet elapsed
    assert reminder_slot(_s(), at(2026, 10, 21, 11, 5)) == "progress:2026-10-21:120:1"
    assert reminder_slot(_s(), at(2026, 10, 21, 13, 0)) == "progress:2026-10-21:120:2"
    assert reminder_slot(_s(), at(2026, 10, 21, 8, 0)) is None           # before work
    assert reminder_slot(_s(), at(2026, 10, 21, 18, 30)) is None         # after work
    assert reminder_slot(_s(), at(2026, 10, 25, 11, 0)) is None          # Sunday not a work day
    assert reminder_slot(_s(reminders_enabled=False), at(2026, 10, 21, 11, 0)) is None


def test_reminder_interval_is_configurable_and_not_repeated():
    s = _s(reminder_interval_minutes=60)
    assert reminder_slot(s, at(2026, 10, 21, 10, 1)) == "progress:2026-10-21:60:1"
    s.last_progress_reminder_at = at(2026, 10, 21, 10, 1)
    assert reminder_slot(s, at(2026, 10, 21, 10, 30)) is None


def _make_task(db, user, project_id=None, **kw):
    t = m.Task(title=kw.pop("title", "Open task"), assignee_id=user.id, created_by_id=user.id, project_id=project_id, **kw)
    db.add(t)
    db.commit()
    return t


def _set_hours_covering_now(db, user):
    from app.notify import user_settings

    s = user_settings(db, user.id)
    s.work_start, s.work_end = dt.time(0, 0), dt.time(23, 59)
    s.work_days = "0,1,2,3,4,5,6"
    s.reminder_interval_minutes = 15
    s.timezone = "UTC"
    db.commit()


def test_progress_reminders_are_deduplicated_and_skip_users_without_tasks(db, users, monkeypatch):
    now = dt.datetime.now(dt.timezone.utc)
    if now.hour == 0 and now.minute < 20:
        now = now.replace(hour=1)
    monkeypatch.setattr("app.scheduler.dt.datetime", type("FakeDT", (dt.datetime,), {"now": classmethod(lambda cls, tz=None: now)}))
    for key in ("member", "other"):
        _set_hours_covering_now(db, users[key])
    _make_task(db, users["member"])
    run_all_checks()
    run_all_checks()  # a second run in the same slot must not duplicate
    db.expire_all()
    rows = db.query(m.Notification).filter_by(type="progress_reminder").all()
    assert len(rows) == 1 and rows[0].user_id == users["member"].id
    assert rows[0].email_status in ("not_requested", "not_configured")  # SMTP is not configured in tests


def test_overdue_and_deadline_alerts(db, users, pm, project):
    today = dt.date.today()
    _make_task(db, users["member"], project["id"], title="Late weld", due_date=today - dt.timedelta(days=1))
    _make_task(db, users["member"], project["id"], title="Soon", due_date=today + dt.timedelta(days=1))
    res = run_all_checks()
    assert not res.get("skipped")
    types = {n.type for n in db.query(m.Notification).filter_by(user_id=users["member"].id)}
    assert {"task_overdue", "task_due_soon"} <= types
    before = db.query(m.Notification).count()
    run_all_checks()
    assert db.query(m.Notification).count() == before  # same-day alerts are not repeated


def test_disabled_rule_produces_no_alert(db, users, admin, project):
    assert admin.put("/api/settings/system/rules", json={"enabled_rules": ["project_deadline"]}).status_code == 200
    _make_task(db, users["member"], project["id"], title="Late", due_date=dt.date.today() - dt.timedelta(days=3))
    run_all_checks()
    assert db.query(m.Notification).filter_by(type="task_overdue").count() == 0


def test_user_settings_validation(member):
    assert member.put("/api/settings/me", json={"reminder_interval_minutes": 5}).status_code == 422
    assert member.put("/api/settings/me", json={"work_start": "18:00", "work_end": "09:00"}).status_code == 422
    assert member.put("/api/settings/me", json={"timezone": "Mars/Base"}).status_code == 422
    r = member.put("/api/settings/me", json={"reminder_interval_minutes": 60, "work_days": [0, 1, 2, 3, 4]})
    assert r.status_code == 200 and r.json()["reminder_interval_minutes"] == 60
