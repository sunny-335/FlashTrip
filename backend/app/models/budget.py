"""预算模型：行程总预算落在 trips.total_budget，分类预算独立成表。

分类预算按现有费用分类（food/lodging/transport/ticket/shopping/other）各一条，
同一行程同一分类唯一；金额统一 Numeric(14, 2)，与费用金额精度一致。
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import Index, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.security import new_id
from app.db.base import Base, SoftDeleteMixin, TimestampMixin


class BudgetCategory(Base, TimestampMixin, SoftDeleteMixin):
    """行程分类预算：每个费用分类一条，trip_id 逻辑关联 trips。"""

    __tablename__ = "budget_categories"
    __table_args__ = (
        UniqueConstraint("trip_id", "category", name="uq_budget_categories_trip_category"),
        Index("ix_budget_categories_trip_id", "trip_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    trip_id: Mapped[str] = mapped_column(String(36), nullable=False)
    # 与 expenses.category 取值体系一致（food / lodging / transport / ticket / shopping / other）
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
