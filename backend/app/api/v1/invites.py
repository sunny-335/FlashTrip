"""邀请：行程内 CRUD + 公开 token 查询与接受。

公开端点不带登录依赖；token 明文只在链接里出现，DB 仅存 hash。
accept 带 password 时一次性完成并签发全量 token + httpOnly cookie；
未带 password 时由 invite_service 抛 PASSWORD_REQUIRED(3002) 并携带 setupToken。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, Request
from sqlalchemy.orm import Session

from app.api.v1.deps import COOKIE_NAME, get_db, require_permission
from app.core.response import ok
from app.services import invite_service

router = APIRouter(tags=["invites"])

_COOKIE_MAX_AGE = 7 * 24 * 3600


def _rid(request: Request) -> str:
    return getattr(request.state, "request_id", "")


def _flag(value: Any, default: bool = False) -> bool:
    """兼容前端传布尔或字符串 'true'/'1'，避免 bool('false') 误判为真。"""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


@router.get("/trips/{trip_id}/invites")
def list_invites(trip_id: str, request: Request, db: Session = Depends(get_db),
                 user: Any = Depends(require_permission("member:manage"))):
    return ok(invite_service.list_invitations(db, trip_id), request_id=_rid(request))


@router.post("/trips/{trip_id}/invites")
def create_invite(trip_id: str, request: Request, payload: dict = Body(default={}),
                  db: Session = Depends(get_db),
                  user: Any = Depends(require_permission("member:manage"))):
    result = invite_service.create_invitation(
        db,
        trip_id=trip_id,
        channel=str(payload.get("channel") or "username"),
        target_value=str(payload.get("target_value") or payload.get("targetValue") or ""),
        permission_keys=payload.get("permission_keys") or payload.get("permissionKeys"),
        expires_days=int(payload.get("expires_days") or payload.get("expiresDays") or 7),
        max_uses=int(payload.get("max_uses") or payload.get("maxUses") or 1),
        created_by=getattr(user, "id", None),
        force_reset=_flag(payload.get("force_reset", payload.get("forceReset"))),
        nickname=payload.get("nickname"),
        email=payload.get("email"),
    )
    return ok(result, request_id=_rid(request))


@router.delete("/trips/{trip_id}/invites/{invite_id}")
def revoke_invite(trip_id: str, invite_id: str, request: Request, db: Session = Depends(get_db),
                  user: Any = Depends(require_permission("member:manage"))):
    data = invite_service.revoke_invitation(db, trip_id, invite_id, getattr(user, "id", None))
    return ok(data, request_id=_rid(request))


@router.get("/invites/{token}")
def get_invite(token: str, request: Request, db: Session = Depends(get_db)):
    """公开：仅在状态校验通过后才返回最小必要信息。"""
    return ok(invite_service.public_info(db, token), request_id=_rid(request))


@router.post("/invites/{token}/accept")
def accept_invite(token: str, request: Request, payload: dict = Body(default={}),
                  db: Session = Depends(get_db)):
    """公开：接受邀请。

    - 带 password：返回 {tripId, scope:'full', userId, accessToken} 并写 httpOnly cookie。
    - 不带 password：invite_service 抛 PASSWORD_REQUIRED(3002)，
      detail 内含 {scope:'setup', setupToken, tripId, userId, invitationId}。
    """
    raw_password = payload.get("password")
    password = None if raw_password is None or raw_password == "" else str(raw_password)
    result = invite_service.accept(
        db, token,
        password=password,
        display_name=payload.get("display_name") or payload.get("displayName") or None,
    )
    # 老用户已有密码且未强制重置：不设 cookie、不消耗次数，前端带 next 跳登录页
    if result.get("action") == "login":
        return ok(
            {"action": "login", "tripId": result["tripId"],
             "next": result.get("next") or f"/invite/{token}"},
            request_id=_rid(request),
        )
    response = ok(
        {
            "tripId": result["tripId"],
            "scope": result["scope"],
            "userId": result["userId"],
            "accessToken": result["accessToken"],
        },
        request_id=_rid(request),
    )
    response.set_cookie(
        COOKIE_NAME,
        result["accessToken"],
        max_age=_COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        path="/",
        secure=False,
    )
    return response
