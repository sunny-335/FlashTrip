"""预订 CRUD：按 trip_id 组织，写端点统一声明 booking:write 权限。"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Body, Depends, Request
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


@router.get("/trips/{trip_id}/bookings")
def list_bookings(trip_id: str, request: Request, db: Session = Depends(get_db),
                  user: Any = Depends(require_permission("trip:read"))):
    rows = db.query(Booking).filter(Booking.trip_id == trip_id).order_by(Booking.created_at.desc()).all()
    return ok([row_to_dict(r) for r in rows], request_id=_rid(request))


@router.post("/trips/{trip_id}/bookings")
def create_booking(trip_id: str, request: Request, payload: dict = Body(default={}),
                   db: Session = Depends(get_db),
                   user: Any = Depends(require_permission("booking:write"))):
    obj = Booking(trip_id=trip_id)
    apply_payload(obj, payload)
    db.add(obj)
    db.commit()
    data = row_to_dict(obj)
    emit(trip_id, "booking.created", data, getattr(user, "id", None))
    return ok(data, request_id=_rid(request))


@router.get("/trips/{trip_id}/bookings/{item_id}")
def get_booking(trip_id: str, item_id: str, request: Request, db: Session = Depends(get_db),
                user: Any = Depends(require_permission("trip:read"))):
    return ok(row_to_dict(_get(db, trip_id, item_id)), request_id=_rid(request))


@router.put("/trips/{trip_id}/bookings/{item_id}")
def update_booking(trip_id: str, item_id: str, request: Request, payload: dict = Body(default={}),
                   db: Session = Depends(get_db),
                   user: Any = Depends(require_permission("booking:write"))):
    obj = _get(db, trip_id, item_id)
    apply_payload(obj, payload)
    db.commit()
    data = row_to_dict(obj)
    emit(trip_id, "booking.updated", data, getattr(user, "id", None))
    return ok(data, request_id=_rid(request))


@router.delete("/trips/{trip_id}/bookings/{item_id}")
def delete_booking(trip_id: str, item_id: str, request: Request, db: Session = Depends(get_db),
                   user: Any = Depends(require_permission("booking:write"))):
    obj = _get(db, trip_id, item_id)
    obj.deleted_at = datetime.now(timezone.utc)
    db.commit()
    emit(trip_id, "booking.deleted", {"id": item_id}, getattr(user, "id", None))
    return ok({"id": item_id, "deleted": True}, request_id=_rid(request))
