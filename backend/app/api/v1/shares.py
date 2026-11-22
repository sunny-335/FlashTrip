"""分享 API：行程内管理（需 member:manage）+ 公开只读 /share/{token}。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, Request
from sqlalchemy.orm import Session

from app.api.v1.deps import get_db, require_permission
from app.core.response import ok
from app.services import share_service

router = APIRouter(tags=["shares"])


def _rid(request: Request) -> str:
    return getattr(getattr(request, "state", None), "request_id", "") or ""


@router.get("/trips/{trip_id}/shares")
def list_shares(trip_id: str, request: Request, db: Session = Depends(get_db),
                user: Any = Depends(require_permission("member:manage"))):
    return ok(share_service.list_shares(db, trip_id), request_id=_rid(request))


@router.post("/trips/{trip_id}/shares")
def create_share(trip_id: str, request: Request,
                 payload: dict | None = Body(default=None),
                 db: Session = Depends(get_db),
                 user: Any = Depends(require_permission("member:manage"))):
    cfg = payload or {}
    try:
        expires_days = int(cfg.get("expires_days", 30))
    except (TypeError, ValueError):
        expires_days = 30
    data = share_service.create_share(
        db, trip_id,
        title=str(cfg.get("title") or ""),
        include_transports=bool(cfg.get("include_transports", True)),
        include_bookings=bool(cfg.get("include_bookings", True)),
        include_packing=bool(cfg.get("include_packing", True)),
        include_expenses=bool(cfg.get("include_expenses", False)),
        include_moments=bool(cfg.get("include_moments", False)),
        expires_days=expires_days,
        created_by=getattr(user, "id", None),
    )
    return ok(data, request_id=_rid(request))


@router.delete("/trips/{trip_id}/shares/{share_id}")
def revoke_share(trip_id: str, share_id: str, request: Request,
                 db: Session = Depends(get_db),
                 user: Any = Depends(require_permission("member:manage"))):
    return ok(share_service.revoke_share(db, trip_id, share_id), request_id=_rid(request))


@router.get("/share/{token}")
def public_view(token: str, request: Request, db: Session = Depends(get_db)):
    """公开只读端点：仅凭一次性 token，不依赖登录。"""
    return ok(share_service.public_view(db, token), request_id=_rid(request))
