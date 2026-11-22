"""权限服务：owner/admin 直通，成员按协作表判定；协作表未就绪时安全降级为只读。

协作模型（M5）尚未落盘时，本模块绝不抛表不存在异常，而是返回 False，
保证「默认只读」的安全语义在所有阶段成立。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.api.v1.deps import DEFAULT_PERMISSION_KEYS, PERMISSION_KEYS
from app.core.errors import AppError, ErrorCode


def all_permission_keys() -> tuple[str, ...]:
    return PERMISSION_KEYS


def default_matrix() -> dict[str, bool]:
    """默认权限矩阵：仅 trip:read 放行。"""
    return {key: key in DEFAULT_PERMISSION_KEYS for key in PERMISSION_KEYS}


def _is_owner_or_admin(user: Any, trip: Any) -> bool:
    if trip is None:
        return False
    if getattr(trip, "owner_id", None) == getattr(user, "id", None):
        return True
    return getattr(user, "role", "") in ("owner", "admin")


def has_permission(db: Session, user: Any, trip: Any, key: str) -> bool:
    if key not in PERMISSION_KEYS:
        raise ValueError(f"未知权限点: {key}")
    if _is_owner_or_admin(user, trip):
        return True
    try:
        from app.models.collab import Permission, TripMember

        trip_id = getattr(trip, "id", None)
        member = (
            db.query(TripMember)
            .filter(TripMember.trip_id == trip_id, TripMember.user_id == getattr(user, "id", None))
            .first()
        )
        if member is None:
            return False
        granted = (
            db.query(Permission)
            .filter(
                Permission.trip_member_id == member.id,
                Permission.permission_key == key,
                Permission.granted.is_(True),
            )
            .first()
        )
        return granted is not None
    except Exception:  # noqa: BLE001  协作表未就绪 → 默认只读
        return False


def effective_permissions(db: Session, user: Any, trip: Any) -> dict[str, bool]:
    if _is_owner_or_admin(user, trip):
        return {key: True for key in PERMISSION_KEYS}
    return {key: has_permission(db, user, trip, key) for key in PERMISSION_KEYS}


def assert_permission(db: Session, user: Any, trip: Any, key: str) -> None:
    if not has_permission(db, user, trip, key):
        raise AppError(ErrorCode.FORBIDDEN, f"缺少权限：{key}（默认只读）")
