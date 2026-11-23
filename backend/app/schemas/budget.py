"""预算请求 schema：金额用 Decimal 承接，服务端统一量化到分。"""
from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field


class CategoryBudgetIn(BaseModel):
    """单个分类预算；category 与 expenses.category 取值体系一致。"""

    category: str = Field(min_length=1, max_length=32)
    amount: Decimal = Field(ge=0)
    note: str | None = None


class BudgetUpdateIn(BaseModel):
    """设置预算：total_budget 为总预算（None 表示保持原值），categories 逐条 upsert。"""

    total_budget: Decimal | None = Field(default=None, ge=0)
    categories: list[CategoryBudgetIn] | None = None
