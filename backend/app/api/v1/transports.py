"""交通 CRUD：坐标按 WGS84 入库，写端点声明 transport:write 权限。"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Body, Depends, Request
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


@router.get("/trips/{trip_id}/transports")
def list_transports(trip_id: str, request: Request, db: Session = Depends(get_db),
                    user: Any = Depends(require_permission("trip:read"))):
    rows = db.query(Transport).filter(Transport.trip_id == trip_id).order_by(Transport.sort_key.asc()).all()
    return ok([row_to_dict(r) for r in rows], request_id=_rid(request))


@router.post("/trips/{trip_id}/transports")
def create_transport(trip_id: str, request: Request, payload: dict = Body(default={}),
                     db: Session = Depends(get_db),
                     user: Any = Depends(require_permission("transport:write"))):
    obj = Transport(trip_id=trip_id)
    apply_payload(obj, payload)
    db.add(obj)
    db.commit()
    data = row_to_dict(obj)
    emit(trip_id, "transport.created", data, getattr(user, "id", None))
    return ok(data, request_id=_rid(request))


@router.get("/trips/{trip_id}/transports/{item_id}")
def get_transport(trip_id: str, item_id: str, request: Request, db: Session = Depends(get_db),
                  user: Any = Depends(require_permission("trip:read"))):
    return ok(row_to_dict(_get(db, trip_id, item_id)), request_id=_rid(request))


@router.put("/trips/{trip_id}/transports/{item_id}")
def update_transport(trip_id: str, item_id: str, request: Request, payload: dict = Body(default={}),
                     db: Session = Depends(get_db),
                     user: Any = Depends(require_permission("transport:write"))):
    obj = _get(db, trip_id, item_id)
    apply_payload(obj, payload)
    db.commit()
    data = row_to_dict(obj)
    emit(trip_id, "transport.updated", data, getattr(user, "id", None))
    return ok(data, request_id=_rid(request))


@router.delete("/trips/{trip_id}/transports/{item_id}")
def delete_transport(trip_id: str, item_id: str, request: Request, db: Session = Depends(get_db),
                     user: Any = Depends(require_permission("transport:write"))):
    obj = _get(db, trip_id, item_id)
    obj.deleted_at = datetime.now(timezone.utc)
    db.commit()
    emit(trip_id, "transport.deleted", {"id": item_id}, getattr(user, "id", None))
    return ok({"id": item_id, "deleted": True}, request_id=_rid(request))
