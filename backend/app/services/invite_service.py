"""邀请服务：随机 token 只存 hash，状态机校验，接受后建用户/成员/权限。

- DB 只存 token_hash；明文仅出现在 /invite/<token> 链接里。
- 过期 / 次数用尽 / 已撤销统一返回 INVITE_INVALID 且不泄露行程信息。
- 新用户 must_set_password=True；未完成设密不发放业务 token（PASSWORD_REQUIRED）。
"""
from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import String, Text

from app.api.v1.deps import DEFAULT_PERMISSION_KEYS, PERMISSION_KEYS
from app.core.errors import AppError, ErrorCode
from app.core.security import create_access_token, hash_password, new_id
from app.models.collab import Invitation, Permission, TripMember

_CHANNEL_COLUMN = {"phone": "phone", "email": "email", "username": "username"}


def hash_token(token: str) -> str:
    """只存哈希，任何情况下不落明文。"""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _utc(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso(value: datetime | None) -> str:
    return _utc(value).isoformat() if value is not None else ""


def _dump(inv: Invitation) -> dict[str, Any]:
    """对外视图：不含 token_hash。"""
    return {
        "id": inv.id,
        "tripId": inv.trip_id,
        "channel": inv.channel,
        "targetValue": inv.target_value,
        "permissionKeys": json.loads(inv.permission_keys_json or "[]"),
        "expiresAt": _iso(inv.expires_at),
        "maxUses": inv.max_uses,
        "usedCount": inv.used_count,
        "revokedAt": _iso(inv.revoked_at) if inv.revoked_at else None,
        "createdBy": inv.created_by,
        "createdAt": _iso(getattr(inv, "created_at", None)),
    }


def _mask_target(value: str) -> str:
    """公开展示时脱敏（不泄露完整手机号/邮箱）。"""
    if "@" in value:
        name, _, domain = value.partition("@")
        return f"{(name[:1] or '*')}***@{domain}"
    if len(value) >= 7:
        return f"{value[:3]}****{value[-4:]}"
    return (value[:1] or "*") + "***"


def create_invitation(db, *, trip_id: str, channel: str, target_value: str,
                      permission_keys: list[str] | None = None, expires_days: int = 7,
                      max_uses: int = 1, created_by: str | None = None) -> dict:
    """创建邀请；返回一次性明文 token（仅此一次，之后无法找回）。"""
    if channel not in _CHANNEL_COLUMN:
        raise AppError(ErrorCode.VALIDATION, "邀请渠道须为 phone / email / username")
    keys = list(permission_keys or DEFAULT_PERMISSION_KEYS)
    invalid = [k for k in keys if k not in PERMISSION_KEYS]
    if invalid:
        raise AppError(ErrorCode.VALIDATION, f"未知权限点：{'、'.join(invalid)}")
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    inv = Invitation(
        id=new_id(),
        trip_id=trip_id,
        token_hash=hash_token(token),
        channel=channel,
        target_value=str(target_value or ""),
        permission_keys_json=json.dumps(keys, ensure_ascii=False),
        expires_at=now + timedelta(days=max(1, int(expires_days))),
        max_uses=max(1, int(max_uses)),
        used_count=0,
        created_by=created_by,
    )
    db.add(inv)
    db.commit()
    return {
        "invitation": _dump(inv),
        "token": token,
        "inviteUrl": f"/invite/{token}",
    }


def validate(db, token: str) -> Invitation:
    """校验状态机；所有失败统一 INVITE_INVALID，不区分原因以免泄露行程。"""
    inv = db.query(Invitation).filter(Invitation.token_hash == hash_token(token)).first()
    now = datetime.now(timezone.utc)
    if (
        inv is None
        or inv.revoked_at is not None
        or _utc(inv.expires_at) <= now
        or inv.used_count >= inv.max_uses
    ):
        raise AppError(ErrorCode.INVITE_INVALID, "邀请无效或已过期")
    return inv


def public_info(db, token: str) -> dict:
    """GET /invites/{token}：校验通过后才展示最小必要信息。"""
    inv = validate(db, token)
    trip_title = ""
    try:
        from app.models.trip import Trip

        trip = db.get(Trip, inv.trip_id)
        if trip is not None:
            trip_title = str(getattr(trip, "title", None) or getattr(trip, "name", None) or "")
    except Exception:  # noqa: BLE001  行程模型未就绪不影响邀请展示
        trip_title = ""
    return {
        "channel": inv.channel,
        "target": _mask_target(inv.target_value),
        "tripTitle": trip_title,
        "permissionKeys": json.loads(inv.permission_keys_json or "[]"),
        "expiresAt": _iso(inv.expires_at),
        "maxUses": inv.max_uses,
        "usedCount": inv.used_count,
        "requiresPassword": True,
    }


def _find_user(db, channel: str, target: str):
    from app.models.user import User

    column = _CHANNEL_COLUMN[channel]
    if not hasattr(User, column) or not target:
        return None
    return db.query(User).filter(getattr(User, column) == target).first()


def _create_user(db, inv: Invitation, password: str | None, display_name: str | None):
    """按 User 模型真实列构造，避免依赖不确定的必填字段。"""
    from app.models.user import User

    columns = {c.name: c for c in User.__table__.columns}
    kwargs: dict[str, Any] = {}
    target = inv.target_value or display_name or f"invite_{new_id()[:12]}"
    if "id" in columns:
        kwargs["id"] = new_id()
    if "username" in columns:
        kwargs["username"] = target if inv.channel == "username" else f"invite_{new_id()[:12]}"
    if "email" in columns and inv.channel == "email":
        kwargs["email"] = target
    if "phone" in columns and inv.channel == "phone":
        kwargs["phone"] = target
    if "display_name" in columns:
        kwargs["display_name"] = str(display_name or target)
    if "password_hash" in columns:
        # 未提供密码时设一个随机不可知口令，必须走 set-password 才能登录
        kwargs["password_hash"] = hash_password(password or secrets.token_urlsafe(24))
    if "role" in columns:
        kwargs["role"] = "member"
    if "must_set_password" in columns:
        kwargs["must_set_password"] = not bool(password)
    for name, column in columns.items():
        if name in kwargs or name in ("created_at", "updated_at", "deleted_at"):
            continue
        if not column.nullable and column.default is None and column.server_default is None:
            if isinstance(column.type, (String, Text)):
                kwargs[name] = ""
    user = User(**kwargs)
    db.add(user)
    db.flush()
    return user


def accept(db, token: str, *, password: str | None = None,
           display_name: str | None = None) -> dict:
    """接受邀请：建用户 + 成员 + 权限（默认 trip:read），未完成设密返回 3002。"""
    inv = validate(db, token)
    now = datetime.now(timezone.utc)
    user = _find_user(db, inv.channel, inv.target_value)
    if user is None:
        user = _create_user(db, inv, password, display_name)
    elif password and getattr(user, "must_set_password", False):
        if hasattr(user, "password_hash"):
            user.password_hash = hash_password(password)
        user.must_set_password = False

    member = (
        db.query(TripMember)
        .filter(TripMember.trip_id == inv.trip_id, TripMember.user_id == user.id)
        .first()
    )
    if member is None:
        member = TripMember(
            id=new_id(), trip_id=inv.trip_id, user_id=user.id, role="member",
            invited_by=inv.created_by, joined_at=now,
        )
        db.add(member)
        db.flush()

    keys = json.loads(inv.permission_keys_json or "[]") or list(DEFAULT_PERMISSION_KEYS)
    for key in keys:
        existing = (
            db.query(Permission)
            .filter(Permission.trip_member_id == member.id, Permission.permission_key == key)
            .first()
        )
        if existing is not None:
            existing.granted = True
        else:
            db.add(Permission(
                id=new_id(), trip_member_id=member.id, permission_key=key,
                granted=True, granted_by=inv.created_by,
            ))
    inv.used_count += 1
    db.commit()

    if getattr(user, "must_set_password", False):
        # 不发放业务 token；只给 setup 作用域凭证供 /auth/set-password 完成设密，
        # require_user 会拒绝该 scope 的用户访问任何业务端点。
        setup_token = create_access_token(
            user.id, extra={"scope": "setup", "role": getattr(user, "role", "member")}
        )
        raise AppError(
            ErrorCode.PASSWORD_REQUIRED,
            "账户已创建，请先设置登录密码后再登录",
            detail=json.dumps(
                {"userId": user.id, "tripId": inv.trip_id, "setupToken": setup_token},
                ensure_ascii=False,
            ),
        )
    return {
        "accessToken": create_access_token(
            user.id, extra={"scope": "full", "role": getattr(user, "role", "member")}
        ),
        "userId": user.id,
        "tripId": inv.trip_id,
    }


def list_invitations(db, trip_id: str) -> list[dict]:
    rows = (
        db.query(Invitation)
        .filter(Invitation.trip_id == trip_id)
        .order_by(Invitation.created_at.desc())
        .all()
    )
    return [_dump(row) for row in rows]


def revoke_invitation(db, trip_id: str, invite_id: str, user_id: str | None) -> dict:
    inv = db.get(Invitation, invite_id)
    if inv is None or inv.trip_id != trip_id:
        raise AppError(ErrorCode.NOT_FOUND, "邀请不存在")
    inv.revoked_at = datetime.now(timezone.utc)
    inv.revoked_by = user_id
    db.commit()
    return _dump(inv)
