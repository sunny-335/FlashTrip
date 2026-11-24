"""AI 排程跨天行为：条目按天分布、天数不足自动补建行程日、行程日清单可读。

覆盖用户实测问题：AI 排程把 3 天行程全部排在第 1 天，且天数不够时不会新增一天。
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.plan import PlanItem
from app.models.trip import Trip, TripDay
from app.models.user import User
from app.services.ai.tools import ToolRegistry


@pytest.fixture()
def db():
    """独立的内存库 + 建表，供工具注册表直接使用。"""
    from app.db.base import Base

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _owner(db) -> User:
    """行程所有者：写工具的权限校验与人工端点完全一致。"""
    user = User(id="user-1", username="owner", password_hash="x", role="owner", is_active=True)
    db.add(user)
    db.commit()
    return user


def _trip_with_days(db, count: int, *, start: date | None = None) -> tuple[Trip, list[TripDay]]:
    trip = Trip(
        id="trip-1",
        owner_id="user-1",
        title="苏州三日游",
        destination="苏州",
        start_date=start,
        end_date=(start + timedelta(days=count - 1)) if start else None,
    )
    db.add(trip)
    days = []
    for index in range(1, count + 1):
        day = TripDay(
            id=f"day-{index}",
            trip_id=trip.id,
            day_index=index,
            sort_key=f"d{index:06d}",
            date=(start + timedelta(days=index - 1)) if start else None,
        )
        db.add(day)
        days.append(day)
    db.commit()
    return trip, days


def _registry(db, trip_id: str) -> ToolRegistry:
    user = db.get(User, "user-1")
    return ToolRegistry(cfg={"ai": {}}, db=db, user=user, trip_id=trip_id)


def test_day_index_places_item_on_requested_day(db):
    _owner(db)
    trip, days = _trip_with_days(db, 3)
    registry = _registry(db, trip.id)

    registry.execute("add_plan_item", {"title": "拙政园", "day_index": 2}, confirmed=True)

    items = db.query(PlanItem).all()
    assert len(items) == 1
    assert items[0].day_id == days[1].id


def test_items_without_day_hint_spread_across_days(db):
    """模型没给落点时，也不能再全部堆在同一天。"""
    _owner(db)
    trip, days = _trip_with_days(db, 3)
    registry = _registry(db, trip.id)

    for title in ("早餐", "拙政园", "晚上"):
        registry.execute("add_plan_item", {"title": title}, confirmed=True)

    items = db.query(PlanItem).all()
    day_ids = {item.day_id for item in items}
    assert len(items) == 3
    assert len(day_ids) > 1, "条目应分散到不同天，而不是全排在同一天"


def test_day_index_beyond_existing_days_creates_new_day(db):
    """天数不够时自动补建行程日，并顺延行程结束日期。"""
    _owner(db)
    start = date(2026, 7, 27)
    trip, _days = _trip_with_days(db, 1, start=start)
    registry = _registry(db, trip.id)

    registry.execute("add_plan_item", {"title": "第三天的行程", "day_index": 3}, confirmed=True)

    days = db.query(TripDay).filter(TripDay.trip_id == trip.id).order_by(TripDay.day_index).all()
    assert [d.day_index for d in days] == [1, 2, 3]
    intermediate = next(d for d in days if d.day_index == 2)
    assert intermediate.date == start + timedelta(days=1)
    created = next(d for d in days if d.day_index == 3)
    assert created.date == start + timedelta(days=2)
    db.refresh(trip)
    assert trip.end_date == start + timedelta(days=2)


def test_date_argument_matches_day_by_date(db):
    _owner(db)
    start = date(2026, 7, 27)
    trip, days = _trip_with_days(db, 3, start=start)
    registry = _registry(db, trip.id)

    registry.execute(
        "add_plan_item",
        {"title": "寒山寺", "date": (start + timedelta(days=1)).isoformat()},
        confirmed=True,
    )

    item = db.query(PlanItem).one()
    assert item.day_id == days[1].id


def test_date_outside_trip_range_creates_days_with_continuous_indices(db):
    _owner(db)
    start = date(2026, 7, 27)
    trip, _days = _trip_with_days(db, 2, start=start)
    registry = _registry(db, trip.id)
    target = start + timedelta(days=4)

    registry.execute("add_plan_item", {"title": "第五天", "date": target.isoformat()}, confirmed=True)

    days = db.query(TripDay).filter(TripDay.trip_id == trip.id).order_by(TripDay.day_index).all()
    assert [day.day_index for day in days] == [1, 2, 3, 4, 5]
    assert [day.date for day in days] == [start + timedelta(days=i) for i in range(5)]
    assert db.query(PlanItem).one().day_id == days[-1].id
    db.refresh(trip)
    assert trip.end_date == target


def test_invalid_date_does_not_fall_back_to_arbitrary_day(db):
    from app.core.errors import AppError

    _owner(db)
    trip, _days = _trip_with_days(db, 2, start=date(2026, 7, 27))
    registry = _registry(db, trip.id)

    with pytest.raises(AppError, match="有效的 YYYY-MM-DD"):
        registry.execute("add_plan_item", {"title": "无效日期", "date": "2026-02-30"}, confirmed=True)

    assert db.query(PlanItem).count() == 0
    assert db.query(TripDay).filter(TripDay.trip_id == trip.id).count() == 2


def test_get_trip_days_lists_days_and_range(db):
    _owner(db)
    start = date(2026, 7, 27)
    trip, days = _trip_with_days(db, 3, start=start)
    registry = _registry(db, trip.id)

    result = registry.execute("get_trip_days", {}, confirmed=False)["result"]

    assert result["total_days"] == 3
    assert [d["day_id"] for d in result["days"]] == [d.id for d in days]
    assert result["start_date"] == start.isoformat()
    assert result["end_date"] == (start + timedelta(days=2)).isoformat()


def test_day_id_from_another_trip_is_ignored(db):
    """模型给出不属于本行程的 day_id 时不得写入。"""
    _owner(db)
    trip, _days = _trip_with_days(db, 2)
    other = TripDay(id="day-other", trip_id="trip-other", day_index=1, sort_key="d000001")
    db.add(other)
    db.commit()
    registry = _registry(db, trip.id)

    registry.execute("add_plan_item", {"title": "外来的天", "day_id": "day-other"}, confirmed=True)

    item = db.query(PlanItem).one()
    assert item.day_id != "day-other"
