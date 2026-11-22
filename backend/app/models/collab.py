"""协作域：成员、细粒度权限、邀请。

字段名与 app.api.v1.deps.require_permission 运行时导入保持一致：
TripMember(trip_id, user_id, id) / Permission(trip_member_id, permission_key, granted)。
邀请 token 明文只在链接里出现，DB 仅存 token_hash。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.security import new_id
from app.db.base import Base, SoftDeleteMixin, TimestampMixin


class TripMember(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "trip_members"
    __table_args__ = (
        UniqueConstraint("trip_id", "user_id", name="uq_trip_members_trip_user"),
        Index("ix_trip_members_trip_id", "trip_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    trip_id: Mapped[str] = mapped_column(String(36), nullable=False)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    role: Mapped[str] = mapped_column(String(24), nullable=False, default="member")
    invited_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    joined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # 受邀成员的可选联系方式（未绑定 User 时也可用于邮件提醒）
    nickname: Mapped[str | None] = mapped_column(String(64), nullable=True)
    email: Mapped[str | None] = mapped_column(String(128), nullable=True)


class Permission(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "permissions"
    __table_args__ = (
        UniqueConstraint("trip_member_id", "permission_key", name="uq_permissions_member_key"),
        Index("ix_permissions_member_id", "trip_member_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    trip_member_id: Mapped[str] = mapped_column(String(36), nullable=False)
    permission_key: Mapped[str] = mapped_column(String(48), nullable=False)
    granted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    granted_by: Mapped[str | None] = mapped_column(String(36), nullable=True)


class Invitation(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "invitations"
    __table_args__ = (Index("ix_invitations_trip_id", "trip_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    trip_id: Mapped[str] = mapped_column(String(36), nullable=False)
    # 唯一约束：任何情况下不可存明文 token
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    channel: Mapped[str] = mapped_column(String(16), nullable=False, default="username")
    target_value: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    permission_keys_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    max_uses: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    used_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # 邀请激活后是否强制首次设密（与管理员强制改密策略配合）
    force_reset: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
