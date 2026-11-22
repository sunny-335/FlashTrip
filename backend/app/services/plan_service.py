"""三栏计划服务：一次取板、条目 CRUD、批量拖拽（单事务字典序校验 + 日志）、精确 undo、导入与 GeoJSON 路线。

拖拽排序键由前端 keyBetween() 计算；后端**只做字典序校验**并落库，
不实现任何 fractional indexing 算法。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
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
    # 写库前统一让 start_time / end_time / duration_min 三者自洽
    data = normalize_times(_item_data(payload, sort_key))
    item = PlanItem(id=new_id(), trip_id=trip_id, created_by=user_id, **data)
    db.add(item)
    db.commit()
    return item


def update_item(db: Session, trip_id: str, item_id: str, payload: PlanItemUpdate) -> PlanItem:
    item = _item_or_404(db, trip_id, item_id)
    incoming = payload.model_dump(exclude_unset=True)
    for key, value in incoming.items():
        if key == "day_id" and value is not None:
            _day_or_404(db, trip_id, value)
        if key == "sort_key" and not value:
            continue
        setattr(item, key, value)

    # 时间三字段基于「合并后的值」重算：只提交 duration_min 时按新时长顺延 end_time，
    # 显式提交 end_time 时以其为准反推 duration_min，避免旧 end 覆盖本次意图。
    time_keys = ("start_time", "end_time", "duration_min")
    if any(key in incoming for key in time_keys):
        old_duration = item.duration_min
        if old_duration is None and item.start_time and item.end_time:
            old_start, old_end = _parse_time(item.start_time), _parse_time(item.end_time)
            if old_start and old_end and old_end >= old_start:
                old_duration = int((old_end - old_start).total_seconds() // 60)
        merged: dict[str, Any] = {
            "start_time": incoming.get("start_time", item.start_time),
        }
        if "end_time" in incoming:
            merged["end_time"] = incoming["end_time"]
        if "duration_min" in incoming:
            merged["duration_min"] = incoming["duration_min"]
        elif "end_time" not in incoming and old_duration is not None:
            merged["duration_min"] = old_duration
        norm = normalize_times(merged)
        item.start_time = norm.get("start_time", item.start_time)
        item.end_time = norm.get("end_time", item.end_time)
        item.duration_min = norm.get("duration_min", item.duration_min)
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


# ---------------------------------------------------------------- 分类预设 / 时间联动 / 冲突 / 自动排程

# 中文分类预设，供 GET /trips/{trip_id}/plan/categories 返回 {id,label}
PLAN_CATEGORIES = ("景点", "餐饮", "住宿", "交通", "购物", "娱乐", "休闲", "其他")


def list_categories() -> list[dict]:
    return [{"id": name, "label": name} for name in PLAN_CATEGORIES]


def _parse_time(value: Any) -> datetime | None:
    """把 datetime / ISO 字符串统一为 naive datetime（避免 aware/naive 相减报错）。"""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo else value
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        raise AppError(ErrorCode.VALIDATION, "时间格式不合法，请使用 ISO 8601") from None
    return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed


def _parse_duration(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        minutes = int(value)
    except (TypeError, ValueError):
        raise AppError(ErrorCode.VALIDATION, "时长须为整数分钟") from None
    if minutes < 0:
        raise AppError(ErrorCode.VALIDATION, "时长不能为负数")
    return minutes


def normalize_times(data: dict) -> dict:
    """让 start_time / end_time / duration_min 三者保持自洽。

    - 给了 start + duration：自动算 end；
    - 给了 start + end：以 end 为准反推 / 校验 duration；
    - 给了 end + duration：反推 start。
    三者齐全时 end_time 优先（HTTP 请求里它是最直观的字段）。
    """
    out = dict(data or {})
    start = _parse_time(out.get("start_time"))
    end = _parse_time(out.get("end_time"))
    duration = _parse_duration(out.get("duration_min"))

    has_start = start is not None
    has_end = end is not None
    has_duration = duration is not None
    if has_start and has_end:
        seconds = (end - start).total_seconds()
        if seconds < 0:
            raise AppError(ErrorCode.VALIDATION, "结束时间不能早于开始时间")
        duration = int(seconds // 60)  # end 权威：反推并校验 duration
        has_duration = True
    elif has_start and has_duration:
        end = start + timedelta(minutes=duration)
        has_end = True
    elif has_end and has_duration:
        start = end - timedelta(minutes=duration)
        has_start = True

    for key, value, present in (
        ("start_time", start, has_start),
        ("end_time", end, has_end),
        ("duration_min", duration, has_duration),
    ):
        if present or key in out:
            out[key] = value
    return out


def _item_field(item: Any, name: str) -> Any:
    return item.get(name) if isinstance(item, dict) else getattr(item, name, None)


def detect_conflicts(items: list) -> list[dict]:
    """同一 day_id 内按 start_time 排序检测重叠。

    严格 prev_end > next_start 才算冲突（前项 end == 后项 start 视为无缝衔接）；
    返回 [{item_id, with_item_id, start, end, reason}]，start/end 为重叠区间 ISO 串。
    无 start/end 或 end <= start 的条目不参与。
    """
    groups: dict[str, list[dict]] = {}
    for item in items or []:
        start = _parse_time(_item_field(item, "start_time"))
        end = _parse_time(_item_field(item, "end_time"))
        if start is None or end is None or end <= start:
            continue
        key = str(_item_field(item, "day_id") or "")
        groups.setdefault(key, []).append({
            "item_id": str(_item_field(item, "id") or ""),
            "title": str(_item_field(item, "title") or ""),
            "start": start,
            "end": end,
        })

    conflicts: list[dict] = []
    for rows in groups.values():
        rows.sort(key=lambda r: (r["start"], r["item_id"]))
        active: dict | None = None  # 结束时间最晚的前项
        for row in rows:
            if active is None:
                active = row
                continue
            if active["end"] > row["start"]:
                conflicts.append({
                    "item_id": row["item_id"],
                    "with_item_id": active["item_id"],
                    "start": row["start"].isoformat(),
                    "end": min(active["end"], row["end"]).isoformat(),
                    "reason": f"与「{active['title'] or active['item_id']}」时间重叠",
                })
            # 保留结束最晚者，避免长时段条目覆盖多个后续条目时漏报
            if row["end"] > active["end"]:
                active = row
    return conflicts


def conflicts_for_trip(db: Session, trip_id: str) -> list[dict]:
    """读取整个行程的已排条目并返回冲突列表（供 GET /plan/conflicts）。"""
    _trip_or_404(db, trip_id)
    rows = (
        db.query(PlanItem)
        .filter(PlanItem.trip_id == trip_id)
        .order_by(PlanItem.day_id, PlanItem.sort_key)
        .all()
    )
    return detect_conflicts(rows)


def _arrange_anchor(db: Session, day_id: str | None, rows: list[PlanItem]) -> datetime:
    """取该天最早的 start_time 作为锚点；都没有时用行程日日期（或今天）的 09:00。"""
    starts = [_parse_time(row.start_time) for row in rows]
    starts = [value for value in starts if value is not None]
    if starts:
        return min(starts)
    day = db.get(TripDay, day_id) if day_id else None
    raw_date = getattr(day, "date", None) if day is not None else None
    if isinstance(raw_date, datetime):
        base = raw_date.replace(hour=9, minute=0, second=0, microsecond=0)
    elif raw_date is not None and hasattr(raw_date, "year"):
        base = datetime(raw_date.year, raw_date.month, raw_date.day, 9, 0, 0)
    else:
        base = datetime.now().replace(hour=9, minute=0, second=0, microsecond=0)
    return base.replace(tzinfo=None) if base.tzinfo else base


def _ai_order(db: Session, rows: list[PlanItem]) -> list[str] | None:
    """调 LLMGateway 生成更合理的顺序；任何异常/非法输出都返回 None 交由调用方降级。"""
    if len(rows) < 2:
        return None
    try:
        import json

        from app.services.ai.gateway import LLMGateway

        ids = [row.id for row in rows]
        brief = [
            {"id": row.id, "title": row.title, "type": row.type,
             "category": row.category, "duration_min": row.duration_min}
            for row in rows
        ]
        prompt = (
            "你是行程规划助手。根据以下条目的类型、标题与时长，给出更合理的游览顺序。"
            "只输出一个 JSON 数组，元素是这些 id 的一个排列，不要输出其它文字。\n"
            + json.dumps(brief, ensure_ascii=False, default=str)
        )
        events = LLMGateway(db=db).chat(
            [{"role": "system", "content": "只输出 JSON 数组，不要解释。"},
             {"role": "user", "content": prompt}],
            stream=False,
        )
        text = ""
        for event in events:
            for line in str(event).splitlines():
                if not line.startswith("data:"):
                    continue
                try:
                    payload = json.loads(line[5:].strip())
                except (ValueError, TypeError):
                    continue
                if isinstance(payload, dict) and payload.get("content"):
                    text = str(payload["content"])
        left, right = text.find("["), text.rfind("]")
        if left < 0 or right <= left:
            return None
        order = json.loads(text[left:right + 1])
        if not isinstance(order, list):
            return None
        cleaned = [str(value) for value in order if str(value) in ids]
        if len(cleaned) != len(ids) or set(cleaned) != set(ids):
            return None
        return cleaned
    except Exception:  # noqa: BLE001  AI 不可用必须静默降级，绝不影响排程
        return None


def auto_arrange(db: Session, trip_id: str, day_id: str | None, *, use_ai: bool = False) -> dict:
    """把该天条目按当前顺序（或 AI 顺序）重排时间：保留时长、相邻无缝衔接、消除冲突。

    use_ai=True 时调 LLMGateway 生成更合理顺序；失败自动降级为顺序重排，不抛异常。
    """
    _trip_or_404(db, trip_id)
    if day_id is not None:
        _day_or_404(db, trip_id, day_id)
    rows = (
        db.query(PlanItem)
        .filter(PlanItem.trip_id == trip_id, PlanItem.day_id == day_id)
        .order_by(PlanItem.sort_key)
        .all()
    )
    if not rows:
        return {"arranged": 0, "dayId": day_id, "useAi": bool(use_ai),
                "aiApplied": False, "conflicts": 0, "items": []}

    order = list(rows)
    ai_applied = False
    if use_ai:
        ai_ids = _ai_order(db, rows)
        if ai_ids:
            by_id = {row.id: row for row in rows}
            order = [by_id[item_id] for item_id in ai_ids]
            ai_applied = True

    cursor = _arrange_anchor(db, day_id, rows)
    for item in order:
        minutes = item.duration_min
        if minutes is None:
            start, end = _parse_time(item.start_time), _parse_time(item.end_time)
            if start and end and end >= start:
                minutes = int((end - start).total_seconds() // 60)
        try:
            minutes = int(minutes or 0)
        except (TypeError, ValueError):
            minutes = 0
        if minutes <= 0:
            minutes = 60  # 无时长信息时给一个可读的默认时长
        item.start_time = cursor
        item.end_time = cursor + timedelta(minutes=minutes)
        item.duration_min = minutes
        cursor = item.end_time
    db.commit()
    return {
        "arranged": len(order),
        "dayId": day_id,
        "useAi": bool(use_ai),
        "aiApplied": ai_applied,
        "conflicts": len(detect_conflicts(order)),
        "items": [
            {
                "id": row.id,
                "start_time": row.start_time.isoformat() if isinstance(row.start_time, datetime) else "",
                "end_time": row.end_time.isoformat() if isinstance(row.end_time, datetime) else "",
                "duration_min": row.duration_min,
            }
            for row in order
        ],
    }
