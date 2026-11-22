"""三栏计划 API：一次取板、条目 CRUD、批量拖拽 / undo、导入、GeoJSON 路线。

所有写端点统一声明 Depends(require_permission("plan:write"))。
"""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Request
from sqlalchemy.orm import Session

from app.api.v1.deps import get_db, require_permission
from app.core.errors import AppError, ErrorCode
from app.core.response import ok
from app.schemas.common import dump, dump_many
from app.schemas.plan import (
    ImportIn,
    MovesIn,
    PlanItemCreate,
    PlanItemOut,
    PlanItemUpdate,
)
from app.services import plan_service

router = APIRouter(tags=["plan"])


@router.get("/trips/{trip_id}/plan")
def get_plan(
    trip_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(require_permission("trip:read")),
):
    return ok(plan_service.get_plan(db, trip_id), request_id=getattr(request.state, "request_id", ""))


@router.post("/trips/{trip_id}/plan/items")
def create_item(
    trip_id: str,
    payload: PlanItemCreate,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(require_permission("plan:write")),
):
    item = plan_service.create_item(db, trip_id, payload, user.id)
    return ok(dump(PlanItemOut, item), request_id=getattr(request.state, "request_id", ""))


@router.put("/trips/{trip_id}/plan/items/{item_id}")
def update_item(
    trip_id: str,
    item_id: str,
    payload: PlanItemUpdate,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(require_permission("plan:write")),
):
    item = plan_service.update_item(db, trip_id, item_id, payload)
    return ok(dump(PlanItemOut, item), request_id=getattr(request.state, "request_id", ""))


@router.delete("/trips/{trip_id}/plan/items/{item_id}")
def delete_item(
    trip_id: str,
    item_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(require_permission("plan:write")),
):
    plan_service.delete_item(db, trip_id, item_id)
    return ok({"deleted": item_id}, request_id=getattr(request.state, "request_id", ""))


@router.post("/trips/{trip_id}/plan/moves")
def apply_moves(
    trip_id: str,
    payload: MovesIn,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(require_permission("plan:write")),
):
    result = plan_service.apply_moves(db, trip_id, user.id, payload.moves)
    return ok(result, request_id=getattr(request.state, "request_id", ""))


@router.post("/trips/{trip_id}/plan/moves/undo")
def undo_moves(
    trip_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(require_permission("plan:write")),
):
    result = plan_service.undo_moves(db, trip_id)
    return ok(result, request_id=getattr(request.state, "request_id", ""))


@router.post("/trips/{trip_id}/plan/import")
def import_items(
    trip_id: str,
    payload: ImportIn,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(require_permission("plan:write")),
):
    items = plan_service.import_items(db, trip_id, user.id, payload.items)
    return ok(
        {"created": len(items), "items": dump_many(PlanItemOut, items)},
        request_id=getattr(request.state, "request_id", ""),
    )


@router.get("/trips/{trip_id}/plan/route")
def plan_route(
    trip_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(require_permission("trip:read")),
):
    return ok(plan_service.build_route(db, trip_id), request_id=getattr(request.state, "request_id", ""))


@router.get("/trips/{trip_id}/plan/categories")
def plan_categories(
    trip_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(require_permission("trip:read")),
):
    """中文分类预设：返回 {id,label} 列表。"""
    return ok(plan_service.list_categories(), request_id=getattr(request.state, "request_id", ""))


@router.get("/trips/{trip_id}/plan/conflicts")
def plan_conflicts(
    trip_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(require_permission("trip:read")),
):
    """同一行程日内时间重叠列表（前项 end == 后项 start 不算冲突）。"""
    return ok(plan_service.conflicts_for_trip(db, trip_id), request_id=getattr(request.state, "request_id", ""))


@router.post("/trips/{trip_id}/plan/auto-arrange")
def plan_auto_arrange(
    trip_id: str,
    request: Request,
    payload: dict = Body(default={}),
    db: Session = Depends(get_db),
    user=Depends(require_permission("plan:write")),
):
    """按当前顺序（或 AI 顺序）重排该天时间，保留时长、相邻无缝衔接。"""
    day_id = payload.get("day_id") or payload.get("dayId")
    if not day_id:
        raise AppError(ErrorCode.VALIDATION, "请指定要自动排程的 day_id")
    use_ai = bool(payload.get("use_ai") or payload.get("useAi"))
    result = plan_service.auto_arrange(db, trip_id, str(day_id), use_ai=use_ai)
    return ok(result, request_id=getattr(request.state, "request_id", ""))
