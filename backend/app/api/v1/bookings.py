"""预订 CRUD：按 trip_id 组织，写端点统一声明 booking:write 权限。

支持把预订归集到某个行程日（day_id）或计划项（plan_item_id），
二者必须属于同一行程，否则返回 VALIDATION。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Body, Depends, Query, Request
from sqlalchemy.orm import Session

from app.api.v1.deps import get_db, require_permission
from app.core.errors import AppError, ErrorCode
from app.core.response import ok
from app.models.booking import Booking
from app.services.sync_service import apply_payload, emit, row_to_dict

router = APIRouter(tags=["bookings"])


def _rid(request: Request) -> str:
    return getattr(request.state, "request_id", "")


def _get(db: Session, trip_id: str, item_id: str) -> Booking:
    obj = db.get(Booking, item_id)
    if obj is None or obj.trip_id != trip_id:
        raise AppError(ErrorCode.NOT_FOUND, "预订记录不存在")
    return obj


def _normalize_payload(payload: dict) -> dict:
    """兼容前端 camelCase 关联键，统一成模型列名。"""
    data = dict(payload or {})
    for alias, key in (("dayId", "day_id"), ("planItemId", "plan_item_id")):
        if alias in data:
            data.setdefault(key, data.pop(alias))
        else:
            data.pop(alias, None)
    return data


def _validate_links(db: Session, trip_id: str, data: dict) -> None:
    """day_id / plan_item_id 必须属于当前行程。"""
    from app.models.plan import PlanItem
    from app.models.trip import TripDay

    day_id = data.get("day_id")
    if day_id:
        day = db.get(TripDay, str(day_id))
        if day is None or day.trip_id != trip_id:
            raise AppError(ErrorCode.VALIDATION, "所选日期或地点不属于当前行程")
    item_id = data.get("plan_item_id")
    if item_id:
        item = db.get(PlanItem, str(item_id))
        if item is None or item.trip_id != trip_id:
            raise AppError(ErrorCode.VALIDATION, "所选日期或地点不属于当前行程")


@router.get("/trips/{trip_id}/bookings")
def list_bookings(trip_id: str, request: Request, day_id: str | None = Query(default=None),
                  db: Session = Depends(get_db),
                  user: Any = Depends(require_permission("trip:read"))):
    query = db.query(Booking).filter(Booking.trip_id == trip_id)
    if day_id:
        query = query.filter(Booking.day_id == day_id)
    rows = query.order_by(Booking.created_at.desc()).all()
    return ok([row_to_dict(r) for r in rows], request_id=_rid(request))


@router.post("/trips/{trip_id}/bookings")
def create_booking(trip_id: str, request: Request, payload: dict = Body(default={}),
                   db: Session = Depends(get_db),
                   user: Any = Depends(require_permission("booking:write"))):
    data = _normalize_payload(payload)
    _validate_links(db, trip_id, data)
    obj = Booking(trip_id=trip_id)
    apply_payload(obj, data)
    db.add(obj)
    db.commit()
    out = row_to_dict(obj)
    emit(trip_id, "booking.created", out, getattr(user, "id", None))
    return ok(out, request_id=_rid(request))


@router.get("/trips/{trip_id}/bookings/{item_id}")
def get_booking(trip_id: str, item_id: str, request: Request, db: Session = Depends(get_db),
                user: Any = Depends(require_permission("trip:read"))):
    return ok(row_to_dict(_get(db, trip_id, item_id)), request_id=_rid(request))


@router.put("/trips/{trip_id}/bookings/{item_id}")
def update_booking(trip_id: str, item_id: str, request: Request, payload: dict = Body(default={}),
                   db: Session = Depends(get_db),
                   user: Any = Depends(require_permission("booking:write"))):
    obj = _get(db, trip_id, item_id)
    data = _normalize_payload(payload)
    _validate_links(db, trip_id, data)
    apply_payload(obj, data)
    db.commit()
    out = row_to_dict(obj)
    emit(trip_id, "booking.updated", out, getattr(user, "id", None))
    return ok(out, request_id=_rid(request))


@router.delete("/trips/{trip_id}/bookings/{item_id}")
def delete_booking(trip_id: str, item_id: str, request: Request, db: Session = Depends(get_db),
                   user: Any = Depends(require_permission("booking:write"))):
    obj = _get(db, trip_id, item_id)
    obj.deleted_at = datetime.now(timezone.utc)
    db.commit()
    emit(trip_id, "booking.deleted", {"id": item_id}, getattr(user, "id", None))
    return ok({"id": item_id, "deleted": True}, request_id=_rid(request))
