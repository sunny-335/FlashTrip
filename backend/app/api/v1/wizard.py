"""安装向导 API（/api/v1/wizard/* 为公开前缀）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.v1.deps import get_db, require_permission, require_user
from app.core.config_store import get_config_store
from app.core.errors import AppError, ErrorCode
from app.core.response import ok
from app.services import install_service as svc

router = APIRouter(tags=["wizard"])


@router.get("/wizard/status")
def wizard_status(request: Request):
    return ok(svc.wizard_status(), request_id=getattr(request.state, "request_id", ""))


@router.post("/wizard/test-db")
def wizard_test_db(payload: svc.DbTestIn, request: Request):
    return ok(svc.test_database(payload), request_id=getattr(request.state, "request_id", ""))


@router.post("/wizard/test-redis")
def wizard_test_redis(payload: svc.RedisTestIn, request: Request):
    return ok(svc.test_redis(payload), request_id=getattr(request.state, "request_id", ""))


@router.post("/wizard/test-ai")
def wizard_test_ai(payload: svc.AiTestIn, request: Request):
    return ok(svc.test_ai(payload), request_id=getattr(request.state, "request_id", ""))


@router.post("/wizard/test-map")
def wizard_test_map(payload: svc.MapTestIn, request: Request):
    """按 provider_id 从预设取元数据做连通性检查；手填 style_url 保留兼容但忽略，不再要求必填。"""
    return ok(svc.test_map(payload), request_id=getattr(request.state, "request_id", ""))


@router.post("/wizard/test-mail")
def wizard_test_mail(payload: svc.MailTestIn, request: Request):
    """向导阶段试发邮件：只探测 SMTP 连通性，不落盘配置；失败返回中文原因。"""
    return ok(svc.test_mail(payload), request_id=getattr(request.state, "request_id", ""))


@router.post("/wizard/install")
def wizard_install(payload: svc.InstallIn, request: Request):
    return ok(svc.perform_install(payload), request_id=getattr(request.state, "request_id", ""))


@router.get("/wizard/config")
def wizard_get_config(request: Request):
    return ok(svc.read_config_sanitized(), request_id=getattr(request.state, "request_id", ""))


@router.put("/wizard/config")
def wizard_put_config(
    payload: svc.ConfigUpdateIn,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(require_user),
    _perm=Depends(require_permission("trip:settings")),
):
    if not get_config_store().is_unlocked():
        raise AppError(ErrorCode.INSTALL_LOCKED, "配置已锁定，请先执行 /wizard/unlock")
    return ok(svc.update_config(db, payload), request_id=getattr(request.state, "request_id", ""))


@router.post("/wizard/unlock")
def wizard_unlock(payload: svc.UnlockIn, request: Request, db: Session = Depends(get_db)):
    return ok(svc.unlock(db, payload), request_id=getattr(request.state, "request_id", ""))
