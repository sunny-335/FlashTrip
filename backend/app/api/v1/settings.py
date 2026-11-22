"""设置 API：脱敏配置读写与主密钥轮换。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app import __version__
from app.api.v1.deps import get_db, require_permission, require_user
from app.core.config_store import get_config_store
from app.core.errors import AppError, ErrorCode
from app.core.response import ok
from app.services import install_service as svc

router = APIRouter(tags=["settings"])


def _assert_unlocked() -> None:
    if not get_config_store().is_unlocked():
        raise AppError(ErrorCode.INSTALL_LOCKED, "配置已锁定，请先解锁后再修改设置")


@router.get("/settings")
def get_settings(request: Request, user=Depends(require_user)):
    return ok(
        {"version": __version__, "config": svc.read_config_sanitized()},
        request_id=getattr(request.state, "request_id", ""),
    )


@router.put("/settings")
def put_settings(
    payload: svc.ConfigUpdateIn,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(require_permission("trip:settings")),
):
    _assert_unlocked()
    return ok(svc.update_config(db, payload), request_id=getattr(request.state, "request_id", ""))


@router.post("/settings/secret/rotate")
def rotate_secret(
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(require_permission("trip:settings")),
):
    _assert_unlocked()
    return ok(svc.rotate_secret(db), request_id=getattr(request.state, "request_id", ""))
