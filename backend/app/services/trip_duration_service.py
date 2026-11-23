"""行程天数联动：日期推算、日期延长补足行程日、日期缩短二次确认。

规则（显式字段优先）：
- 同时给 start_date + duration_days → end_date = start + (duration_days - 1)；
- 同时给 end_date + duration_days → start_date = end - (duration_days - 1)；
- 同时显式给 start_date + end_date → 以显式日期为准，duration_days 仅作参考被忽略；
- 日期缩短时 confirm_shrink=False 只返回预览（受影响地点列表），不写库；
  confirm=True 才把受影响 day 的 plan_items 移入待规划区（写 PlanMoveLog）并软删多余 day。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.core.security import new_id
from app.models.plan import PlanItem, PlanMoveLog
from app.models.trip import Trip, TripDay


# ---------------------------------------------------------------- 日期推算

def compute_date_range(trip: Trip, changes: dict) -> tuple[date | None, date | None, int | None]:
    """根据显式日期字段与 duration_days 推算 (start_date, end_date, 目标天数)。

    目标天数 = (end - start).days + 1（含首尾）；任一日期缺失时为 None。
    """
    start = changes.get("start_date", trip.start_date)
    end = changes.get("end_date", trip.end_date)
    explicit_start = "start_date" in changes
    explicit_end = "end_date" in changes
    duration = changes.get("duration_days")

    if duration is not None:
        try:
            duration = int(duration)
        except (TypeError, ValueError):
            raise AppError(ErrorCode.DURATION_INVALID, "行程天数必须为正整数") from None
        if duration <= 0:
            raise AppError(ErrorCode.DURATION_INVALID, "行程天数必须为正整数")
        if explicit_start and explicit_end:
            pass  # 显式日期优先，忽略 duration_days
        elif explicit_start:
            if start is None:
                raise AppError(ErrorCode.DURATION_INVALID, "按天数推算需要开始日期")
            end = start + timedelta(days=duration - 1)
        elif explicit_end:
            if end is None:
                raise AppError(ErrorCode.DURATION_INVALID, "按天数推算需要结束日期")
            start = end - timedelta(days=duration - 1)
        elif start is not None:
            end = start + timedelta(days=duration - 1)
        elif end is not None:
            start = end - timedelta(days=duration - 1)
        else:
            raise AppError(ErrorCode.DURATION_INVALID, "请至少提供开始日期或结束日期，才能按天数推算")

    if start is not None and end is not None and end < start:
        raise AppError(ErrorCode.DURATION_INVALID, "结束日期不能早于开始日期")

    target_days = (end - start).days + 1 if start is not None and end is not None else None
    return start, end, target_days


# ---------------------------------------------------------------- 行程日联动

def _days(db: Session, trip_id: str) -> list[TripDay]:
    return (
        db.query(TripDay)
        .filter(TripDay.trip_id == trip_id)
        .order_by(TripDay.day_index)
        .all()
    )


def _reindex_dates(days: list[TripDay], start: date | None) -> None:
    """按顺序把行程日日期对齐到 start_date + 第 N 天。"""
    if start is None:
        return
    for position, day in enumerate(sorted(days, key=lambda d: d.day_index or 0)):
        day.date = start + timedelta(days=position)


def _describe_day(day: TripDay) -> dict:
    return {
        "id": day.id,
        "day_index": day.day_index,
        "date": day.date.isoformat() if day.date else None,
    }


def _describe_item(item: PlanItem, day_index: int | None) -> dict:
    return {
        "id": item.id,
        "title": item.title,
        "type": item.type,
        "from_day_id": item.day_id,
        "from_day_index": day_index,
        "sort_key": item.sort_key,
    }


def _preview(db: Session, trip: Trip, target_days: int, current_days: int,
             removed: list[TripDay]) -> dict:
    day_index = {day.id: day.day_index for day in removed}
    removed_ids = [day.id for day in removed]
    items = (
        db.query(PlanItem)
        .filter(PlanItem.trip_id == trip.id, PlanItem.day_id.in_(removed_ids))
        .order_by(PlanItem.day_id, PlanItem.sort_key)
        .all()
        if removed_ids
        else []
    )
    return {
        "applied": False,
        "preview": True,
        "trip_id": trip.id,
        "start_date": trip.start_date.isoformat() if trip.start_date else None,
        "end_date": trip.end_date.isoformat() if trip.end_date else None,
        "current_days": current_days,
        "target_days": target_days,
        "removed_days": [_describe_day(day) for day in removed],
        "affected_items": [_describe_item(item, day_index.get(item.day_id or "")) for item in items],
    }


def apply_duration(db: Session, trip: Trip, start: date | None, end: date | None,
                   target_days: int | None, *, confirm_shrink: bool,
                   user_id: str | None = None) -> dict:
    """应用日期与行程日联动。

    返回值中 preview=True 表示缩短未确认（此时不写库，调用方应回滚此前内存改动）；
    其余情况已在内部提交并返回 applied 摘要。
    """
    days = _days(db, trip.id)
    current_days = len(days)

    if target_days is not None and target_days < current_days and not confirm_shrink:
        # 预览基于「新日期」计算，但不写 trip / day / item
        old_start, old_end = trip.start_date, trip.end_date
        trip.start_date, trip.end_date = start, end
        result = _preview(db, trip, target_days, current_days, days[target_days:])
        trip.start_date, trip.end_date = old_start, old_end
        return result

    trip.start_date = start
    trip.end_date = end

    if target_days is None:
        db.commit()
        return {
            "applied": True,
            "preview": False,
            "trip_id": trip.id,
            "current_days": current_days,
            "target_days": None,
            "created_days": 0,
            "removed_days": [],
            "moved_items": [],
        }

    created_days = 0
    removed_days: list[dict] = []
    moved_items: list[dict] = []

    if target_days > current_days:
        # 延长：沿用 create_day 的 sort_key 规则补足缺失行程日
        existing_indices = {day.day_index for day in days}
        next_index = max(existing_indices, default=0) + 1
        new_days: list[TripDay] = []
        while len(days) + created_days < target_days:
            day_date = start + timedelta(days=next_index - 1) if start is not None else None
            day = TripDay(
                id=new_id(),
                trip_id=trip.id,
                day_index=next_index,
                sort_key=f"d{next_index:06d}",
                date=day_date,
            )
            db.add(day)
            new_days.append(day)
            created_days += 1
            next_index += 1
        _reindex_dates(days + new_days, start)
    elif target_days < current_days:
        # 缩短：受影响 day 的计划项移入待规划区（写 PlanMoveLog，沿用 plan_moves 语义）
        keep = days[:target_days]
        removed = days[target_days:]
        removed_ids = {day.id for day in removed}
        day_index = {day.id: day.day_index for day in removed}
        items = (
            db.query(PlanItem)
            .filter(PlanItem.trip_id == trip.id, PlanItem.day_id.in_(removed_ids))
            .order_by(PlanItem.day_id, PlanItem.sort_key)
            .all()
            if removed_ids
            else []
        )
        batch_id = new_id()
        now = datetime.now(timezone.utc)
        for item in items:
            before_day_id, before_sort_key = item.day_id, item.sort_key
            item.day_id = None
            item.bucket = "main"
            db.add(
                PlanMoveLog(
                    id=new_id(),
                    trip_id=trip.id,
                    item_id=item.id,
                    user_id=user_id,
                    batch_id=batch_id,
                    before_day_id=before_day_id,
                    before_sort_key=before_sort_key,
                    after_day_id=None,
                    after_sort_key=before_sort_key,
                    undone_at=None,
                )
            )
            moved_items.append(_describe_item(item, day_index.get(before_day_id or "")))
        for day in removed:
            day.deleted_at = now
            removed_days.append(_describe_day(day))
        _reindex_dates(keep, start)
    else:
        _reindex_dates(days, start)

    db.commit()
    return {
        "applied": True,
        "preview": False,
        "trip_id": trip.id,
        "current_days": current_days,
        "target_days": target_days,
        "created_days": created_days,
        "removed_days": removed_days,
        "moved_items": moved_items,
    }


def duration_days(start: date | None, end: date | None) -> int | None:
    """读取侧展示用：行程天数（含首尾）。"""
    if start is None or end is None or end < start:
        return None
    return (end - start).days + 1
