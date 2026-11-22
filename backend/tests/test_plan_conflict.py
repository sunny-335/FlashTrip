"""plan_service：normalize_times 自洽、14:00 衔接不冲突、真正重叠才报、
auto_arrange 后无冲突、中文分类预设。

直接调 service + 临时 SQLite，AI 排程分支可用 monkeypatch 覆盖，不发真实网络请求。
"""
from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.errors import AppError, ErrorCode
from app.core.security import new_id
from app.db.base import Base
from app.models.plan import PlanItem, PlanMoveLog
from app.models.trip import Trip, TripDay
from app.services import plan_service as svc

_TABLES = [Trip.__table__, TripDay.__table__, PlanItem.__table__, PlanMoveLog.__table__]


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'plan_conflict.db').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine, tables=_TABLES)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _seed(db):
    trip = Trip(id=new_id(), owner_id="owner-1", title="冲突测试行程")
    day = TripDay(id=new_id(), trip_id=trip.id, day_index=1, sort_key="d1")
    db.add_all([trip, day])
    db.commit()
    return trip, day


def _item(item_id, day_id, start, end):
    return {"id": item_id, "day_id": day_id, "title": item_id,
            "start_time": start, "end_time": end}


def test_normalize_times_start_plus_duration():
    out = svc.normalize_times({"start_time": "2024-01-01T09:00:00", "duration_min": 90})
    assert out["end_time"] == datetime(2024, 1, 1, 10, 30)
    assert out["duration_min"] == 90


def test_normalize_times_end_recomputes_duration():
    """三者齐全时 end_time 优先：duration_min 被反推/校验为 120。"""
    out = svc.normalize_times({
        "start_time": "2024-01-01T09:00:00",
        "end_time": "2024-01-01T11:00:00",
        "duration_min": 30,
    })
    assert out["duration_min"] == 120
    assert out["end_time"] == datetime(2024, 1, 1, 11, 0)


def test_normalize_times_end_plus_duration_infers_start():
    out = svc.normalize_times({"end_time": "2024-01-01T12:00:00", "duration_min": 60})
    assert out["start_time"] == datetime(2024, 1, 1, 11, 0)
    assert out["end_time"] == datetime(2024, 1, 1, 12, 0)


def test_normalize_times_rejects_reversed_range():
    with pytest.raises(AppError) as err:
        svc.normalize_times({
            "start_time": "2024-01-01T10:00:00",
            "end_time": "2024-01-01T09:00:00",
        })
    assert err.value.code == ErrorCode.VALIDATION


def test_adjacent_14_00_is_not_conflict():
    """前项 14:00 结束、后项 14:00 开始，严格相等不算冲突。"""
    items = [
        _item("a", "d1", "2024-01-01T13:00:00", "2024-01-01T14:00:00"),
        _item("b", "d1", "2024-01-01T14:00:00", "2024-01-01T15:00:00"),
    ]
    assert svc.detect_conflicts(items) == []


def test_real_overlap_is_reported():
    items = [
        _item("a", "d1", "2024-01-01T13:00:00", "2024-01-01T14:30:00"),
        _item("b", "d1", "2024-01-01T14:00:00", "2024-01-01T15:00:00"),
        _item("c", "d1", "2024-01-01T15:00:00", "2024-01-01T16:00:00"),
    ]
    conflicts = svc.detect_conflicts(items)
    assert len(conflicts) == 1
    assert {conflicts[0]["item_id"], conflicts[0]["with_item_id"]} == {"a", "b"}
    assert "重叠" in conflicts[0]["reason"]
    assert conflicts[0]["start"] == "2024-01-01T14:00:00"


def test_different_days_never_conflict():
    items = [
        _item("a", "d1", "2024-01-01T13:00:00", "2024-01-01T15:00:00"),
        _item("b", "d2", "2024-01-01T13:00:00", "2024-01-01T15:00:00"),
    ]
    assert svc.detect_conflicts(items) == []


def test_auto_arrange_removes_conflicts(db):
    trip, day = _seed(db)
    db.add_all([
        PlanItem(id=new_id(), trip_id=trip.id, day_id=day.id, bucket="day", type="place",
                 title="A", sort_key="a0", start_time=datetime(2024, 1, 1, 13, 0),
                 end_time=datetime(2024, 1, 1, 15, 0), duration_min=120),
        PlanItem(id=new_id(), trip_id=trip.id, day_id=day.id, bucket="day", type="place",
                 title="B", sort_key="a1", start_time=datetime(2024, 1, 1, 14, 0),
                 end_time=datetime(2024, 1, 1, 15, 0), duration_min=60),
        PlanItem(id=new_id(), trip_id=trip.id, day_id=day.id, bucket="day", type="place",
                 title="C", sort_key="a2", start_time=datetime(2024, 1, 1, 16, 0),
                 end_time=datetime(2024, 1, 1, 17, 0), duration_min=60),
    ])
    db.commit()
    assert len(svc.conflicts_for_trip(db, trip.id)) == 1

    result = svc.auto_arrange(db, trip.id, day.id, use_ai=False)
    assert result["arranged"] == 3
    assert result["conflicts"] == 0
    assert result["aiApplied"] is False
    # 相邻无缝衔接：前项 end == 后项 start
    arranged = sorted(result["items"], key=lambda row: row["start_time"])
    for prev, nxt in zip(arranged, arranged[1:]):
        assert prev["end_time"] == nxt["start_time"]
    assert svc.conflicts_for_trip(db, trip.id) == []


def test_auto_arrange_ai_failure_falls_back(db, monkeypatch):
    """AI 顺序不可用时静默降级为顺序重排，不抛异常。"""
    trip, day = _seed(db)
    db.add_all([
        PlanItem(id=new_id(), trip_id=trip.id, day_id=day.id, bucket="day", type="place",
                 title="A", sort_key="a0", duration_min=30),
        PlanItem(id=new_id(), trip_id=trip.id, day_id=day.id, bucket="day", type="place",
                 title="B", sort_key="a1", duration_min=45),
    ])
    db.commit()
    monkeypatch.setattr(svc, "_ai_order", lambda *_args, **_kwargs: None)

    result = svc.auto_arrange(db, trip.id, day.id, use_ai=True)
    assert result["useAi"] is True
    assert result["aiApplied"] is False
    assert result["conflicts"] == 0
    assert [row["duration_min"] for row in result["items"]] == [30, 45]


def test_categories_are_chinese_id_label_pairs():
    cats = svc.list_categories()
    assert {c["id"] for c in cats} == {"景点", "餐饮", "住宿", "交通", "购物", "娱乐", "休闲", "其他"}
    assert all(c["id"] == c["label"] for c in cats)
