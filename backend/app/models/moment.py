"""旅途瞬间（随记 / 照片）：坐标 WGS84 入库并带 coord_system 标记。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.security import new_id
from app.db.base import Base, SoftDeleteMixin, TimestampMixin


class Moment(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "moments"
    __table_args__ = (Index("ix_moments_trip_id", "trip_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    trip_id: Mapped[str] = mapped_column(String(36), nullable=False)
    day_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    plan_item_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    author_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    mood: Mapped[str | None] = mapped_column(String(32), nullable=True)
    lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    coord_system: Mapped[str] = mapped_column(String(16), nullable=False, default="WGS84")
    taken_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    media_json: Mapped[str | None] = mapped_column(Text, nullable=True)
