"""依赖注入：数据库会话、当前用户、细粒度权限。

约定：所有行程相关路径参数名为 trip_id（亦兼容 id），由 request.path_params 读取。
默认只读：无对应 permission 记录或 granted=False 一律 403。
"""
from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.core.security import decode_access_token
from app.db.session import get_db

PERMISSION_KEYS = (
    "trip:read", "plan:write", "booking:write", "transport:write", "expense:write",
    "packing:write", "moment:write", "member:manage", "trip:settings", "ai:use",
)
DEFAULT_PERMISSION_KEYS = ("trip:read",)
COOKIE_NAME = "flashtrip_token"


def _token_from_request(request: Request) -> str | None:
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.cookies.get(COOKIE_NAME)


def current_user_optional(request: Request, db: Session = Depends(get_db)) -> Any | None:
    token = _token_from_request(request)
    if not token:
        return None
    try:
        payload = decode_access_token(token)
    except Exception:  # noqa: BLE001
        return None
    if payload.get("type") != "access":
        return None
    try:
        from app.models.user import User  # 延迟导入，避免 M0 阶段模型未就绪

        return db.get(User, payload.get("sub"))
    except Exception:  # noqa: BLE001  表不存在时视为未登录
        return None


def require_user(request: Request, db: Session = Depends(get_db)) -> Any:
    user = current_user_optional(request, db)
    if user is None:
        raise AppError(ErrorCode.UNAUTHORIZED, "请先登录")
    if getattr(user, "must_set_password", False):
        raise AppError(ErrorCode.PASSWORD_REQUIRED, "请先设置登录密码")
    return user


def _trip_id(request: Request, kwargs: dict) -> str | None:
    return kwargs.get("trip_id") or request.path_params.get("trip_id") or request.path_params.get("id")


def require_permission(key: str):
    """生成权限依赖；写端点统一使用 Depends(require_permission("plan:write"))。"""
    if key not in PERMISSION_KEYS:
        raise ValueError(f"未知权限点: {key}")

    def _dependency(request: Request, db: Session = Depends(get_db), user: Any = Depends(require_user)) -> Any:
        trip_id = _trip_id(request, {})
        if not trip_id:
            # 非行程级端点（如 /trips 创建）只需登录
            return user
        try:
            from app.models.trip import Trip
            from app.models.collab import Permission, TripMember

            trip = db.get(Trip, trip_id)
            if trip is None:
                raise AppError(ErrorCode.NOT_FOUND, "行程不存在")
            if getattr(trip, "owner_id", None) == user.id or getattr(user, "role", "") in ("owner", "admin"):
                return user
            member = (
                db.query(TripMember)
                .filter(TripMember.trip_id == trip_id, TripMember.user_id == user.id)
                .first()
            )
            if member is None:
                raise AppError(ErrorCode.FORBIDDEN, "非行程成员")
            granted = (
                db.query(Permission)
                .filter(
                    Permission.trip_member_id == member.id,
                    Permission.permission_key == key,
                    Permission.granted.is_(True),
                )
                .first()
            )
            if granted is None:
                raise AppError(ErrorCode.FORBIDDEN, f"缺少权限：{key}（默认只读）")
            return user
        except AppError:
            raise
        except Exception as exc:  # noqa: BLE001  协作表未就绪时安全拒绝
            raise AppError(ErrorCode.FORBIDDEN, "权限校验不可用（默认只读）") from exc

    return _dependency


def get_db_dep() -> Iterator[Session]:
    yield from get_db()
