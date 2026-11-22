"""认证 API：httpOnly cookie 会话、首次设密与改密。

POST /auth/set-password 同时支持两条路径：
  1) Authorization: Bearer <setupToken>（邀请 accept 未带密码时签发）：
     校验 setup scope -> 设密 -> 激活成员/权限/次数 -> 签发全量 token 并写 cookie。
  2) 普通已登录用户首次设密：保持原有 current_user_optional + set_initial_password 行为。
"""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.v1.deps import COOKIE_NAME, current_user_optional, get_db, require_user
from app.core.errors import AppError, ErrorCode
from app.core.response import ok
from app.core.security import decode_access_token
from app.schemas.common import dump
from app.schemas.user import ChangePasswordIn, LoginIn, SetPasswordIn, UserOut
from app.services import auth_service, invite_service

router = APIRouter(tags=["auth"])

_COOKIE_MAX_AGE = 7 * 24 * 3600  # 与 create_access_token 默认 TTL 对齐


def _with_cookie(resp: JSONResponse, token: str) -> JSONResponse:
    resp.set_cookie(
        COOKIE_NAME,
        token,
        max_age=_COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        path="/",
        secure=False,  # 由部署层 HTTPS 反向代理终止；容器内部为 HTTP
    )
    return resp


def _bearer_claims(request: Request) -> dict | None:
    """解析 Authorization: Bearer 或 cookie 中的 token；失败返回 None。"""
    auth = request.headers.get("Authorization", "")
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    try:
        return decode_access_token(token)
    except Exception:  # noqa: BLE001  非法/过期 token 按未登录处理
        return None


@router.post("/auth/password-strength")
def password_strength_api(request: Request, payload: dict = Body(default={})):
    """公开：实时评估密码强度，供前端强度条 / 分级提示使用（不落库、不校验登录态）。

    body: {password: string, is_admin?: bool}；返回 password_strength() 的全部指标，
    另附 isAdmin 与 meetsPolicy（按是否管理员分别取 adminOk / valid）。
    """
    from app.services.password_policy import password_strength

    info = password_strength(str(payload.get("password") or ""))
    is_admin = bool(payload.get("is_admin"))
    info["isAdmin"] = is_admin
    info["meetsPolicy"] = bool(info.get("adminOk")) if is_admin else bool(info.get("valid"))
    return ok(info, request_id=getattr(request.state, "request_id", ""))


@router.post("/auth/login")
def login(payload: LoginIn, request: Request, db: Session = Depends(get_db)):
    user = auth_service.authenticate(db, payload.username, payload.password)
    token = auth_service.issue_token(user, scope=auth_service.token_scope_for(user))
    resp = ok(dump(UserOut, user), request_id=getattr(request.state, "request_id", ""))
    return _with_cookie(resp, token)


@router.post("/auth/logout")
def logout(request: Request):
    resp = ok({"logged_out": True}, request_id=getattr(request.state, "request_id", ""))
    resp.delete_cookie(COOKIE_NAME, path="/")
    return resp


@router.post("/auth/refresh")
def refresh(request: Request, user=Depends(current_user_optional)):
    if user is None:
        raise AppError(ErrorCode.UNAUTHORIZED, "登录已失效，请重新登录")
    token = auth_service.issue_token(user, scope=auth_service.token_scope_for(user))
    resp = ok(dump(UserOut, user), request_id=getattr(request.state, "request_id", ""))
    return _with_cookie(resp, token)


@router.get("/auth/me")
def me(request: Request, user=Depends(require_user)):
    return ok(dump(UserOut, user), request_id=getattr(request.state, "request_id", ""))


@router.post("/auth/set-password")
def set_password(
    payload: SetPasswordIn,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(current_user_optional),
):
    """邀请成员首次设密：setup scope 凭证走统一激活流程，普通用户保持原逻辑。"""
    claims = _bearer_claims(request)
    # setup = 邀请首次设密；reset = 邀请 force_reset 强制改密，两者共用统一激活流程
    if claims is not None and claims.get("scope") in ("setup", "reset"):
        result = invite_service.activate_from_setup(db, claims, payload.new_password)
        resp = ok(
            {"tripId": result["tripId"], "scope": "full"},
            request_id=getattr(request.state, "request_id", ""),
        )
        return _with_cookie(resp, result["accessToken"])
    # 普通已登录用户首次设密（原行为不变）
    if user is None:
        raise AppError(ErrorCode.UNAUTHORIZED, "请先使用邀请链接登录")
    updated = auth_service.set_initial_password(db, user, payload.new_password)
    resp = ok(dump(UserOut, updated), request_id=getattr(request.state, "request_id", ""))
    return _with_cookie(resp, auth_service.issue_token(updated))


@router.post("/auth/change-password")
def change_password(
    payload: ChangePasswordIn,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(require_user),
):
    updated = auth_service.change_password(db, user, payload.old_password, payload.new_password)
    return ok(dump(UserOut, updated), request_id=getattr(request.state, "request_id", ""))
