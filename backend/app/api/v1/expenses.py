"""费用 CRUD + 汇总：按币种/分类统计，写端点声明 expense:write 权限。"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Body, Depends, Request
from sqlalchemy.orm import Session

from app.api.v1.deps import get_db, require_permission
from app.core.errors import AppError, ErrorCode
from app.core.response import ok
from app.models.expense import Expense
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


@router.get("/trips/{trip_id}/expenses")
def list_expenses(trip_id: str, request: Request, db: Session = Depends(get_db),
                  user: Any = Depends(require_permission("trip:read"))):
    rows = db.query(Expense).filter(Expense.trip_id == trip_id).order_by(Expense.occurred_at.desc()).all()
    return ok([row_to_dict(r) for r in rows], request_id=_rid(request))


@router.get("/trips/{trip_id}/expenses/summary")
def expenses_summary(trip_id: str, request: Request, db: Session = Depends(get_db),
                     user: Any = Depends(require_permission("trip:read"))):
    """按分类与币种汇总；有 exchange_rate 时折算为本位币计入 total。"""
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
    return ok({
        "total": round(total, 2),
        "byCategory": {k: round(v, 2) for k, v in by_category.items()},
        "byCurrency": {k: round(v, 2) for k, v in by_currency.items()},
        "count": len(rows),
    }, request_id=_rid(request))


@router.post("/trips/{trip_id}/expenses")
def create_expense(trip_id: str, request: Request, payload: dict = Body(default={}),
                   db: Session = Depends(get_db),
                   user: Any = Depends(require_permission("expense:write"))):
    payload = dict(payload or {})
    if "amount" in payload:
        try:
            payload["amount"] = Decimal(str(payload["amount"]))
        except Exception:  # noqa: BLE001
            raise AppError(ErrorCode.VALIDATION, "金额格式不正确") from None
    obj = Expense(trip_id=trip_id)
    apply_payload(obj, payload)
    db.add(obj)
    db.commit()
    data = row_to_dict(obj)
    emit(trip_id, "expense.created", data, getattr(user, "id", None))
    return ok(data, request_id=_rid(request))


@router.get("/trips/{trip_id}/expenses/{item_id}")
def get_expense(trip_id: str, item_id: str, request: Request, db: Session = Depends(get_db),
                user: Any = Depends(require_permission("trip:read"))):
    return ok(row_to_dict(_get(db, trip_id, item_id)), request_id=_rid(request))


@router.put("/trips/{trip_id}/expenses/{item_id}")
def update_expense(trip_id: str, item_id: str, request: Request, payload: dict = Body(default={}),
                   db: Session = Depends(get_db),
                   user: Any = Depends(require_permission("expense:write"))):
    obj = _get(db, trip_id, item_id)
    apply_payload(obj, payload)
    db.commit()
    data = row_to_dict(obj)
    emit(trip_id, "expense.updated", data, getattr(user, "id", None))
    return ok(data, request_id=_rid(request))


@router.delete("/trips/{trip_id}/expenses/{item_id}")
def delete_expense(trip_id: str, item_id: str, request: Request, db: Session = Depends(get_db),
                   user: Any = Depends(require_permission("expense:write"))):
    obj = _get(db, trip_id, item_id)
    obj.deleted_at = datetime.now(timezone.utc)
    db.commit()
    emit(trip_id, "expense.deleted", {"id": item_id}, getattr(user, "id", None))
    return ok({"id": item_id, "deleted": True}, request_id=_rid(request))
