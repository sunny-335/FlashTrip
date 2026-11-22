"""费用记录：金额 Numeric(12,2) + 币种，split_json 存分账明细。"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Index, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.security import new_id
from app.db.base import Base, SoftDeleteMixin, TimestampMixin


class Expense(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "expenses"
    __table_args__ = (Index("ix_expenses_trip_id", "trip_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    trip_id: Mapped[str] = mapped_column(String(36), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False, default="other")
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="CNY")
    exchange_rate: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    paid_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # 分账明细（复用 split_json）+ 扩展明细，统一结构见 services/expense_service.py
    split_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    split_detail_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # equal / child_free / family / custom / payer_only
    split_mode: Mapped[str] = mapped_column(String(24), nullable=False, default="equal")
    # 可归集到某个行程日 / 计划项（与 0004_extended 迁移对齐）
    day_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    plan_item_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    attachment_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
