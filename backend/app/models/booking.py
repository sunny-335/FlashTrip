"""预订（机票 / 酒店 / 火车 / 门票等），挂靠行程、可选计划项与附件。"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Index, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.security import new_id
from app.db.base import Base, SoftDeleteMixin, TimestampMixin


class Booking(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "bookings"
    __table_args__ = (Index("ix_bookings_trip_id", "trip_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    trip_id: Mapped[str] = mapped_column(String(36), nullable=False)
    plan_item_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    type: Mapped[str] = mapped_column(String(32), nullable=False, default="other")
    vendor: Mapped[str | None] = mapped_column(String(128), nullable=True)
    booking_no: Mapped[str | None] = mapped_column(String(128), nullable=True)
    holder: Mapped[str | None] = mapped_column(String(128), nullable=True)
    start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="CNY")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    attachment_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
