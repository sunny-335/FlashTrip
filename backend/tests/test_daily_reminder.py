"""旅行中每日早晨天气邮件：触发时机、在途行程筛选、同行程同天去重。

全部外部依赖（天气、SMTP、AI）均 mock，不发真实邮件、不联网。
"""
from __future__ import annotations

from datetime import date, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.mail import MailLog
from app.models.trip import Trip
from app.services import backup_service as bs
from app.services import mail_service, weather_service

TARGET = datetime(2026, 11, 23, 7, 30)

_TRIPS = [
    {"trip_id": "trip-1", "title": "苏州三日游", "destination": "苏州",
     "start_date": "2026-11-22", "end_date": "2026-11-25"},
    {"trip_id": "trip-2", "title": "杭州两日", "destination": "杭州",
     "start_date": "2026-11-23", "end_date": "2026-11-24"},
]

_WEATHER = {
    "current": {"weather": "晴", "temperature": 26.0, "humidity": 60,
                "wind": "东南 3", "report_time": "2026-11-23 07:00", "alerts": []},
    "forecast": [{"date": "2026-11-23", "week": "周一", "weather_day": "晴",
                  "weather_night": "多云", "temp_min": 18.0, "temp_max": 28.0, "pop": 0.1}],
    "advice_hints": ["注意防晒"],
}


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine, tables=[MailLog.__table__, Trip.__table__])
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    yield session
    session.close()
    engine.dispose()


def _patch(monkeypatch, *, trips=None, enabled=True, time="07:30", mail_enabled=True):
    monkeypatch.setattr(weather_service, "get_daily_reminder_config",
                        lambda: {"enabled": enabled, "time": time})
    monkeypatch.setattr(mail_service, "get_mail_config", lambda: {"enabled": mail_enabled})
    monkeypatch.setattr(weather_service, "check_active_trips",
                        lambda session, today=None: list(_TRIPS if trips is None else trips))
    monkeypatch.setattr(weather_service, "fetch_weather", lambda city, **kwargs: _WEATHER)


def _record_send(monkeypatch):
    """把 send_weather_advice 换成写 MailLog 的假实现，模拟一次成功投递。"""
    sent_trips: list[str] = []

    def fake_send(session, trip, *, advice, weather=None, template="", subject=None):
        sent_trips.append(trip["trip_id"])
        session.add(MailLog(
            to_addr="member@example.com", subject=subject or "提醒",
            template=template or mail_service.DAILY_TEMPLATE,
            status="sent", trip_id=trip.get("trip_id"),
        ))
        session.commit()
        return {"sent": 1, "failed": 0}

    monkeypatch.setattr(mail_service, "send_weather_advice", fake_send)
    return sent_trips


def test_daily_reminder_sends_active_and_skips_already_sent(monkeypatch, db):
    _patch(monkeypatch)
    # trip-2 今天已发过，应被去重跳过
    db.add(MailLog(
        to_addr="x@example.com", subject="【今日出行】2026-11-23 · 杭州两日 · 天气与建议",
        template=mail_service.DAILY_TEMPLATE, status="sent", trip_id="trip-2",
    ))
    db.commit()
    sent_trips = _record_send(monkeypatch)

    result = bs.run_daily_weather_reminders(now=TARGET, db=db)
    assert result["enabled"] is True and result["fired"] is True
    assert result["sent"] == 1 and result["skipped"] == 1
    assert sent_trips == ["trip-1"]


def test_daily_reminder_not_repeated_same_day(monkeypatch, db):
    _patch(monkeypatch)
    sent_trips = _record_send(monkeypatch)

    first = bs.run_daily_weather_reminders(now=TARGET, db=db)
    assert first["sent"] == 2 and first["skipped"] == 0
    assert sorted(sent_trips) == ["trip-1", "trip-2"]

    second = bs.run_daily_weather_reminders(now=TARGET, db=db)
    assert second["sent"] == 0 and second["skipped"] == 2
    assert sorted(sent_trips) == ["trip-1", "trip-2"], "同一天不得重复发送"


def test_daily_reminder_respects_configured_time(monkeypatch, db):
    _patch(monkeypatch)
    sent_trips = _record_send(monkeypatch)
    result = bs.run_daily_weather_reminders(now=datetime(2026, 11, 23, 8, 5), db=db)
    assert result["fired"] is False and result["sent"] == 0
    assert sent_trips == []


def test_daily_reminder_disabled(monkeypatch, db):
    _patch(monkeypatch, enabled=False)
    result = bs.run_daily_weather_reminders(now=TARGET, db=db)
    assert result["enabled"] is False and result["fired"] is False


def test_daily_reminder_skips_when_mail_disabled(monkeypatch, db):
    _patch(monkeypatch, mail_enabled=False)
    result = bs.run_daily_weather_reminders(now=TARGET, db=db)
    assert result["fired"] is False and result["sent"] == 0


def test_check_active_trips_window_and_status(db):
    today = date(2026, 11, 23)
    db.add(Trip(owner_id="u", title="在途", start_date=date(2026, 11, 22),
                end_date=date(2026, 11, 25), status="planned"))
    db.add(Trip(owner_id="u", title="未开始", start_date=date(2026, 11, 24),
                end_date=date(2026, 11, 26), status="planned"))
    db.add(Trip(owner_id="u", title="已结束", start_date=date(2026, 11, 20),
                end_date=date(2026, 11, 22), status="planned"))
    db.add(Trip(owner_id="u", title="已归档", start_date=date(2026, 11, 22),
                end_date=date(2026, 11, 25), status="archived"))
    db.commit()

    out = weather_service.check_active_trips(db, today=today)
    assert {trip["title"] for trip in out} == {"在途"}
