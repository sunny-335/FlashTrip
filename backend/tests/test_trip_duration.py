"""行程天数联动测试：start+days / end+days / 显式优先 / 缩短预览与确认 / 延长补 day。"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1 import deps
from app.core.errors import ErrorCode
from app.db.base import Base
from app.models.plan import PlanItem, PlanMoveLog
from app.models.trip import Trip, TripDay
from app.models.user import User

_TABLES = [Trip.__table__, TripDay.__table__, PlanItem.__table__, PlanMoveLog.__table__, User.__table__]


@pytest.fixture()
def env(client, monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine, tables=_TABLES)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    db = Session()

    owner = User(
        id="owner-1", username="owner", password_hash="x",
        role="owner", is_active=True, must_set_password=False,
    )
    db.add(owner)
    for trip_id in ("trip-1", "trip-2", "trip-3"):
        db.add(Trip(id=trip_id, owner_id=owner.id, title=trip_id, traveler_count=1))
    db.commit()

    fake_user = SimpleNamespace(id=owner.id, role="owner", must_set_password=False)
    monkeypatch.setitem(client.app.dependency_overrides, deps.require_user, lambda: fake_user)
    monkeypatch.setitem(client.app.dependency_overrides, deps.get_db, lambda: db)
    yield SimpleNamespace(client=client, db=db, owner=owner)
    db.close()
    engine.dispose()


def _put(env, trip_id: str, **body):
    return env.client.put(f"/api/v1/trips/{trip_id}", json=body)


def _day_count(env, trip_id: str) -> int:
    return env.db.query(TripDay).filter(TripDay.trip_id == trip_id).count()


def test_start_plus_duration_computes_end_and_creates_days(env):
    resp = _put(env, "trip-1", start_date="2026-01-01", duration_days=5)
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["start_date"] == "2026-01-01"
    assert data["end_date"] == "2026-01-05"
    assert data["duration_days"] == 5
    assert _day_count(env, "trip-1") == 5

    days = (
        env.db.query(TripDay)
        .filter(TripDay.trip_id == "trip-1")
        .order_by(TripDay.day_index)
        .all()
    )
    assert [d.day_index for d in days] == [1, 2, 3, 4, 5]
    assert days[0].date.isoformat() == "2026-01-01"
    assert days[4].date.isoformat() == "2026-01-05"


def test_end_plus_duration_computes_start(env):
    resp = _put(env, "trip-2", end_date="2026-02-10", duration_days=3)
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["start_date"] == "2026-02-08"
    assert data["end_date"] == "2026-02-10"
    assert data["duration_days"] == 3
    assert _day_count(env, "trip-2") == 3


def test_explicit_dates_win_over_duration(env):
    resp = _put(env, "trip-3", start_date="2026-03-01", end_date="2026-03-02", duration_days=10)
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["start_date"] == "2026-03-01"
    assert data["end_date"] == "2026-03-02"
    assert data["duration_days"] == 2
    assert _day_count(env, "trip-3") == 2


def test_extend_adds_missing_days(env):
    _put(env, "trip-3", start_date="2026-03-01", duration_days=2)
    assert _day_count(env, "trip-3") == 2

    resp = _put(env, "trip-3", start_date="2026-03-01", duration_days=4)
    assert resp.status_code == 200
    assert _day_count(env, "trip-3") == 4
    assert resp.json()["data"]["duration_days"] == 4


def test_shrink_preview_then_confirm_moves_items_to_unplanned(env):
    # 先建成 5 天行程
    _put(env, "trip-1", start_date="2026-01-01", duration_days=5)
    days = (
        env.db.query(TripDay)
        .filter(TripDay.trip_id == "trip-1")
        .order_by(TripDay.day_index)
        .all()
    )
    day4, day5 = days[3], days[4]
    item4 = PlanItem(
        trip_id="trip-1", day_id=day4.id, bucket="day", type="place",
        title="第四天景点", sort_key="a0",
    )
    item5 = PlanItem(
        trip_id="trip-1", day_id=day5.id, bucket="day", type="hotel",
        title="第五天酒店", sort_key="a0",
    )
    env.db.add_all([item4, item5])
    env.db.commit()

    # 未确认：返回预览，不写库
    preview = _put(env, "trip-1", start_date="2026-01-01", duration_days=3)
    assert preview.status_code == 200, preview.text
    body = preview.json()["data"]
    change = body["duration_change"]
    assert change["preview"] is True
    assert change["applied"] is False
    assert change["target_days"] == 3
    assert {row["day_index"] for row in change["removed_days"]} == {4, 5}
    assert {row["title"] for row in change["affected_items"]} == {"第四天景点", "第五天酒店"}

    assert _day_count(env, "trip-1") == 5
    trip = env.client.get("/api/v1/trips/trip-1").json()["data"]
    assert trip["duration_days"] == 5
    env.db.expire_all()
    assert env.db.get(PlanItem, item4.id).day_id == day4.id

    # 确认：执行缩短，地点移入待规划区并写移动日志
    confirmed = _put(env, "trip-1", start_date="2026-01-01", duration_days=3, confirm_shrink=True)
    assert confirmed.status_code == 200, confirmed.text
    result = confirmed.json()["data"]["duration_change"]
    assert result["applied"] is True
    assert result["preview"] is False
    assert len(result["removed_days"]) == 2
    assert len(result["moved_items"]) == 2

    assert _day_count(env, "trip-1") == 3
    trip = env.client.get("/api/v1/trips/trip-1").json()["data"]
    assert trip["duration_days"] == 3
    env.db.expire_all()
    assert env.db.get(PlanItem, item4.id).day_id is None
    assert env.db.get(PlanItem, item5.id).day_id is None
    assert env.db.query(PlanMoveLog).filter(PlanMoveLog.trip_id == "trip-1").count() == 2


def test_invalid_duration_rejected(env):
    resp = _put(env, "trip-3", start_date="2026-03-01", duration_days=0)
    assert resp.status_code == 422
    assert resp.json()["code"] == ErrorCode.DURATION_INVALID
    assert "天数" in resp.json()["message"]


def test_duration_without_anchor_date_rejected(env):
    resp = _put(env, "trip-3", duration_days=3)
    assert resp.status_code == 422
    assert resp.json()["code"] == ErrorCode.DURATION_INVALID
