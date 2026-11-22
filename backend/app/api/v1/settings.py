"""设置 API：脱敏配置读写、扩展配置段（mail/weather/backup）落盘、
旅途瞬间全局默认可见性与主密钥轮换。

PUT /settings 的扩展字段由本模块转交 N1 的 save_*_config（内部负责密钥
加密与脱敏）；基础配置仍走 install_service.update_config，顺序不可颠倒，
否则 ConfigStore 的整份写回会覆盖掉刚保存的扩展段。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app import __version__
from app.api.v1.deps import get_db, require_permission, require_user
from app.core.config_store import get_config_store
from app.core.errors import AppError, ErrorCode
from app.core.response import ok
from app.models.config import UserPreferences
from app.services import backup_service, install_service as svc, mail_service, weather_service

router = APIRouter(tags=["settings"])


def _assert_unlocked() -> None:
    if not get_config_store().is_unlocked():
        raise AppError(ErrorCode.INSTALL_LOCKED, "配置已锁定，请先解锁后再修改设置")


def _moment_default_public(db: Session, user) -> bool:
    """读当前用户的瞬间默认可见性；无偏好行时返回 False（默认私有）。"""
    user_id = getattr(user, "id", None)
    if user_id is None:
        return False
    try:
        pref = db.get(UserPreferences, user_id)
        return bool(getattr(pref, "moment_default_public", False))
    except Exception:  # noqa: BLE001  偏好表未迁移时安全降级
        return False


def _settings_view(db: Session, user) -> dict:
    """统一组装 GET/PUT 返回的脱敏视图。

    read_config_sanitized 已把 mail/weather/backup 段替换为各 service 的
    脱敏摘要（不含 password_enc / *_key_enc）。为兼容既有前端与测试契约，
    顶层仍直接展开 config 的字段（如 map / security），同时提供 config
    镜像供新前端按命名空间读取；mail/weather/backup 另有顶层快捷引用。
    """
    cfg = svc.read_config_sanitized()
    view = dict(cfg)
    view.update({
        "version": __version__,
        "config": dict(cfg),
        "mail": cfg.get("mail") or {},
        "weather": cfg.get("weather") or {},
        "backup": cfg.get("backup") or {},
        "moment_default_public": _moment_default_public(db, user),
    })
    return view


@router.get("/settings")
def get_settings(request: Request, db: Session = Depends(get_db),
                 user=Depends(require_user)):
    return ok(_settings_view(db, user), request_id=getattr(request.state, "request_id", ""))


@router.put("/settings")
def put_settings(
    payload: svc.ConfigUpdateIn,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(require_permission("trip:settings")),
):
    # AI/地图供应商、默认底图、AI 工具开关属于业务配置，登录后即可修改；
    # 数据库 / 主密钥 / Redis 等危险项仍由 PUT /wizard/config 走解锁门禁。
    # ① 先写基础配置（整份 config.json 落盘）
    svc.update_config(db, payload)

    # ② 扩展段交给 N1 的 save_*_config：基于最新 config.json 合并、密钥加密、返回脱敏
    if payload.mail is not None:
        mail_service.save_mail_config(payload.mail)
    if payload.weather is not None:
        weather_service.save_weather_config(payload.weather)
    if payload.backup is not None:
        backup_service.save_backup_config(payload.backup)

    # ③ 全局默认可见性写 UserPreferences（不进 config.json）
    if payload.moment_default_public is not None:
        user_id = getattr(user, "id", None)
        if user_id is not None:
            pref = db.get(UserPreferences, user_id)
            if pref is None:
                db.add(UserPreferences(
                    user_id=user_id,
                    moment_default_public=bool(payload.moment_default_public),
                ))
            else:
                pref.moment_default_public = bool(payload.moment_default_public)
            db.commit()

    return ok(_settings_view(db, user), request_id=getattr(request.state, "request_id", ""))


@router.post("/settings/secret/rotate")
def rotate_secret(
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(require_permission("trip:settings")),
):
    _assert_unlocked()
    return ok(svc.rotate_secret(db), request_id=getattr(request.state, "request_id", ""))
