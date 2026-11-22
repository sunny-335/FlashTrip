"""公开分享服务：DB 只存 sha256(token)，一次性明文仅在创建响应里返回。

public_view 为公开只读视图，按 include_* 逐项裁剪；费用默认不公开，
旅途瞬间仅汇总 is_public=True 的记录；每次访问 view_count +1。
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from app.core.errors import AppError, ErrorCode
from app.models.booking import Booking
from app.models.expense import Expense
from app.models.moment import Moment
from app.models.packing import PackingItem, PackingList
from app.models.share import ShareLink
from app.models.transport import Transport
from app.models.trip import Trip

_TRIP_FIELDS = ("id", "title", "destination", "start_date", "end_date", "status", "cover_url")
_TRANSPORT_FIELDS = ("id", "mode", "from_name", "to_name", "depart_at", "arrive_at", "carrier", "seat")
_BOOKING_FIELDS = ("id", "type", "vendor", "holder", "start_at", "end_at", "status", "note")
_EXPENSE_FIELDS = ("id", "category", "amount", "currency", "occurred_at", "note")
_MOMENT_FIELDS = ("id", "content", "mood", "lng", "lat", "taken_at", "media_json")


def _utc_naive() -> datetime:
    """SQLite 取回的 DateTime 常为 naive，统一用 naive UTC 比较。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _as_naive(value: Any) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=None) if getattr(value, "tzinfo", None) else value


def _iso(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return "" if value is None else str(value)


def _hash(token: str) -> str:
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


def _project(row: Any, fields: tuple[str, ...]) -> dict:
    """按白名单裁剪 ORM 行；复用 row_to_dict 处理日期/Decimal 序列化。"""
    from app.services.sync_service import row_to_dict

    data = row_to_dict(row)
    return {key: data.get(key) for key in fields if key in data}


def _share_dict(row: ShareLink) -> dict:
    """列表/详情字典：绝不含 token 或 token_hash。"""
    return {
        "id": row.id,
        "trip_id": row.trip_id,
        "title": row.title,
        "include_transports": bool(row.include_transports),
        "include_bookings": bool(row.include_bookings),
        "include_packing": bool(row.include_packing),
        "include_expenses": bool(row.include_expenses),
        "include_moments": bool(row.include_moments),
        "expires_at": _iso(row.expires_at),
        "revoked_at": _iso(row.revoked_at),
        "created_by": row.created_by,
        "view_count": int(row.view_count or 0),
        "created_at": _iso(row.created_at),
    }


def create_share(db, trip_id: str, *, title: str = "",
                 include_transports: bool = True, include_bookings: bool = True,
                 include_packing: bool = True, include_expenses: bool = False,
                 include_moments: bool = False, expires_days: int = 30,
                 created_by: str | None = None) -> dict:
    """创建分享链接；明文 token 只在返回的 url/token 里出现一次。"""
    token = secrets.token_urlsafe(24)
    expires_at = _utc_naive() + timedelta(days=int(expires_days)) if expires_days else None
    row = ShareLink(
        trip_id=trip_id,
        token_hash=_hash(token),
        title=title or "",
        include_transports=bool(include_transports),
        include_bookings=bool(include_bookings),
        include_packing=bool(include_packing),
        include_expenses=bool(include_expenses),
        include_moments=bool(include_moments),
        expires_at=expires_at,
        created_by=created_by,
    )
    db.add(row)
    db.commit()
    result = _share_dict(row)
    result["token"] = token
    result["url"] = f"/share/{token}"
    return result


def validate(db, token: str) -> ShareLink:
    """校验 hash 等值 + revoked_at / expires_at / 软删；失败统一 NOT_FOUND。"""
    row = db.query(ShareLink).filter(ShareLink.token_hash == _hash(token)).first()
    if row is None or row.revoked_at is not None:
        raise AppError(ErrorCode.NOT_FOUND, "分享链接无效或已过期")
    expires = _as_naive(row.expires_at)
    if expires is not None and expires <= _utc_naive():
        raise AppError(ErrorCode.NOT_FOUND, "分享链接无效或已过期")
    return row


def list_shares(db, trip_id: str) -> list[dict]:
    """列出行程的分享链接（不含 token）。"""
    rows = (
        db.query(ShareLink)
        .filter(ShareLink.trip_id == trip_id)
        .order_by(ShareLink.created_at.desc())
        .all()
    )
    return [_share_dict(row) for row in rows]


def revoke_share(db, trip_id: str, share_id: str) -> dict:
    """撤销分享（软状态标记，不物理删除，保留审计）。"""
    row = db.get(ShareLink, share_id)
    if row is None or row.trip_id != trip_id:
        raise AppError(ErrorCode.NOT_FOUND, "分享链接不存在")
    row.revoked_at = _utc_naive()
    db.commit()
    return {"id": share_id, "revoked": True}


# ---------------------------------------------------------------- 公开视图组装

def _transport_rows(db, trip_id: str) -> list[dict]:
    rows = db.query(Transport).filter(Transport.trip_id == trip_id).all()
    return [_project(row, _TRANSPORT_FIELDS) for row in rows]


def _booking_rows(db, trip_id: str) -> list[dict]:
    rows = db.query(Booking).filter(Booking.trip_id == trip_id).all()
    return [_project(row, _BOOKING_FIELDS) for row in rows]


def _expense_rows(db, trip_id: str) -> list[dict]:
    rows = db.query(Expense).filter(Expense.trip_id == trip_id).all()
    return [_project(row, _EXPENSE_FIELDS) for row in rows]


def _moment_rows(db, trip_id: str) -> list[dict]:
    # 公开页只汇总显式设为公开的旅途瞬间
    rows = db.query(Moment).filter(
        Moment.trip_id == trip_id, Moment.is_public.is_(True)
    ).all()
    return [_project(row, _MOMENT_FIELDS) for row in rows]


def _packing_rows(db, trip_id: str) -> list[dict]:
    lists = (
        db.query(PackingList)
        .filter(PackingList.trip_id == trip_id)
        .order_by(PackingList.sort_key.asc())
        .all()
    )
    out: list[dict] = []
    for packing_list in lists:
        items = (
            db.query(PackingItem)
            .filter(PackingItem.list_id == packing_list.id)
            .order_by(PackingItem.sort_key.asc())
            .all()
        )
        out.append({
            "list": {"id": packing_list.id, "name": packing_list.name},
            "items": [
                {"id": item.id, "name": item.name,
                 "qty": int(item.qty or 1), "checked": bool(item.checked)}
                for item in items
            ],
        })
    return out


def public_view(db, token: str) -> dict:
    """公开只读视图：按 include_* 组装，公开访问不依赖登录。"""
    link = validate(db, token)
    trip = db.get(Trip, link.trip_id)
    if trip is None:
        raise AppError(ErrorCode.NOT_FOUND, "分享链接无效或已过期")

    result: dict[str, Any] = {
        "trip": _project(trip, _TRIP_FIELDS),
        "transports": _transport_rows(db, link.trip_id) if link.include_transports else [],
        "bookings": _booking_rows(db, link.trip_id) if link.include_bookings else [],
        "packing": _packing_rows(db, link.trip_id) if link.include_packing else [],
        # include_expenses=False 时为 None，且整份视图不含金额字段
        "expenses": _expense_rows(db, link.trip_id) if link.include_expenses else None,
        "moments": _moment_rows(db, link.trip_id) if link.include_moments else [],
        "generated_at": _utc_naive().isoformat(),
    }
    link.view_count = int(link.view_count or 0) + 1
    db.commit()
    return result
