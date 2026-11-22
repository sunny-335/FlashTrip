"""导出 API：PDF 行程册（StreamingResponse）与 ICS 日历订阅。"""
from __future__ import annotations

import io
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.orm import Session

from app.api.v1.deps import get_db, require_permission
from app.core.errors import AppError, ErrorCode
from app.services.export_service import render_trip_ics, render_trip_pdf

router = APIRouter(tags=["export"])


@router.post("/trips/{trip_id}/export/pdf")
def export_pdf(trip_id: str, request: Request, db: Session = Depends(get_db),
               user: Any = Depends(require_permission("trip:read"))):
    data = render_trip_pdf(db, trip_id)
    return StreamingResponse(
        io.BytesIO(data),
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="flashtrip-trip.pdf"'},
    )


@router.get("/trips/{trip_id}/export/ics")
def export_ics(trip_id: str, request: Request, scope: str = Query(default="trip"),
               db: Session = Depends(get_db),
               user: Any = Depends(require_permission("trip:read"))):
    if scope not in ("trip", "all"):
        raise AppError(ErrorCode.VALIDATION, "scope 须为 trip 或 all")
    data = render_trip_ics(db, trip_id, scope)
    return Response(
        content=data,
        media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="flashtrip.ics"'},
    )
