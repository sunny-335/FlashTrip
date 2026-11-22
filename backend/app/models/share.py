"""公开分享链接：明文 token 只在创建响应里出现一次，DB 仅存 sha256(token)。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.security import new_id
from app.db.base import Base, SoftDeleteMixin, TimestampMixin


class ShareLink(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "share_links"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_share_links_token_hash"),
        Index("ix_share_links_trip_id", "trip_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    trip_id: Mapped[str] = mapped_column(String(36), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    include_transports: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    include_bookings: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    include_packing: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    include_expenses: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    include_moments: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    view_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
