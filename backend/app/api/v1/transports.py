"""交通 CRUD：坐标按 WGS84 入库，写端点声明 transport:write 权限。

支持按行程日（day_id）/ 计划项（plan_item_id）归集，二者必须属于同一行程。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Body, Depends, Query, Request
from sqlalchemy.orm import Session

from app.api.v1.deps import get_db, require_permission
from app.core.errors import AppError, ErrorCode
from app.core.response import ok
from app.models.transport import Transport
from app.services.sync_service import apply_payload, emit, row_to_dict

router = APIRouter(tags=["transports"])


def _rid(request: Request) -> str:
    return getattr(request.state, "request_id", "")


def _get(db: Session, trip_id: str, item_id: str) -> Transport:
    obj = db.get(Transport, item_id)
    if obj is None or obj.trip_id != trip_id:
        raise AppError(ErrorCode.NOT_FOUND, "交通记录不存在")
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


@router.get("/trips/{trip_id}/transports")
def list_transports(trip_id: str, request: Request, day_id: str | None = Query(default=None),
                    db: Session = Depends(get_db),
                    user: Any = Depends(require_permission("trip:read"))):
    query = db.query(Transport).filter(Transport.trip_id == trip_id)
    if day_id:
        query = query.filter(Transport.day_id == day_id)
    rows = query.order_by(Transport.sort_key.asc()).all()
    return ok([row_to_dict(r) for r in rows], request_id=_rid(request))


@router.post("/trips/{trip_id}/transports")
def create_transport(trip_id: str, request: Request, payload: dict = Body(default={}),
                     db: Session = Depends(get_db),
                     user: Any = Depends(require_permission("transport:write"))):
    data = _normalize_payload(payload)
    _validate_links(db, trip_id, data)
    obj = Transport(trip_id=trip_id)
    apply_payload(obj, data)
    db.add(obj)
    db.commit()
    out = row_to_dict(obj)
    emit(trip_id, "transport.created", out, getattr(user, "id", None))
    return ok(out, request_id=_rid(request))


@router.get("/trips/{trip_id}/transports/{item_id}")
def get_transport(trip_id: str, item_id: str, request: Request, db: Session = Depends(get_db),
                  user: Any = Depends(require_permission("trip:read"))):
    return ok(row_to_dict(_get(db, trip_id, item_id)), request_id=_rid(request))


@router.put("/trips/{trip_id}/transports/{item_id}")
def update_transport(trip_id: str, item_id: str, request: Request, payload: dict = Body(default={}),
                     db: Session = Depends(get_db),
                     user: Any = Depends(require_permission("transport:write"))):
    obj = _get(db, trip_id, item_id)
    data = _normalize_payload(payload)
    _validate_links(db, trip_id, data)
    apply_payload(obj, data)
    db.commit()
    out = row_to_dict(obj)
    emit(trip_id, "transport.updated", out, getattr(user, "id", None))
    return ok(out, request_id=_rid(request))


@router.delete("/trips/{trip_id}/transports/{item_id}")
def delete_transport(trip_id: str, item_id: str, request: Request, db: Session = Depends(get_db),
                     user: Any = Depends(require_permission("transport:write"))):
    obj = _get(db, trip_id, item_id)
    obj.deleted_at = datetime.now(timezone.utc)
    db.commit()
    emit(trip_id, "transport.deleted", {"id": item_id}, getattr(user, "id", None))
    return ok({"id": item_id, "deleted": True}, request_id=_rid(request))
