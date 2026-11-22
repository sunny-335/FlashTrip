"""行程 API：CRUD、当前行程、概览、行程日 CRUD。"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.v1.deps import get_db, require_permission, require_user
from app.core.errors import AppError, ErrorCode
from app.core.response import ok
from app.core.security import new_id
from app.models.config import UserPreferences
from app.models.plan import PlanItem
from app.models.trip import Trip, TripDay
from app.schemas.common import dump, dump_many
from app.schemas.trip import (
    TripCreate,
    TripDayCreate,
    TripDayOut,
    TripDayUpdate,
    TripOut,
    TripUpdate,
)

router = APIRouter(tags=["trips"])


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


@router.get("/trips")
def list_trips(
    request: Request,
    status: str = "all",
    db: Session = Depends(get_db),
    user=Depends(require_user),
):
    if status not in ("all", "completed", "active"):
        raise AppError(ErrorCode.VALIDATION, "status 只支持 all / completed / active")
    query = db.query(Trip).filter(Trip.owner_id == user.id)
    if status == "completed":
        query = query.filter(Trip.status == "completed")
    elif status == "active":
        query = query.filter(Trip.status.in_(("planned", "ongoing")))
    rows = query.order_by(Trip.start_date, Trip.created_at).all()
    return ok(dump_many(TripOut, rows), request_id=getattr(request.state, "request_id", ""))


@router.post("/trips")
def create_trip(
    payload: TripCreate,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(require_permission("trip:settings")),
):
    trip = Trip(id=new_id(), owner_id=user.id, **payload.model_dump())
    db.add(trip)
    db.commit()
    return ok(dump(TripOut, trip), request_id=getattr(request.state, "request_id", ""))


@router.get("/trips/{trip_id}")
def get_trip(
    trip_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(require_permission("trip:read")),
):
    return ok(
        dump(TripOut, _trip_or_404(db, trip_id)),
        request_id=getattr(request.state, "request_id", ""),
    )


@router.put("/trips/{trip_id}")
def update_trip(
    trip_id: str,
    payload: TripUpdate,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(require_permission("trip:settings")),
):
    trip = _trip_or_404(db, trip_id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(trip, key, value)
    db.commit()
    return ok(dump(TripOut, trip), request_id=getattr(request.state, "request_id", ""))


@router.delete("/trips/{trip_id}")
def delete_trip(
    trip_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(require_permission("trip:settings")),
):
    trip = _trip_or_404(db, trip_id)
    trip.deleted_at = datetime.now(timezone.utc)  # 软删
    db.commit()
    return ok({"deleted": trip_id}, request_id=getattr(request.state, "request_id", ""))


@router.put("/trips/{trip_id}/current")
def set_current_trip(
    trip_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(require_permission("trip:settings")),
):
    """设置当前行程：写入 UserPreferences.current_trip_id（不修改行程本身）。"""
    _trip_or_404(db, trip_id)
    prefs = db.get(UserPreferences, user.id)
    if prefs is None:
        db.add(
            UserPreferences(
                user_id=user.id,
                current_trip_id=trip_id,
                theme="light",
                default_map_provider_id="openfreemap",
                ai_tools_enabled=False,
            )
        )
    else:
        prefs.current_trip_id = trip_id
    db.commit()
    return ok({"current_trip_id": trip_id}, request_id=getattr(request.state, "request_id", ""))


@router.get("/trips/{trip_id}/overview")
def trip_overview(
    trip_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(require_permission("trip:read")),
):
    trip = _trip_or_404(db, trip_id)
    days_count = (
        db.execute(
            text("SELECT COUNT(*) FROM trip_days WHERE trip_id = :t AND deleted_at IS NULL"),
            {"t": trip_id},
        ).scalar()
        or 0
    )
    items = db.query(PlanItem).filter(PlanItem.trip_id == trip_id).all()
    planned = sum(1 for item in items if item.day_id is not None)
    geo = sum(1 for item in items if item.lng is not None and item.lat is not None)
    return ok(
        {
            "trip": dump(TripOut, trip),
            "days_count": int(days_count),
            "item_count": len(items),
            "planned_count": planned,
            "unplanned_count": len(items) - planned,
            "geocoded_count": geo,
        },
        request_id=getattr(request.state, "request_id", ""),
    )


# ---------------------------------------------------------------- 行程日

@router.get("/trips/{trip_id}/days")
def list_days(
    trip_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(require_permission("trip:read")),
):
    _trip_or_404(db, trip_id)
    rows = (
        db.query(TripDay)
        .filter(TripDay.trip_id == trip_id)
        .order_by(TripDay.sort_key, TripDay.day_index)
        .all()
    )
    return ok(dump_many(TripDayOut, rows), request_id=getattr(request.state, "request_id", ""))


@router.post("/trips/{trip_id}/days")
def create_day(
    trip_id: str,
    payload: TripDayCreate,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(require_permission("plan:write")),
):
    _trip_or_404(db, trip_id)
    day_index = payload.day_index
    if day_index is None:
        mx = db.execute(
            text("SELECT MAX(day_index) FROM trip_days WHERE trip_id = :t AND deleted_at IS NULL"),
            {"t": trip_id},
        ).scalar()
        day_index = int(mx or 0) + 1
    exists = (
        db.query(TripDay)
        .filter(TripDay.trip_id == trip_id, TripDay.day_index == day_index)
        .first()
    )
    if exists is not None:
        raise AppError(ErrorCode.CONFLICT, "该天序号已存在")
    data = payload.model_dump(exclude={"day_index", "sort_key"})
    day = TripDay(
        id=new_id(),
        trip_id=trip_id,
        day_index=day_index,
        sort_key=payload.sort_key or f"d{day_index:06d}",
        **data,
    )
    db.add(day)
    db.commit()
    return ok(dump(TripDayOut, day), request_id=getattr(request.state, "request_id", ""))


@router.put("/trips/{trip_id}/days/{day_id}")
def update_day(
    trip_id: str,
    day_id: str,
    payload: TripDayUpdate,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(require_permission("plan:write")),
):
    day = _day_or_404(db, trip_id, day_id)
    changes = payload.model_dump(exclude_unset=True)
    new_index = changes.get("day_index")
    if new_index is not None and new_index != day.day_index:
        clash = (
            db.query(TripDay)
            .filter(
                TripDay.trip_id == trip_id,
                TripDay.day_index == new_index,
                TripDay.id != day_id,
            )
            .first()
        )
        if clash is not None:
            raise AppError(ErrorCode.CONFLICT, "该天序号已存在")
    for key, value in changes.items():
        if key == "sort_key" and not value:
            continue
        setattr(day, key, value)
    db.commit()
    return ok(dump(TripDayOut, day), request_id=getattr(request.state, "request_id", ""))


@router.delete("/trips/{trip_id}/days/{day_id}")
def delete_day(
    trip_id: str,
    day_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(require_permission("plan:write")),
):
    day = _day_or_404(db, trip_id, day_id)
    # 该天的条目回到待规划池，避免悬挂 day_id
    for item in (
        db.query(PlanItem)
        .filter(PlanItem.trip_id == trip_id, PlanItem.day_id == day_id)
        .all()
    ):
        item.day_id = None
    day.deleted_at = datetime.now(timezone.utc)
    db.commit()
    return ok({"deleted": day_id}, request_id=getattr(request.state, "request_id", ""))
