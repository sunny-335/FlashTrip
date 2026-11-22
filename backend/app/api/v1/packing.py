"""行李清单 CRUD：清单 + 条目两级，写端点声明 packing:write 权限。"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Body, Depends, Request
from sqlalchemy.orm import Session

from app.api.v1.deps import get_db, require_permission
from app.core.errors import AppError, ErrorCode
from app.core.response import ok
from app.models.packing import PackingItem, PackingList
from app.services.sync_service import apply_payload, emit, row_to_dict

router = APIRouter(tags=["packing"])


def _rid(request: Request) -> str:
    return getattr(request.state, "request_id", "")


def _get_list(db: Session, trip_id: str, list_id: str) -> PackingList:
    obj = db.get(PackingList, list_id)
    if obj is None or obj.trip_id != trip_id:
        raise AppError(ErrorCode.NOT_FOUND, "行李清单不存在")
    return obj


def _get_item(db: Session, list_id: str, item_id: str) -> PackingItem:
    obj = db.get(PackingItem, item_id)
    if obj is None or obj.list_id != list_id:
        raise AppError(ErrorCode.NOT_FOUND, "清单条目不存在")
    return obj


def _items(db: Session, list_id: str) -> list[dict]:
    rows = db.query(PackingItem).filter(PackingItem.list_id == list_id).order_by(PackingItem.sort_key.asc()).all()
    return [row_to_dict(r) for r in rows]


@router.get("/trips/{trip_id}/packing/lists")
def list_lists(trip_id: str, request: Request, db: Session = Depends(get_db),
               user: Any = Depends(require_permission("trip:read"))):
    rows = db.query(PackingList).filter(PackingList.trip_id == trip_id).order_by(PackingList.sort_key.asc()).all()
    data = [{**row_to_dict(row), "items": _items(db, row.id)} for row in rows]
    return ok(data, request_id=_rid(request))


@router.post("/trips/{trip_id}/packing/lists")
def create_list(trip_id: str, request: Request, payload: dict = Body(default={}),
                db: Session = Depends(get_db),
                user: Any = Depends(require_permission("packing:write"))):
    obj = PackingList(trip_id=trip_id)
    apply_payload(obj, payload)
    db.add(obj)
    db.commit()
    data = {**row_to_dict(obj), "items": []}
    emit(trip_id, "packing.list_created", data, getattr(user, "id", None))
    return ok(data, request_id=_rid(request))


@router.put("/trips/{trip_id}/packing/lists/{list_id}")
def update_list(trip_id: str, list_id: str, request: Request, payload: dict = Body(default={}),
                db: Session = Depends(get_db),
                user: Any = Depends(require_permission("packing:write"))):
    obj = _get_list(db, trip_id, list_id)
    apply_payload(obj, payload)
    db.commit()
    data = {**row_to_dict(obj), "items": _items(db, list_id)}
    emit(trip_id, "packing.list_updated", data, getattr(user, "id", None))
    return ok(data, request_id=_rid(request))


@router.delete("/trips/{trip_id}/packing/lists/{list_id}")
def delete_list(trip_id: str, list_id: str, request: Request, db: Session = Depends(get_db),
                user: Any = Depends(require_permission("packing:write"))):
    obj = _get_list(db, trip_id, list_id)
    obj.deleted_at = datetime.now(timezone.utc)
    db.commit()
    emit(trip_id, "packing.list_deleted", {"id": list_id}, getattr(user, "id", None))
    return ok({"id": list_id, "deleted": True}, request_id=_rid(request))


@router.get("/trips/{trip_id}/packing/lists/{list_id}/items")
def list_items(trip_id: str, list_id: str, request: Request, db: Session = Depends(get_db),
               user: Any = Depends(require_permission("trip:read"))):
    _get_list(db, trip_id, list_id)
    return ok(_items(db, list_id), request_id=_rid(request))


@router.post("/trips/{trip_id}/packing/lists/{list_id}/items")
def create_item(trip_id: str, list_id: str, request: Request, payload: dict = Body(default={}),
                db: Session = Depends(get_db),
                user: Any = Depends(require_permission("packing:write"))):
    _get_list(db, trip_id, list_id)
    obj = PackingItem(list_id=list_id)
    apply_payload(obj, payload)
    db.add(obj)
    db.commit()
    data = row_to_dict(obj)
    emit(trip_id, "packing.item_created", data, getattr(user, "id", None))
    return ok(data, request_id=_rid(request))


@router.put("/trips/{trip_id}/packing/lists/{list_id}/items/{item_id}")
def update_item(trip_id: str, list_id: str, item_id: str, request: Request,
                payload: dict = Body(default={}), db: Session = Depends(get_db),
                user: Any = Depends(require_permission("packing:write"))):
    _get_list(db, trip_id, list_id)
    obj = _get_item(db, list_id, item_id)
    apply_payload(obj, payload)
    db.commit()
    data = row_to_dict(obj)
    emit(trip_id, "packing.item_updated", data, getattr(user, "id", None))
    return ok(data, request_id=_rid(request))


@router.delete("/trips/{trip_id}/packing/lists/{list_id}/items/{item_id}")
def delete_item(trip_id: str, list_id: str, item_id: str, request: Request,
                db: Session = Depends(get_db),
                user: Any = Depends(require_permission("packing:write"))):
    _get_list(db, trip_id, list_id)
    obj = _get_item(db, list_id, item_id)
    obj.deleted_at = datetime.now(timezone.utc)
    db.commit()
    emit(trip_id, "packing.item_deleted", {"id": item_id, "list_id": list_id}, getattr(user, "id", None))
    return ok({"id": item_id, "deleted": True}, request_id=_rid(request))
