"""天气 API：脱敏配置、供应商列表、三家归一化预报。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, Query, Request
from sqlalchemy.orm import Session

from app.api.v1.deps import get_db, require_permission
from app.core.response import ok
from app.services import weather_service

router = APIRouter(tags=["weather"])

_PROVIDER_META = (
    ("uapis", "UApi Pro（免密钥）", False),
    ("amap", "高德天气", True),
    ("qweather", "和风天气", True),
)


def _rid(request: Request) -> str:
    return getattr(getattr(request, "state", None), "request_id", "") or ""


@router.get("/weather/config")
def get_config(request: Request, user: Any = Depends(require_permission("trip:settings"))):
    """脱敏配置：所有 *_enc 只回 has_* 布尔。"""
    return ok(weather_service.get_weather_config(), request_id=_rid(request))


@router.put("/weather/config")
def put_config(request: Request, cfg: dict | None = Body(default=None),
               user: Any = Depends(require_permission("trip:settings"))):
    return ok(weather_service.save_weather_config(cfg or {}), request_id=_rid(request))


@router.get("/weather/forecast")
def forecast(request: Request, city: str = Query(..., min_length=1),
             days: int = Query(default=7, ge=1, le=15),
             provider: str = Query(default=""),
             db: Session = Depends(get_db),
             user: Any = Depends(require_permission("trip:settings"))):
    data = weather_service.fetch_weather(city, days=days, provider=provider or None, db=db)
    return ok(data, request_id=_rid(request))


@router.get("/weather/providers")
def providers(request: Request, user: Any = Depends(require_permission("trip:settings"))):
    return ok(
        {"providers": [
            {"id": pid, "label": label, "needs_key": needs}
            for pid, label, needs in _PROVIDER_META
        ]},
        request_id=_rid(request),
    )
