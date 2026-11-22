"""plan_service：sort_key 字典序校验、moves 单事务落库、undo 精确还原。

直接调用 service 函数 + 临时 SQLite，不经过 API 权限依赖。
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.errors import AppError, ErrorCode
from app.core.security import new_id
from app.db.base import Base
from app.models.plan import PlanItem, PlanMoveLog
from app.models.trip import Trip, TripDay
from app.schemas.plan import MoveIn
from app.services import plan_service

# 只建本用例涉及的四张表，隔离其他并行模块新增的模型
_TABLES = [Trip.__table__, TripDay.__table__, PlanItem.__table__, PlanMoveLog.__table__]


@pytest.fixture()
def session(tmp_path):
    url = f"sqlite:///{(tmp_path / 'plan.db').as_posix()}"
    engine = create_engine(url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine, tables=_TABLES)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    db = Session()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


def _seed(db):
    trip = Trip(id=new_id(), owner_id="owner-1", title="测试行程")
    day1 = TripDay(id=new_id(), trip_id=trip.id, day_index=1, sort_key="d000001")
    day2 = TripDay(id=new_id(), trip_id=trip.id, day_index=2, sort_key="d000002")
    items = [
        PlanItem(
            id=new_id(), trip_id=trip.id, day_id=None, bucket="main", type="place",
            title="池A", sort_key="a0", created_by="u1",
        ),
        PlanItem(
            id=new_id(), trip_id=trip.id, day_id=None, bucket="main", type="activity",
            title="池B", sort_key="a1", created_by="u1", lng=116.39, lat=39.90,
        ),
        PlanItem(
            id=new_id(), trip_id=trip.id, day_id=day2.id, bucket="day", type="hotel",
            title="已排C", sort_key="b0", created_by="u1", lng=116.40, lat=39.91,
        ),
    ]
    db.add_all([trip, day1, day2, *items])
    db.commit()
    return trip, day1, day2, items


def _move(item, to_day_id, new_key, before=None, after=None):
    return MoveIn(
        item_id=item.id,
        to_day_id=to_day_id,
        to_bucket="day",
        new_sort_key=new_key,
        before_sort_key=before,
        after_sort_key=after,
    )


def test_validate_sort_key_is_pure_lexicographic():
    # 合法：before < new < after
    plan_service.validate_sort_key("a0", "a0V", "a1")
    plan_service.validate_sort_key(None, "z", None)  # 落到端点，无相邻约束

    with pytest.raises(AppError) as err:
        plan_service.validate_sort_key("a1", "a0", "a2")  # new 不大于 before
    assert err.value.code == ErrorCode.VALIDATION

    with pytest.raises(AppError) as err:
        plan_service.validate_sort_key("a0", "zz", "a1")  # new 不小于 after
    assert err.value.code == ErrorCode.VALIDATION

    with pytest.raises(AppError):
        plan_service.validate_sort_key("a0", "", "a1")  # 空键非法


def test_moves_persist_and_write_log(session):
    trip, day1, _day2, items = _seed(session)
    moves = [
        _move(items[0], day1.id, "m", before="a", after="z"),
        _move(items[1], day1.id, "n", before="m", after="z"),
    ]

    result = plan_service.apply_moves(session, trip.id, "u1", moves)

    assert result["moved"] == 2
    assert result["batch_id"]
    # 清掉 identity map，从 DB 重新读取，验证真的落库
    session.expunge_all()
    row0 = session.get(PlanItem, items[0].id)
    row1 = session.get(PlanItem, items[1].id)
    assert (row0.day_id, row0.sort_key, row0.bucket) == (day1.id, "m", "day")
    assert (row1.day_id, row1.sort_key, row1.bucket) == (day1.id, "n", "day")

    logs = (
        session.query(PlanMoveLog)
        .filter(PlanMoveLog.batch_id == result["batch_id"])
        .all()
    )
    assert len(logs) == 2
    assert {log.before_day_id for log in logs} == {None}
    assert {log.after_day_id for log in logs} == {day1.id}
    assert all(log.undone_at is None for log in logs)


def test_moves_rollback_entire_batch_on_invalid_key(session):
    trip, day1, _day2, items = _seed(session)
    original = {item.id: (item.day_id, item.sort_key) for item in items}

    good = _move(items[0], day1.id, "m", before="a", after="z")
    bad = _move(items[1], day1.id, "a", before="m", after="z")  # m < a 不成立
    with pytest.raises(AppError) as err:
        plan_service.apply_moves(session, trip.id, "u1", [good, bad])
    assert err.value.code == ErrorCode.VALIDATION

    # 整体回滚：第一条也没落库、没有任何日志
    session.expunge_all()
    assert session.query(PlanMoveLog).count() == 0
    for item_id, (day_id, sort_key) in original.items():
        row = session.get(PlanItem, item_id)
        assert (row.day_id, row.sort_key) == (day_id, sort_key)


def test_undo_restores_before_position_exactly(session):
    trip, day1, day2, items = _seed(session)
    before = {item.id: (item.day_id, item.sort_key) for item in items}
    moves = [
        _move(items[0], day1.id, "m", before="a", after="z"),
        _move(items[2], None, "c", before="b", after="z"),  # 已排 → 回池
    ]
    plan_service.apply_moves(session, trip.id, "u1", moves)

    result = plan_service.undo_moves(session, trip.id)

    assert result["restored"] == 2
    session.expunge_all()
    for item_id, (day_id, sort_key) in before.items():
        row = session.get(PlanItem, item_id)
        assert (row.day_id, row.sort_key) == (day_id, sort_key)
    # 全部日志已标记 undone，重复 undo 应报无记录
    assert (
        session.query(PlanMoveLog)
        .filter(PlanMoveLog.undone_at.is_(None))
        .count()
        == 0
    )
    with pytest.raises(AppError) as err:
        plan_service.undo_moves(session, trip.id)
    assert err.value.code == ErrorCode.NOT_FOUND


def test_get_plan_shape_and_route(session):
    trip, day1, day2, items = _seed(session)
    board = plan_service.get_plan(session, trip.id)

    assert {d["id"] for d in board["days"]} == {day1.id, day2.id}
    assert len(board["planned"]) == 1
    assert len(board["unplanned"]) == 2
    assert day2.id in board["planned_by_day"]

    route = plan_service.build_route(session, trip.id)
    assert route["type"] == "FeatureCollection"
    # 两个带坐标的点 + 一条 LineString
    assert len(route["features"]) == 3
    assert route["features"][0]["geometry"]["type"] == "LineString"
