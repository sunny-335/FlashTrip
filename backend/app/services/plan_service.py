"""三栏计划服务：一次取板、条目 CRUD、批量拖拽（单事务字典序校验 + 日志）、精确 undo、导入与 GeoJSON 路线。

拖拽排序键由前端 keyBetween() 计算；后端**只做字典序校验**并落库，
不实现任何 fractional indexing 算法。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Sequence

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.core.security import new_id
from app.models.plan import PlanItem, PlanMoveLog
from app.models.trip import Trip, TripDay
from app.schemas.common import dump_many
from app.schemas.plan import MoveIn, PlanItemCreate, PlanItemOut, PlanItemUpdate
from app.schemas.trip import TripDayOut


# ---------------------------------------------------------------- 内部辅助

def _trip_or_404(db: Session, trip_id: str) -> Trip:
    trip = db.get(Trip, trip_id)
    if trip is None:
        raise AppError(ErrorCode.NOT_FOUND, "行程不存在")
    return trip


def _day_or_404(db: Session, trip_id: str, day_id: str) -> TripDay:
    day = db.get(TripDay, day_id)
    if day is None or day.trip_id != trip_id:
        raise AppError(ErrorCode.NOT_FOUND, "行程日不存在")
    return day


def _item_or_404(db: Session, trip_id: str, item_id: str) -> PlanItem:
    item = db.get(PlanItem, item_id)
    if item is None or item.trip_id != trip_id:
        raise AppError(ErrorCode.NOT_FOUND, "计划项不存在")
    return item


def _max_sort_key(db: Session, trip_id: str, day_id: str | None, bucket: str) -> str | None:
    """取同分组最大 sort_key；用显式 SQL 并手动排除软删行，避免聚合与全局 loader criteria 耦合。"""
    params: dict[str, Any] = {"t": trip_id, "b": bucket}
    if day_id is None:
        condition = "day_id IS NULL"
    else:
        condition = "day_id = :d"
        params["d"] = day_id
    sql = text(
        "SELECT MAX(sort_key) FROM plan_items "
        f"WHERE trip_id = :t AND {condition} AND bucket = :b AND deleted_at IS NULL"
    )
    return db.execute(sql, params).scalar()


def next_sort_key(db: Session, trip_id: str, day_id: str | None = None, bucket: str = "main") -> str:
    """新建条目时追加到末尾：取当前最大键后追加 'z'。

    这只是「末尾追加」启发式，不是 fractional indexing；插到两项之间必须由前端提交 new_sort_key。
    """
    mx = _max_sort_key(db, trip_id, day_id, bucket)
    return f"{mx}z" if mx else "a0"


def _item_data(payload: PlanItemCreate, sort_key: str) -> dict[str, Any]:
    data = payload.model_dump()
    data.pop("sort_key", None)
    data["sort_key"] = sort_key
    return data


# ---------------------------------------------------------------- 查询

def get_plan(db: Session, trip_id: str) -> dict:
    """一次返回 days / planned / unplanned（另附 planned_by_day 便于看板分组）。"""
    _trip_or_404(db, trip_id)
    days = (
        db.query(TripDay)
        .filter(TripDay.trip_id == trip_id)
        .order_by(TripDay.sort_key, TripDay.day_index)
        .all()
    )
    items = (
        db.query(PlanItem)
        .filter(PlanItem.trip_id == trip_id)
        .order_by(PlanItem.sort_key)
        .all()
    )
    planned = sorted(
        (i for i in items if i.day_id is not None),
        key=lambda i: (i.day_id or "", i.sort_key),
    )
    unplanned = [i for i in items if i.day_id is None]
    by_day: dict[str, list[PlanItem]] = {}
    for item in planned:
        by_day.setdefault(item.day_id or "", []).append(item)
    return {
        "days": dump_many(TripDayOut, days),
        "planned": dump_many(PlanItemOut, planned),
        "unplanned": dump_many(PlanItemOut, unplanned),
        "planned_by_day": {key: dump_many(PlanItemOut, value) for key, value in by_day.items()},
    }


def build_route(db: Session, trip_id: str) -> dict:
    """按 day / sort_key 顺序生成 GeoJSON FeatureCollection（点 + 连线）。"""
    _trip_or_404(db, trip_id)
    items = (
        db.query(PlanItem)
        .filter(
            PlanItem.trip_id == trip_id,
            PlanItem.lng.isnot(None),
            PlanItem.lat.isnot(None),
        )
        .order_by(PlanItem.day_id, PlanItem.sort_key)
        .all()
    )
    coords: list[list[float]] = []
    features: list[dict[str, Any]] = []
    for item in items:
        coord = [float(item.lng), float(item.lat)]  # type: ignore[arg-type]
        coords.append(coord)
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": coord},
                "properties": {
                    "id": item.id,
                    "title": item.title,
                    "type": item.type,
                    "day_id": item.day_id,
                    "bucket": item.bucket,
                    "sort_key": item.sort_key,
                },
            }
        )
    if len(coords) >= 2:
        features.insert(
            0,
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": coords},
                "properties": {"title": "行程路线", "count": len(coords)},
            },
        )
    return {"type": "FeatureCollection", "features": features}


# ---------------------------------------------------------------- 条目写入

def create_item(db: Session, trip_id: str, payload: PlanItemCreate, user_id: str | None) -> PlanItem:
    _trip_or_404(db, trip_id)
    if payload.day_id is not None:
        _day_or_404(db, trip_id, payload.day_id)
    sort_key = payload.sort_key or next_sort_key(db, trip_id, payload.day_id, payload.bucket)
    item = PlanItem(id=new_id(), trip_id=trip_id, created_by=user_id, **_item_data(payload, sort_key))
    db.add(item)
    db.commit()
    return item


def update_item(db: Session, trip_id: str, item_id: str, payload: PlanItemUpdate) -> PlanItem:
    item = _item_or_404(db, trip_id, item_id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        if key == "day_id" and value is not None:
            _day_or_404(db, trip_id, value)
        if key == "sort_key" and not value:
            continue
        setattr(item, key, value)
    db.commit()
    return item


def delete_item(db: Session, trip_id: str, item_id: str) -> None:
    """软删：写入 deleted_at，全局过滤自动隐藏。"""
    item = _item_or_404(db, trip_id, item_id)
    item.deleted_at = datetime.now(timezone.utc)
    db.commit()


def import_items(
    db: Session, trip_id: str, user_id: str | None, items: Sequence[PlanItemCreate]
) -> list[PlanItem]:
    try:
        _trip_or_404(db, trip_id)
        created: list[PlanItem] = []
        for payload in items:
            if payload.day_id is not None:
                _day_or_404(db, trip_id, payload.day_id)
            sort_key = payload.sort_key or next_sort_key(db, trip_id, payload.day_id, payload.bucket)
            item = PlanItem(
                id=new_id(), trip_id=trip_id, created_by=user_id, **_item_data(payload, sort_key)
            )
            db.add(item)
            # 逐条 flush，使同批后续 next_sort_key 能看到刚追加的键
            db.flush()
            created.append(item)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return created


# ---------------------------------------------------------------- 批量拖拽 / undo

def validate_sort_key(before: str | None, new: str, after: str | None) -> None:
    """唯一校验规则：before_sort_key < new_sort_key < after_sort_key（纯字典序）。

    None 表示该方向没有相邻项（落到端点）。后端不计算键、不校验邻居是否真实存在。
    """
    if not new:
        raise AppError(ErrorCode.VALIDATION, "new_sort_key 不能为空")
    if before is not None and not (before < new):
        raise AppError(ErrorCode.VALIDATION, "排序键非法：new_sort_key 必须大于 before_sort_key")
    if after is not None and not (new < after):
        raise AppError(ErrorCode.VALIDATION, "排序键非法：new_sort_key 必须小于 after_sort_key")


def apply_moves(
    db: Session, trip_id: str, user_id: str | None, moves: Sequence[MoveIn]
) -> dict:
    """单事务：先整体校验，再一次性落库并写 PlanMoveLog；任何失败全批回滚。"""
    try:
        _trip_or_404(db, trip_id)
        prepared: list[tuple[MoveIn, PlanItem]] = []
        for move in moves:
            validate_sort_key(move.before_sort_key, move.new_sort_key, move.after_sort_key)
            item = _item_or_404(db, trip_id, move.item_id)
            if move.to_day_id is not None:
                _day_or_404(db, trip_id, move.to_day_id)
            prepared.append((move, item))

        batch_id = new_id()
        for move, item in prepared:
            before_day_id, before_sort_key = item.day_id, item.sort_key
            item.day_id = move.to_day_id
            item.bucket = move.to_bucket
            item.sort_key = move.new_sort_key
            db.add(
                PlanMoveLog(
                    id=new_id(),
                    trip_id=trip_id,
                    item_id=item.id,
                    user_id=user_id,
                    batch_id=batch_id,
                    before_day_id=before_day_id,
                    before_sort_key=before_sort_key,
                    after_day_id=move.to_day_id,
                    after_sort_key=move.new_sort_key,
                    undone_at=None,
                )
            )
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"batch_id": batch_id, "moved": len(prepared)}


def undo_moves(
    db: Session, trip_id: str, batch_id: str | None = None
) -> dict:
    """撤销最近一批（或指定 batch）拖拽，精确还原到 before_day_id / before_sort_key。"""
    try:
        _trip_or_404(db, trip_id)
        base = db.query(PlanMoveLog).filter(
            PlanMoveLog.trip_id == trip_id, PlanMoveLog.undone_at.is_(None)
        )
        if batch_id is None:
            latest = base.order_by(PlanMoveLog.created_at.desc()).first()
            if latest is None:
                raise AppError(ErrorCode.NOT_FOUND, "没有可撤销的拖拽记录")
            batch_id = latest.batch_id
        logs = base.filter(PlanMoveLog.batch_id == batch_id).order_by(PlanMoveLog.created_at).all()
        if not logs:
            raise AppError(ErrorCode.NOT_FOUND, "没有可撤销的拖拽记录")

        now = datetime.now(timezone.utc)
        restored = 0
        for log in logs:
            item = db.get(PlanItem, log.item_id)
            if item is not None and item.trip_id == trip_id:
                item.day_id = log.before_day_id
                item.sort_key = log.before_sort_key or item.sort_key
                restored += 1
            log.undone_at = now
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"batch_id": batch_id, "restored": restored}
