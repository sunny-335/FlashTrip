"""行程与行程日模型。"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import Boolean, Date, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.security import new_id
from app.db.base import Base, SoftDeleteMixin, TimestampMixin


class Trip(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "trips"
    __table_args__ = (
        Index("ix_trips_owner_status_start_date", "owner_id", "status", "start_date"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(String(36), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    destination: Mapped[str | None] = mapped_column(String(255), nullable=True)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    cover_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    # planned / ongoing / completed / archived
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="planned")
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Asia/Shanghai")
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="CNY")
    visibility: Mapped[str] = mapped_column(String(16), nullable=False, default="private")
    # 出行人群 / 家庭模式（与 0004_extended 迁移逐列对齐）
    traveler_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    has_children: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    children_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    family_mode: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    family_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # 行程总预算：NULL 表示未设置预算；金额与本位币一致
    total_budget: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)


class TripDay(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "trip_days"
    __table_args__ = (
        UniqueConstraint("trip_id", "day_index", name="uq_trip_days_trip_day"),
        Index("ix_trip_days_trip_sort", "trip_id", "sort_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    trip_id: Mapped[str] = mapped_column(String(36), nullable=False)
    day_index: Mapped[int] = mapped_column(Integer, nullable=False)
    date: Mapped[date | None] = mapped_column(Date, nullable=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 天气快照，JSON 字符串（Text 存储）
    weather_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    collapsed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # 前端计算并提交的字典序键
    sort_key: Mapped[str] = mapped_column(String(128), nullable=False, default="")
