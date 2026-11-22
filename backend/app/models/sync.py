"""同步事件：追加型日志表，自增整数 id 作为 SSE 补发游标（Last-Event-ID）。

特例说明：id 必须为单调递增整数才能做断点续传，故不用 UUID 主键；
其余沿用 TimestampMixin / SoftDeleteMixin 范式（created_at 由 mixin 提供）。
"""
from __future__ import annotations

from sqlalchemy import Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, SoftDeleteMixin, TimestampMixin


class SyncEvent(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "sync_events"
    __table_args__ = (Index("ix_sync_events_trip_id_id", "trip_id", "id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trip_id: Mapped[str] = mapped_column(String(36), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
