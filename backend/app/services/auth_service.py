"""认证服务： argon2 校验、JWT 签发、首次设密与改密、管理员创建。"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.core.security import create_access_token, hash_password, new_id, verify_password
from app.models.user import User
from app.services.password_policy import validate_password


def find_by_account(db: Session, account: str) -> User | None:
    """支持用户名 / 邮箱 / 手机号登录（全局软删过滤自动生效）。"""
    return (
        db.query(User)
        .filter(
            or_(
                User.username == account,
                User.email == account,
                User.phone == account,
            )
        )
        .first()
    )


def authenticate(db: Session, account: str, password: str) -> User:
    user = find_by_account(db, account)
    if user is None or not verify_password(user.password_hash, password):
        raise AppError(ErrorCode.UNAUTHORIZED, "账号或密码错误")
    if not user.is_active:
        raise AppError(ErrorCode.FORBIDDEN, "账号已停用")
    return user


def issue_token(user: User, *, scope: str = "full") -> str:
    """签发 access token；must_set_password 用户仅发放 setup 作用域（非业务 token）。"""
    return create_access_token(user.id, extra={"scope": scope, "role": user.role})


def token_scope_for(user: User) -> str:
    return "setup" if user.must_set_password else "full"


def create_user(
    db: Session,
    *,
    username: str,
    password: str,
    role: str = "member",
    email: str | None = None,
    phone: str | None = None,
    display_name: str = "",
    must_set_password: bool = False,
) -> User:
    """创建用户（不提交，交由调用方在同一事务内 commit）。"""
    # 全站统一密码策略；owner 属于管理员，强制四类字符
    validate_password(password, is_admin=(role == "owner"))
    if find_by_account(db, username) is not None:
        raise AppError(ErrorCode.CONFLICT, "账号已存在")
    now = datetime.now(timezone.utc)
    user = User(
        id=new_id(),
        username=username,
        email=email or None,
        phone=phone or None,
        password_hash=hash_password(password),
        display_name=display_name or username,
        avatar_url=None,
        role=role,
        is_active=True,
        must_set_password=must_set_password,
        password_set_at=None if must_set_password else now,
    )
    db.add(user)
    return user


def set_initial_password(db: Session, user: User, new_password: str) -> User:
    """邀请成员首次设密：完成后清除 must_set_password。"""
    if not user.must_set_password:
        raise AppError(ErrorCode.VALIDATION, "密码已设置，请使用修改密码接口")
    validate_password(new_password)
    user.password_hash = hash_password(new_password)
    user.must_set_password = False
    user.password_set_at = datetime.now(timezone.utc)
    db.commit()
    return user


def change_password(db: Session, user: User, old_password: str, new_password: str) -> User:
    if not verify_password(user.password_hash, old_password):
        raise AppError(ErrorCode.UNAUTHORIZED, "原密码错误")
    validate_password(new_password)
    user.password_hash = hash_password(new_password)
    user.password_set_at = datetime.now(timezone.utc)
    db.commit()
    return user
