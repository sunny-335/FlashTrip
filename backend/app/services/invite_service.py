"""邀请服务：随机 token 只存 hash，状态机校验，接受后建用户/成员/权限。

- DB 只存 token_hash；明文仅出现在 /invite/<token> 链接里。
- 过期 / 次数用尽 / 已撤销 / 软删统一返回 INVITE_INVALID 且不泄露行程信息。
- accept 带 password：一次性完成建用户 + 设密 + 激活成员 + 消耗次数 + 签发全量 token。
- accept 不带 password：仅签发 setup 作用域凭证，**不消耗次数、不建成员**，
  待 /auth/set-password 成功后统一激活，避免「次数已用尽但密码未设置」的死路。
- force_reset：即使目标用户已有密码也强制走重置（scope="reset"）；
  public_info / accept 通过 action 把前端分流到登录页或重置密码页。
- 受邀成员的 nickname / email 随邀请持久化（复用 permission_keys_json 的
  元数据槽位），激活 TripMember 时写入，供成员列表与邮件提醒使用。
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
from app.services.password_policy import validate_password

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


def _inv_meta(inv: Invitation) -> dict:
    """解析 permission_keys_json 中的权限键与受邀成员元数据。

    兼容两种格式：历史纯数组 ["trip:read", ...]，以及新结构
    {"keys": [...], "nickname": ..., "email": ...}。Invitation 模型未新增列，
    因此把可选的 nickname/email 挂在同一 Text 槽位，读取时统一归一化。
    """
    try:
        raw = json.loads(inv.permission_keys_json or "[]")
    except (ValueError, TypeError):
        raw = []
    if isinstance(raw, dict):
        keys = raw.get("keys")
        return {
            "keys": list(keys) if isinstance(keys, list) else [],
            "nickname": raw.get("nickname"),
            "email": raw.get("email"),
        }
    return {
        "keys": list(raw) if isinstance(raw, list) else [],
        "nickname": None,
        "email": None,
    }


def _inv_keys(inv: Invitation) -> list[str]:
    return [str(key) for key in _inv_meta(inv)["keys"]]


def _dump(inv: Invitation) -> dict[str, Any]:
    """对外视图：不含 token_hash。"""
    meta = _inv_meta(inv)
    return {
        "id": inv.id,
        "tripId": inv.trip_id,
        "channel": inv.channel,
        "targetValue": inv.target_value,
        "permissionKeys": meta["keys"],
        "expiresAt": _iso(inv.expires_at),
        "maxUses": inv.max_uses,
        "usedCount": inv.used_count,
        "revokedAt": _iso(inv.revoked_at) if inv.revoked_at else None,
        "createdBy": inv.created_by,
        "createdAt": _iso(getattr(inv, "created_at", None)),
        "forceReset": bool(getattr(inv, "force_reset", False)),
        "nickname": meta["nickname"],
        "email": meta["email"],
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
                      max_uses: int = 1, created_by: str | None = None,
                      force_reset: bool = False, nickname: str | None = None,
                      email: str | None = None) -> dict:
    """创建邀请；返回一次性明文 token（仅此一次，之后无法找回）。"""
    if channel not in _CHANNEL_COLUMN:
        raise AppError(ErrorCode.VALIDATION, "邀请渠道须为 phone / email / username")
    keys = list(permission_keys or DEFAULT_PERMISSION_KEYS)
    invalid = [k for k in keys if k not in PERMISSION_KEYS]
    if invalid:
        raise AppError(ErrorCode.VALIDATION, f"未知权限点：{'、'.join(invalid)}")
    nick = str(nickname).strip() if nickname is not None else ""
    mail = str(email).strip() if email is not None else ""
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    inv = Invitation(
        id=new_id(),
        trip_id=trip_id,
        token_hash=hash_token(token),
        channel=channel,
        target_value=str(target_value or ""),
        permission_keys_json=json.dumps(
            {"keys": keys, "nickname": nick or None, "email": mail or None},
            ensure_ascii=False,
        ),
        expires_at=now + timedelta(days=max(1, int(expires_days))),
        max_uses=max(1, int(max_uses)),
        used_count=0,
        created_by=created_by,
        force_reset=bool(force_reset),
    )
    db.add(inv)
    db.commit()
    return {
        "invitation": _dump(inv),
        "token": token,
        "inviteUrl": f"/invite/{token}",
    }


def _ensure_valid(inv: Invitation | None) -> Invitation:
    """统一状态校验：任何无效/过期/撤销/超次/软删都返回 INVITE_INVALID。"""
    now = datetime.now(timezone.utc)
    if (
        inv is None
        or getattr(inv, "deleted_at", None) is not None
        or inv.revoked_at is not None
        or _utc(inv.expires_at) <= now
        or inv.used_count >= inv.max_uses
    ):
        raise AppError(ErrorCode.INVITE_INVALID, "邀请无效或已过期")
    return inv


def validate(db, token: str) -> Invitation:
    """按 sha256 等值查询校验状态机；不区分失败原因以免泄露行程信息。"""
    inv = (
        db.query(Invitation)
        .filter(
            Invitation.token_hash == hash_token(token),
            Invitation.deleted_at.is_(None),
        )
        .first()
    )
    return _ensure_valid(inv)


def public_info(db, token: str) -> dict:
    """GET /invites/{token}：校验通过后才展示最小必要信息。

    action 分流：login（老用户已有密码且未强制重置，前端跳 /login?next=/invite/<token>）、
    reset（force_reset，前端进入重置密码页）、setup（新用户首次设密）。
    """
    inv = validate(db, token)
    trip_title = ""
    try:
        from app.models.trip import Trip

        trip = db.get(Trip, inv.trip_id)
        if trip is not None:
            trip_title = str(getattr(trip, "title", None) or getattr(trip, "name", None) or "")
    except Exception:  # noqa: BLE001  行程模型未就绪不影响邀请展示
        trip_title = ""
    meta = _inv_meta(inv)
    existing = _find_user(db, inv.channel, inv.target_value)
    has_password = existing is not None and not getattr(existing, "must_set_password", False)
    force_reset = bool(getattr(inv, "force_reset", False))
    if force_reset:
        action = "reset"
    elif has_password:
        action = "login"
    else:
        action = "setup"
    return {
        "channel": inv.channel,
        "target": _mask_target(inv.target_value),
        "tripTitle": trip_title,
        "permissionKeys": meta["keys"],
        "expiresAt": _iso(inv.expires_at),
        "maxUses": inv.max_uses,
        "usedCount": inv.used_count,
        "requiresPassword": (not has_password) or force_reset,
        "forceReset": force_reset,
        "hasPassword": has_password,
        "nickname": meta["nickname"],
        "email": meta["email"],
        "action": action,
        "next": f"/invite/{token}",
    }


def _find_user(db, channel: str, target: str):
    """仅复用启用且未软删的账号，停用账号一律视为不存在。"""
    from app.models.user import User

    column = _CHANNEL_COLUMN[channel]
    if not hasattr(User, column) or not target:
        return None
    return (
        db.query(User)
        .filter(
            getattr(User, column) == target,
            User.is_active.is_(True),
            User.deleted_at.is_(None),
        )
        .first()
    )


def _unique_value(db, column: str, value: str, max_len: int) -> str:
    """停用/软删账号仍占用唯一索引，重名时加随机后缀，避免建号触发 UNIQUE 冲突。"""
    from app.models.user import User

    col = getattr(User, column, None)
    if col is None or not value:
        return value
    taken = (
        db.query(User)
        .filter(col == value)
        .execution_options(include_deleted=True)  # 绕过全局软删过滤，覆盖历史占位
        .first()
    )
    if taken is None:
        return value
    suffix = new_id()[:8]
    return f"{value[:max(1, max_len - len(suffix) - 1)]}_{suffix}"


def _create_user(db, inv: Invitation, password: str | None, display_name: str | None):
    """按 User 模型真实列构造，避免依赖不确定的必填字段。"""
    from app.models.user import User

    columns = {c.name: c for c in User.__table__.columns}
    kwargs: dict[str, Any] = {}
    target = inv.target_value or display_name or f"invite_{new_id()[:12]}"
    if "username" in columns:
        desired = target if inv.channel == "username" else f"invite_{new_id()[:12]}"
        kwargs["username"] = _unique_value(db, "username", desired, 64)
    if "email" in columns and inv.channel == "email":
        kwargs["email"] = _unique_value(db, "email", target, 255)
    if "phone" in columns and inv.channel == "phone":
        kwargs["phone"] = _unique_value(db, "phone", target, 32)
    if "display_name" in columns:
        kwargs["display_name"] = str(display_name or target)
    if "password_hash" in columns:
        # 未提供密码时设一个随机不可知口令，必须走 set-password 才能登录
        kwargs["password_hash"] = hash_password(password or secrets.token_urlsafe(24))
    if "role" in columns:
        kwargs["role"] = "member"
    if "must_set_password" in columns:
        kwargs["must_set_password"] = not bool(password)
    if "password_set_at" in columns and password:
        kwargs["password_set_at"] = datetime.now(timezone.utc)
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


def _activate_membership(db, inv: Invitation, user, *,
                         nickname: str | None = None, email: str | None = None) -> None:
    """建/复用 TripMember 并写入权限；受邀成员的联系方式在此一并落库。"""
    member = (
        db.query(TripMember)
        .filter(TripMember.trip_id == inv.trip_id, TripMember.user_id == user.id)
        .first()
    )
    if member is None:
        member = TripMember(
            id=new_id(), trip_id=inv.trip_id, user_id=user.id, role="member",
            invited_by=inv.created_by, joined_at=datetime.now(timezone.utc),
            nickname=nickname, email=email,
        )
        db.add(member)
        db.flush()
    else:
        if nickname:
            member.nickname = nickname
        if email:
            member.email = email
    keys = _inv_keys(inv) or list(DEFAULT_PERMISSION_KEYS)
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


def _issue_full(user) -> str:
    return create_access_token(
        user.id, extra={"scope": "full", "role": getattr(user, "role", "member")}
    )


def accept(db, token: str, *, password: str | None = None,
           display_name: str | None = None) -> dict:
    """接受邀请。

    - 老用户已有密码且 force_reset=False：直接返回 action=login，不消耗次数。
    - force_reset=True：无论是否已设密，都签发 scope=reset 凭证走重置密码页。
    - 带 password 且非强制重置：一次性设密 + 激活成员 + 消耗次数 + 全量 token。
    - 不带 password：仅签发 setup 凭证并抛 PASSWORD_REQUIRED(3002)，不消耗次数。
    """
    inv = validate(db, token)
    existing = _find_user(db, inv.channel, inv.target_value)
    has_password_user = existing is not None and not getattr(existing, "must_set_password", False)
    force_reset = bool(getattr(inv, "force_reset", False))

    # ① 已有密码且未要求强制重置：分流到登录页（带 ?next=/invite/<token>），不消耗次数
    if has_password_user and not force_reset:
        return {"action": "login", "tripId": inv.trip_id, "next": f"/invite/{token}"}

    # ② 只有真正写入密码时才做全站强度校验（≥8 的旧判断由新策略统一取代）
    if password is not None:
        validate_password(password)
    has_password = bool(password)
    now = datetime.now(timezone.utc)
    meta = _inv_meta(inv)

    user = existing
    if user is None:
        # 强制重置的新用户先建待设密账号，密码留到重置页统一设置
        user = _create_user(db, inv, None if force_reset else password, display_name)
    elif has_password and not force_reset and getattr(user, "must_set_password", False):
        # 复用此前未设密的待激活账号，此处直接完成设密
        user.password_hash = hash_password(password)
        user.must_set_password = False
        user.password_set_at = now

    # ③ 未带密码或强制重置：签发 setup/reset 凭证，不消耗次数、不建成员
    if not has_password or force_reset:
        db.commit()
        scope = "reset" if force_reset else "setup"
        setup_token = create_access_token(
            user.id,
            extra={
                "scope": scope,
                "invitation_id": inv.id,
                "user_id": user.id,
                "trip_id": inv.trip_id,
                "role": getattr(user, "role", "member"),
            },
        )
        message = "该邀请要求重置登录密码，请先设置新密码" if force_reset else "账户已创建，请先设置登录密码"
        raise AppError(
            ErrorCode.PASSWORD_REQUIRED,
            message,
            # detail 约定为 JSON 字符串，供前端 JSON.parse 后取 setupToken / scope
            detail=json.dumps(
                {
                    "scope": scope,
                    "setupToken": setup_token,
                    "userId": user.id,
                    "tripId": inv.trip_id,
                    "invitationId": inv.id,
                    "action": scope,
                },
                ensure_ascii=False,
            ),
        )

    # ④ 带密码且非强制重置：一次性激活 + 消耗次数 + 签发全量 token
    _activate_membership(db, inv, user, nickname=meta["nickname"], email=meta["email"])
    inv.used_count += 1
    db.commit()
    return {
        "accessToken": _issue_full(user),
        "userId": user.id,
        "tripId": inv.trip_id,
        "scope": "full",
    }


def activate_from_setup(db, claims: dict, new_password: str) -> dict:
    """凭 setup / reset 作用域凭证完成设密并统一激活成员 / 权限 / 次数。

    只有设密成功后才 used_count+1，因此凭证可安全重试，不会造成
    「次数已用尽但密码未设置」的死路；reset 作用域对已有密码的老用户同样
    强制覆盖密码，完成后 must_set_password=False。
    """
    scope = claims.get("scope")
    if scope not in ("setup", "reset") or claims.get("type") != "access":
        raise AppError(ErrorCode.UNAUTHORIZED, "无效的设置凭证")
    validate_password(new_password)
    from app.models.user import User

    inv_id = str(claims.get("invitation_id") or "")
    trip_id = str(claims.get("trip_id") or "")
    user_id = str(claims.get("user_id") or claims.get("sub") or "")
    inv = _ensure_valid(db.get(Invitation, inv_id)) if inv_id else None
    if inv is None or inv.trip_id != trip_id:
        raise AppError(ErrorCode.INVITE_INVALID, "邀请无效或已过期")
    user = db.get(User, user_id) if user_id else None
    if (
        user is None
        or not getattr(user, "is_active", False)
        or getattr(user, "deleted_at", None) is not None
    ):
        raise AppError(ErrorCode.INVITE_INVALID, "邀请无效或已过期")

    meta = _inv_meta(inv)
    # setup 仅对待设密账号写密码（老用户复用原密码）；reset 一律强制覆盖
    if scope == "reset" or getattr(user, "must_set_password", False):
        user.password_hash = hash_password(new_password)
        user.must_set_password = False
        user.password_set_at = datetime.now(timezone.utc)
    _activate_membership(db, inv, user, nickname=meta["nickname"], email=meta["email"])
    inv.used_count += 1
    db.commit()
    return {
        "accessToken": _issue_full(user),
        "userId": user.id,
        "tripId": inv.trip_id,
        "scope": "full",
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
