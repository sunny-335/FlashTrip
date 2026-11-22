"""费用 CRUD + 汇总 + 多人智能分账：写端点声明 expense:write 权限。

GET /expenses/summary 在原有 {total,byCategory,byCurrency,count} 上追加
splitMode / participants / byParticipant；另提供 split-summary 与单笔 split。
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Body, Depends, Query, Request
from sqlalchemy.orm import Session

from app.api.v1.deps import get_db, require_permission
from app.core.errors import AppError, ErrorCode
from app.core.response import ok
from app.models.expense import Expense
from app.models.trip import Trip
from app.services import expense_service
from app.services.sync_service import apply_payload, emit, row_to_dict

router = APIRouter(tags=["expenses"])


def _rid(request: Request) -> str:
    return getattr(request.state, "request_id", "")


def _get(db: Session, trip_id: str, item_id: str) -> Expense:
    obj = db.get(Expense, item_id)
    if obj is None or obj.trip_id != trip_id:
        raise AppError(ErrorCode.NOT_FOUND, "费用记录不存在")
    return obj


def _amount(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _normalize_payload(payload: dict) -> dict:
    """兼容前端 camelCase 关联键，并把金额转成 Decimal 避免浮点误差。"""
    data = dict(payload or {})
    for alias, key in (("dayId", "day_id"), ("planItemId", "plan_item_id")):
        if alias in data:
            data.setdefault(key, data.pop(alias))
        else:
            data.pop(alias, None)
    if "amount" in data and data["amount"] is not None:
        try:
            data["amount"] = Decimal(str(data["amount"]))
        except Exception:  # noqa: BLE001
            raise AppError(ErrorCode.VALIDATION, "金额格式不正确") from None
    if data.get("split_mode") is not None and data["split_mode"] not in expense_service.SPLIT_MODES:
        raise AppError(ErrorCode.VALIDATION, "不支持的分账方式")
    return data


def _validate_links(db: Session, trip_id: str, data: dict) -> None:
    """day_id / plan_item_id 必须属于当前行程。"""
    from app.models.plan import PlanItem
    from app.models.trip import TripDay

    day_id = data.get("day_id")
    if day_id:
        day = db.get(TripDay, str(day_id))
        if day is None or day.trip_id != trip_id:
            raise AppError(ErrorCode.VALIDATION, "所选日期或地点不属于当前行程")
    item_id = data.get("plan_item_id")
    if item_id:
        item = db.get(PlanItem, str(item_id))
        if item is None or item.trip_id != trip_id:
            raise AppError(ErrorCode.VALIDATION, "所选日期或地点不属于当前行程")


def _maybe_normalize_split(db: Session, trip_id: str, obj: Expense, data: dict) -> None:
    """POST/PUT 带 split_mode 时自动填充分账明细。"""
    if data.get("split_mode") is None:
        return
    trip = db.get(Trip, trip_id)
    if trip is None:
        raise AppError(ErrorCode.NOT_FOUND, "行程不存在")
    expense_service.apply_split(obj, trip, data)


@router.get("/trips/{trip_id}/expenses")
def list_expenses(trip_id: str, request: Request, day_id: str | None = Query(default=None),
                  db: Session = Depends(get_db),
                  user: Any = Depends(require_permission("trip:read"))):
    query = db.query(Expense).filter(Expense.trip_id == trip_id)
    if day_id:
        query = query.filter(Expense.day_id == day_id)
    rows = query.order_by(Expense.occurred_at.desc()).all()
    return ok([row_to_dict(r) for r in rows], request_id=_rid(request))


@router.get("/trips/{trip_id}/expenses/summary")
def expenses_summary(trip_id: str, request: Request, db: Session = Depends(get_db),
                     user: Any = Depends(require_permission("trip:read"))):
    """按分类与币种汇总；有 exchange_rate 时折算为本位币计入 total。

    保留原有 4 个字段，追加 splitMode / participants / byParticipant 供分账视图使用。
    """
    rows = db.query(Expense).filter(Expense.trip_id == trip_id).all()
    by_category: dict[str, float] = {}
    by_currency: dict[str, float] = {}
    total = 0.0
    for row in rows:
        amount = _amount(row.amount)
        rate = _amount(row.exchange_rate) or 1.0
        currency = row.currency or "CNY"
        category = row.category or "other"
        by_currency[currency] = by_currency.get(currency, 0.0) + amount
        by_category[category] = by_category.get(category, 0.0) + amount * rate
        total += amount * rate
    data: dict[str, Any] = {
        "total": round(total, 2),
        "byCategory": {k: round(v, 2) for k, v in by_category.items()},
        "byCurrency": {k: round(v, 2) for k, v in by_currency.items()},
        "count": len(rows),
    }
    data.update(expense_service.summary_extras(db, trip_id))
    return ok(data, request_id=_rid(request))


@router.get("/trips/{trip_id}/expenses/split-summary")
def split_summary(trip_id: str, request: Request, db: Session = Depends(get_db),
                  user: Any = Depends(require_permission("trip:read"))):
    """行程级多人分账汇总（余额 + 建议转账）。"""
    return ok(expense_service.split_summary(db, trip_id), request_id=_rid(request))


@router.post("/trips/{trip_id}/expenses")
def create_expense(trip_id: str, request: Request, payload: dict = Body(default={}),
                   db: Session = Depends(get_db),
                   user: Any = Depends(require_permission("expense:write"))):
    data = _normalize_payload(payload)
    _validate_links(db, trip_id, data)
    obj = Expense(trip_id=trip_id)
    apply_payload(obj, data)
    _maybe_normalize_split(db, trip_id, obj, data)
    db.add(obj)
    db.commit()
    out = row_to_dict(obj)
    emit(trip_id, "expense.created", out, getattr(user, "id", None))
    return ok(out, request_id=_rid(request))


@router.post("/trips/{trip_id}/expenses/{expense_id}/split")
def split_expense(trip_id: str, expense_id: str, request: Request, payload: dict = Body(default={}),
                  db: Session = Depends(get_db),
                  user: Any = Depends(require_permission("expense:write"))):
    """重算单笔费用分账并落库 split_json / split_detail_json / split_mode。"""
    obj = _get(db, trip_id, expense_id)
    trip = db.get(Trip, trip_id)
    if trip is None:
        raise AppError(ErrorCode.NOT_FOUND, "行程不存在")
    detail = expense_service.apply_split(obj, trip, dict(payload or {}))
    db.commit()
    out = row_to_dict(obj)
    emit(trip_id, "expense.split", out, getattr(user, "id", None))
    return ok(
        {"expense": out, "shares": expense_service.to_jsonable(detail["shares"])},
        request_id=_rid(request),
    )


@router.get("/trips/{trip_id}/expenses/{item_id}")
def get_expense(trip_id: str, item_id: str, request: Request, db: Session = Depends(get_db),
                user: Any = Depends(require_permission("trip:read"))):
    return ok(row_to_dict(_get(db, trip_id, item_id)), request_id=_rid(request))


@router.put("/trips/{trip_id}/expenses/{item_id}")
def update_expense(trip_id: str, item_id: str, request: Request, payload: dict = Body(default={}),
                   db: Session = Depends(get_db),
                   user: Any = Depends(require_permission("expense:write"))):
    obj = _get(db, trip_id, item_id)
    data = _normalize_payload(payload)
    _validate_links(db, trip_id, data)
    apply_payload(obj, data)
    _maybe_normalize_split(db, trip_id, obj, data)
    db.commit()
    out = row_to_dict(obj)
    emit(trip_id, "expense.updated", out, getattr(user, "id", None))
    return ok(out, request_id=_rid(request))


@router.delete("/trips/{trip_id}/expenses/{item_id}")
def delete_expense(trip_id: str, item_id: str, request: Request, db: Session = Depends(get_db),
                   user: Any = Depends(require_permission("expense:write"))):
    obj = _get(db, trip_id, item_id)
    obj.deleted_at = datetime.now(timezone.utc)
    db.commit()
    emit(trip_id, "expense.deleted", {"id": item_id}, getattr(user, "id", None))
    return ok({"id": item_id, "deleted": True}, request_id=_rid(request))
