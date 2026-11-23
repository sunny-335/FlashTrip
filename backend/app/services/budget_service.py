"""预算服务：行程总预算 + 分类预算的设置、查询与费用对比（已用/剩余/超支）。

费用汇总口径与 expenses 端点保持一致：金额按 exchange_rate 折算为本位币，
无汇率视为 1；所有金额用 Decimal 计算并量化到分，输出 float。
分类预算与费用分类共用同一套取值（food / lodging / transport / ticket / shopping / other）。
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models.budget import BudgetCategory
from app.models.expense import Expense
from app.models.trip import Trip
from app.schemas.budget import BudgetUpdateIn

CENT = Decimal("0.01")
ONE = Decimal("1")

# 现有费用分类预设（与前端 ExpensesView 的 categoryOptions 对齐）
EXPENSE_CATEGORIES: tuple[tuple[str, str], ...] = (
    ("food", "餐饮"),
    ("lodging", "住宿"),
    ("transport", "交通"),
    ("ticket", "门票"),
    ("shopping", "购物"),
    ("other", "其他"),
)
_LABELS = dict(EXPENSE_CATEGORIES)


# ---------------------------------------------------------------- 基础工具

def _dec(value: Any) -> Decimal:
    try:
        return Decimal(str(value if value is not None else 0))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")


def _q(value: Any) -> Decimal:
    return _dec(value).quantize(CENT, rounding=ROUND_HALF_UP)


def _f(value: Any) -> float:
    return float(_q(value))


def _trip_or_404(db: Session, trip_id: str) -> Trip:
    trip = db.get(Trip, trip_id)
    if trip is None:
        raise AppError(ErrorCode.NOT_FOUND, "行程不存在")
    return trip


def _label(category: str) -> str:
    return _LABELS.get(category, category)


def category_options() -> list[dict]:
    """供前端渲染的分类预设 [{value,label}]。"""
    return [{"value": value, "label": label} for value, label in EXPENSE_CATEGORIES]


def _category_budgets(db: Session, trip_id: str) -> list[BudgetCategory]:
    return (
        db.query(BudgetCategory)
        .filter(BudgetCategory.trip_id == trip_id)
        .order_by(BudgetCategory.category)
        .all()
    )


def _spent_by_category(db: Session, trip_id: str) -> tuple[dict[str, Decimal], Decimal]:
    """按分类汇总已用金额（折本位币），返回 (分类 -> 金额, 合计)。"""
    by_category: dict[str, Decimal] = {}
    total = Decimal("0")
    for row in db.query(Expense).filter(Expense.trip_id == trip_id).all():
        amount = _q(row.amount)
        rate = _q(row.exchange_rate) if row.exchange_rate is not None else ONE
        if rate <= 0:
            rate = ONE
        converted = _q(amount * rate)
        category = str(row.category or "other")
        by_category[category] = by_category.get(category, Decimal("0")) + converted
        total += converted
    return by_category, total


# ---------------------------------------------------------------- 预算设置 / 查询

def get_budget(db: Session, trip_id: str) -> dict:
    trip = _trip_or_404(db, trip_id)
    rows = _category_budgets(db, trip_id)
    return {
        "trip_id": trip_id,
        "currency": trip.currency or "CNY",
        "total_budget": _f(trip.total_budget) if trip.total_budget is not None else None,
        "categories": [
            {
                "id": row.id,
                "category": row.category,
                "label": _label(row.category),
                "amount": _f(row.amount),
                "note": row.note,
            }
            for row in rows
        ],
        "available_categories": category_options(),
    }


def set_budget(db: Session, trip_id: str, payload: BudgetUpdateIn) -> dict:
    """设置总预算与分类预算；categories 逐条 upsert，total_budget 显式 null 表示清空。"""
    trip = _trip_or_404(db, trip_id)
    fields_set = getattr(payload, "model_fields_set", set())
    if "total_budget" in fields_set:
        trip.total_budget = _q(payload.total_budget) if payload.total_budget is not None else None

    for item in payload.categories or []:
        category = str(item.category or "").strip()
        if not category:
            raise AppError(ErrorCode.BUDGET_INVALID, "分类预算必须指定费用分类")
        row = (
            db.query(BudgetCategory)
            .filter(BudgetCategory.trip_id == trip_id, BudgetCategory.category == category)
            .first()
        )
        if row is None:
            row = BudgetCategory(trip_id=trip_id, category=category)
            db.add(row)
        row.amount = _q(item.amount)
        if item.note is not None:
            row.note = item.note
    db.commit()
    return get_budget(db, trip_id)


def delete_category_budget(db: Session, trip_id: str, category: str) -> dict:
    _trip_or_404(db, trip_id)
    row = (
        db.query(BudgetCategory)
        .filter(BudgetCategory.trip_id == trip_id, BudgetCategory.category == category)
        .first()
    )
    if row is None:
        raise AppError(ErrorCode.NOT_FOUND, "该分类预算不存在")
    row.deleted_at = datetime.now(timezone.utc)
    db.commit()
    return {"trip_id": trip_id, "category": category, "deleted": True}


# ---------------------------------------------------------------- 费用对比

def _compare_item(category: str, budget: Decimal | None, spent: Decimal) -> dict:
    remaining = (budget - spent) if budget is not None else None
    over = remaining is not None and remaining < 0
    usage = None
    if budget is not None and budget > 0:
        usage = float(_q(spent / budget * Decimal("100")))
    return {
        "category": category,
        "label": _label(category),
        "budget": _f(budget) if budget is not None else None,
        "spent": _f(spent),
        "remaining": _f(remaining) if remaining is not None else None,
        "over_budget": bool(over),
        "usage_rate": usage,
    }


def budget_comparison(db: Session, trip_id: str) -> dict:
    """总预算与分类预算的费用对比：已用 / 剩余 / 是否超支 / 使用率。"""
    trip = _trip_or_404(db, trip_id)
    budgets = {row.category: _q(row.amount) for row in _category_budgets(db, trip_id)}
    spent_by_category, total_spent = _spent_by_category(db, trip_id)

    # 预设分类在前，其次是有预算或有开销的额外分类，保证顺序稳定
    ordered = [value for value, _ in EXPENSE_CATEGORIES]
    extra = sorted(
        (set(budgets) | set(spent_by_category)) - set(ordered)
    )
    by_category = [
        _compare_item(
            category,
            budgets.get(category),
            spent_by_category.get(category, Decimal("0")),
        )
        for category in ordered + extra
        if category in budgets or category in spent_by_category
    ]

    total_budget = _q(trip.total_budget) if trip.total_budget is not None else None
    total_remaining = (total_budget - total_spent) if total_budget is not None else None
    total_usage = None
    if total_budget is not None and total_budget > 0:
        total_usage = float(_q(total_spent / total_budget * Decimal("100")))

    return {
        "trip_id": trip_id,
        "currency": trip.currency or "CNY",
        "total_budget": _f(total_budget) if total_budget is not None else None,
        "total_spent": _f(total_spent),
        "total_remaining": _f(total_remaining) if total_remaining is not None else None,
        "total_over_budget": bool(total_remaining is not None and total_remaining < 0),
        "total_usage_rate": total_usage,
        "by_category": by_category,
    }
