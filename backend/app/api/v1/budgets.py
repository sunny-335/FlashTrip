"""预算 API：总预算 / 分类预算的设置与查询，以及与费用的对比（已用/剩余/超支）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.v1.deps import get_db, require_permission
from app.core.response import ok
from app.schemas.budget import BudgetUpdateIn
from app.services import budget_service

router = APIRouter(tags=["budgets"])


def _rid(request: Request) -> str:
    return getattr(request.state, "request_id", "")


@router.get("/trips/{trip_id}/budget")
def get_budget(
    trip_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(require_permission("trip:read")),
):
    return ok(budget_service.get_budget(db, trip_id), request_id=_rid(request))


@router.put("/trips/{trip_id}/budget")
def put_budget(
    trip_id: str,
    payload: BudgetUpdateIn,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(require_permission("trip:settings")),
):
    """设置总预算与分类预算；categories 逐条 upsert，total_budget=null 表示清空。"""
    return ok(budget_service.set_budget(db, trip_id, payload), request_id=_rid(request))


@router.get("/trips/{trip_id}/budget/comparison")
def budget_comparison(
    trip_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(require_permission("trip:read")),
):
    """费用汇总对比：返回总预算与各分类的已用 / 剩余 / 超支状态。"""
    return ok(budget_service.budget_comparison(db, trip_id), request_id=_rid(request))


@router.delete("/trips/{trip_id}/budget/categories/{category}")
def delete_category_budget(
    trip_id: str,
    category: str,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(require_permission("trip:settings")),
):
    return ok(budget_service.delete_category_budget(db, trip_id, category), request_id=_rid(request))
