"""交通段落：起终点坐标一律 WGS84 入库并带 coord_system 标记。"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Float, Index, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.security import new_id
from app.db.base import Base, SoftDeleteMixin, TimestampMixin


class Transport(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "transports"
    __table_args__ = (Index("ix_transports_trip_id", "trip_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    trip_id: Mapped[str] = mapped_column(String(36), nullable=False)
    plan_item_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    mode: Mapped[str] = mapped_column(String(32), nullable=False, default="other")
    from_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    to_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    from_lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    from_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    to_lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    to_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    coord_system: Mapped[str] = mapped_column(String(16), nullable=False, default="WGS84")
    depart_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    arrive_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    carrier: Mapped[str | None] = mapped_column(String(128), nullable=True)
    seat: Mapped[str | None] = mapped_column(String(64), nullable=True)
    price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    route_geojson: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_key: Mapped[str] = mapped_column(Text, nullable=False, default="")
