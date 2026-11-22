"""协作：成员与权限矩阵、SSE 同步流与 REST 降级补发。"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Body, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.v1.deps import PERMISSION_KEYS, get_db, require_permission
from app.core.errors import AppError, ErrorCode
from app.core.response import ok
from app.models.collab import Permission, TripMember
from app.services.sync_service import emit, events_since, row_to_dict, subscribe

router = APIRouter(tags=["collab"])

_SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


def _rid(request: Request) -> str:
    return getattr(request.state, "request_id", "")


def _user_brief(db: Session, user_id: str) -> dict:
    try:
        from app.models.user import User

        user = db.get(User, user_id)
        if user is None:
            return {"id": user_id}
        brief: dict[str, Any] = {"id": user_id}
        for field in ("username", "display_name", "email", "phone", "role"):
            if hasattr(user, field):
                brief[field] = getattr(user, field)
        return brief
    except Exception:  # noqa: BLE001  用户模型未就绪时仅返回 id
        return {"id": user_id}


def _permissions(db: Session, member_id: str) -> dict[str, bool]:
    rows = db.query(Permission).filter(Permission.trip_member_id == member_id).all()
    return {row.permission_key: bool(row.granted) for row in rows}


def _member_view(db: Session, member: TripMember) -> dict:
    return {**row_to_dict(member), "user": _user_brief(db, member.user_id),
            "permissions": _permissions(db, member.id)}


def _get_member(db: Session, trip_id: str, member_id: str) -> TripMember:
    member = db.get(TripMember, member_id)
    if member is None or member.trip_id != trip_id:
        raise AppError(ErrorCode.NOT_FOUND, "成员不存在")
    return member


@router.get("/trips/{trip_id}/members")
def list_members(trip_id: str, request: Request, db: Session = Depends(get_db),
                 user: Any = Depends(require_permission("trip:read"))):
    rows = db.query(TripMember).filter(TripMember.trip_id == trip_id).order_by(TripMember.joined_at.asc()).all()
    return ok([_member_view(db, row) for row in rows], request_id=_rid(request))


@router.put("/trips/{trip_id}/members/{member_id}/permissions")
def update_permissions(trip_id: str, member_id: str, request: Request,
                       payload: dict = Body(default={}), db: Session = Depends(get_db),
                       user: Any = Depends(require_permission("member:manage"))):
    member = _get_member(db, trip_id, member_id)
    incoming = payload.get("permissions")
    if isinstance(incoming, list):
        incoming = {key: True for key in incoming}
    elif not isinstance(incoming, dict):
        incoming = payload.get("permission_keys")
        incoming = {key: True for key in incoming} if isinstance(incoming, list) else {}
    unknown = [key for key in incoming if key not in PERMISSION_KEYS]
    if unknown:
        raise AppError(ErrorCode.VALIDATION, f"未知权限点：{'、'.join(map(str, unknown))}")

    for key in PERMISSION_KEYS:
        granted = bool(incoming.get(key, False))
        record = (
            db.query(Permission)
            .filter(Permission.trip_member_id == member.id, Permission.permission_key == key)
            .first()
        )
        if record is None:
            db.add(Permission(trip_member_id=member.id, permission_key=key,
                              granted=granted, granted_by=getattr(user, "id", None)))
        else:
            record.granted = granted
            record.granted_by = getattr(user, "id", None)
    db.commit()
    data = {"memberId": member_id, "permissions": _permissions(db, member.id)}
    emit(trip_id, "member.permissions_updated", data, getattr(user, "id", None))
    return ok(data, request_id=_rid(request))


@router.delete("/trips/{trip_id}/members/{member_id}")
def remove_member(trip_id: str, member_id: str, request: Request, db: Session = Depends(get_db),
                  user: Any = Depends(require_permission("member:manage"))):
    member = _get_member(db, trip_id, member_id)
    if member.role in ("owner", "admin"):
        raise AppError(ErrorCode.FORBIDDEN, "不能移除行程所有者")
    member.deleted_at = datetime.now(timezone.utc)
    for record in db.query(Permission).filter(Permission.trip_member_id == member.id).all():
        record.deleted_at = datetime.now(timezone.utc)
    db.commit()
    emit(trip_id, "member.removed", {"id": member_id}, getattr(user, "id", None))
    return ok({"id": member_id, "deleted": True}, request_id=_rid(request))


@router.get("/trips/{trip_id}/events/since")
def events_since_endpoint(trip_id: str, request: Request, cursor: int = Query(default=0, ge=0),
                          db: Session = Depends(get_db),
                          user: Any = Depends(require_permission("trip:read"))):
    """禁用 SSE 时的轮询降级：返回 id > cursor 的增量事件。"""
    return ok({"events": events_since(trip_id, cursor), "cursor": cursor}, request_id=_rid(request))


@router.get("/trips/{trip_id}/events")
def events_stream(trip_id: str, request: Request, last_event_id: int = Query(default=0, ge=0),
                  db: Session = Depends(get_db),
                  user: Any = Depends(require_permission("trip:read"))):
    """SSE 单向广播；支持 Last-Event-ID 头与查询参数两种补发游标。"""
    raw = request.headers.get("Last-Event-ID")
    try:
        cursor = int(raw) if raw else int(last_event_id or 0)
    except (TypeError, ValueError):
        cursor = 0
    return StreamingResponse(
        subscribe(trip_id, cursor),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )
