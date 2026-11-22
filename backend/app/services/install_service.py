"""安装向导服务：连通性探测、原子安装、锁定/解锁、脱敏配置读写、密钥轮换与体检。

安全约定：
- 所有 API Key 经 encrypt() 后存 *_enc；明文绝不落盘、绝不返回前端、绝不写日志。
- 日志只记录异常类型名，不记录异常消息（可能回显 key/连接串）。
- config.json 为权威源，DB 侧由 ConfigStore 镜像兜底。
"""
from __future__ import annotations

import json
import secrets
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from alembic import command
from alembic.config import Config as AlembicConfig
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from app import __version__
from app.core.config import (
    config_path,
    data_dir,
    get_settings,
    installed_marker_path,
    resolve_database_url,
    resolve_redis_url,
    static_dir,
)
from app.core.config_store import get_config_store
from app.core.errors import AppError, ErrorCode
from app.core.logging import get_logger
from app.core.security import decrypt, encrypt, hash_password, new_id, verify_password
from app.db.session import get_session, reset_engine
from app.models.config import (
    AiProviderConfig,
    AppConfig,
    InstallState,
    MapProviderConfig,
    UserPreferences,
)
from app.models.user import User
from app.services import auth_service

log = get_logger(__name__)
_BACKEND_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------- 请求 DTO

class DbTestIn(BaseModel):
    url: str = ""


class RedisTestIn(BaseModel):
    url: str = ""


class AiTestIn(BaseModel):
    base_url: str = Field(min_length=1)
    api_key: str = ""
    timeout_s: float = 10.0


class MapTestIn(BaseModel):
    style_url: str = ""
    tile_url_template: str = ""
    key: str = ""


class AdminIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=8, max_length=256)
    email: str | None = None
    phone: str | None = None
    display_name: str = ""


class AiProviderIn(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    base_url: str = ""
    api_key: str = ""
    # 模型名动态来自 /models 或手填，绝不硬编码
    model: str = ""
    enabled: bool = True
    priority: int = 0
    timeout_s: int = 60
    supports_stream: bool = True


class MapProviderIn(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    key: str = ""
    style_url: str = ""
    tile_url_template: str = ""
    default_style: str = ""
    coord_system: str = "WGS84"
    attribution: str = ""
    audit_number: str = ""
    enabled: bool = True
    needs_token: bool = False


class InstallIn(BaseModel):
    database_url: str = "sqlite:////data/flashtrip.db"
    database_dialect: str = ""
    redis_url: str = ""
    redis_enabled: bool = False
    admin: AdminIn
    ai_providers: list[AiProviderIn] = Field(default_factory=list)
    map_providers: list[MapProviderIn] = Field(default_factory=list)
    map_default_provider_id: str = "openfreemap"
    audit_number: str = ""
    ai_tools_enabled: bool = False
    # 可选自带主密钥；env FLASHTRIP_SECRET_KEY 优先级更高
    secret_key: str = ""


class ConfigUpdateIn(BaseModel):
    redis_url: str | None = None
    redis_enabled: bool | None = None
    ai_providers: list[AiProviderIn] | None = None
    map_providers: list[MapProviderIn] | None = None
    map_default_provider_id: str | None = None
    audit_number: str | None = None
    ai_tools_enabled: bool | None = None


class UnlockIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


# ---------------------------------------------------------------- 连通性探测

def test_database(payload: DbTestIn) -> dict:
    """SELECT 1 + 取版本，3s 超时；失败 DB_CONNECT_FAILED。"""
    url = (payload.url or resolve_database_url()).strip()
    if not url:
        raise AppError(ErrorCode.DB_CONNECT_FAILED, "数据库连接串为空")
    kwargs: dict[str, Any] = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"timeout": 3}
    elif url.startswith("postgres"):
        kwargs["connect_args"] = {"connect_timeout": 3}
    engine = create_engine(url, **kwargs)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            dialect = conn.dialect.name
            if dialect == "sqlite":
                version = conn.execute(text("SELECT sqlite_version()")).scalar()
            elif dialect.startswith("postgres"):
                version = conn.execute(text("SELECT version()")).scalar()
            else:
                version = ""
        return {"ok": True, "dialect": dialect, "version": str(version or "")}
    except Exception as exc:  # noqa: BLE001  错误消息可能含连接串，只记录类型
        log.warning("wizard.db_test_failed", error=type(exc).__name__)
        raise AppError(ErrorCode.DB_CONNECT_FAILED, f"数据库连接失败：{type(exc).__name__}") from exc
    finally:
        engine.dispose()


def test_redis(payload: RedisTestIn) -> dict:
    url = (payload.url or resolve_redis_url()).strip()
    if not url:
        return {"ok": True, "enabled": False, "message": "未配置 Redis（可跳过）"}
    try:
        import redis

        client = redis.Redis.from_url(url, socket_connect_timeout=3, socket_timeout=3)
        pong = client.ping()
        client.close()
        return {"ok": bool(pong), "enabled": True}
    except Exception as exc:  # noqa: BLE001
        log.warning("wizard.redis_test_failed", error=type(exc).__name__)
        raise AppError(ErrorCode.DB_CONNECT_FAILED, f"Redis 连接失败：{type(exc).__name__}") from exc


def test_ai(payload: AiTestIn) -> dict:
    """用原生 openai SDK 探测 /models，动态返回模型名列表；绝不硬编码模型名。"""
    try:
        from openai import OpenAI

        client = OpenAI(
            base_url=payload.base_url,
            api_key=payload.api_key or "sk-probe-placeholder",
            timeout=payload.timeout_s,
            max_retries=0,
        )
        try:
            result = client.models.list()
            models = sorted({str(m.id) for m in result.data})
        finally:
            client.close()
        return {"ok": True, "models": models}
    except Exception as exc:  # noqa: BLE001
        log.warning("wizard.ai_test_failed", error=type(exc).__name__)
        raise AppError(ErrorCode.AI_PROVIDER_ERROR, f"AI 供应商探测失败：{type(exc).__name__}") from exc


def test_map(payload: MapTestIn) -> dict:
    url = (payload.style_url or payload.tile_url_template).strip()
    if not url:
        return {"ok": True, "skipped": True, "message": "未配置地图地址，跳过探测"}
    if payload.key:
        url = url.replace("{key}", payload.key).replace("{token}", payload.key)
    try:
        resp = httpx.get(url, timeout=3.0, follow_redirects=True)
        if resp.status_code >= 400:
            raise AppError(ErrorCode.MAP_PROVIDER_ERROR, f"地图地址返回 HTTP {resp.status_code}")
        return {"ok": True, "status_code": resp.status_code}
    except AppError:
        raise
    except Exception as exc:  # noqa: BLE001
        log.warning("wizard.map_test_failed", error=type(exc).__name__)
        raise AppError(ErrorCode.MAP_PROVIDER_ERROR, f"地图探测失败：{type(exc).__name__}") from exc


# ---------------------------------------------------------------- 安装状态 / 配置脱敏

def wizard_status() -> dict:
    store = get_config_store()
    installed = store.is_installed()
    unlocked = store.is_unlocked()
    step_defs = (
        ("database", "数据库"),
        ("admin", "管理员"),
        ("ai", "AI 供应商"),
        ("map", "地图"),
        ("security", "安全"),
        ("confirm", "确认"),
    )
    return {
        "installed": installed,
        "unlocked": unlocked,
        "steps": [{"key": key, "label": label, "done": installed} for key, label in step_defs],
        "version": __version__,
    }


def read_config_sanitized() -> dict:
    """脱敏配置：主密钥打码、所有 *_enc 替换为布尔标记，密文绝不出后端。"""
    cfg = deepcopy(get_config_store().load())
    if "secret_key" in cfg:
        cfg["secret_key"] = "***"
    for provider in (cfg.get("ai") or {}).get("providers", []) or []:
        enc = provider.pop("api_key_enc", "")
        provider.pop("api_key", None)
        provider["has_api_key"] = bool(enc)
    for provider in (cfg.get("map") or {}).get("providers", []) or []:
        enc = provider.pop("key_enc", "")
        provider.pop("key", None)
        provider["has_key"] = bool(enc)
    return cfg


# ---------------------------------------------------------------- 配置构造 / DB 同步

def _dialect(url: str) -> str:
    head = url.split(":", 1)[0]
    return "sqlite" if head == "sqlite" else head


def _base_config(payload: InstallIn, secret_key: str) -> dict:
    return {
        "installed": False,
        "installed_at": "",
        "version": __version__,
        "secret_key": secret_key,
        "database": {
            "url": payload.database_url,
            "dialect": payload.database_dialect or _dialect(payload.database_url),
        },
        "redis": {"url": payload.redis_url, "enabled": bool(payload.redis_enabled and payload.redis_url)},
        "ai": {"providers": []},
        "map": {
            "providers": [],
            "default_provider_id": payload.map_default_provider_id,
            "audit_number": payload.audit_number,
        },
        "security": {"ai_tools_enabled": payload.ai_tools_enabled},
    }


def _build_config(payload: InstallIn, secret_key: str) -> dict:
    """构造完整 config.json；api_key/key 经 encrypt() 后写入 *_enc。"""
    cfg = _base_config(payload, secret_key)
    cfg["ai"]["providers"] = [
        {
            "id": p.id,
            "base_url": p.base_url,
            "api_key_enc": encrypt(p.api_key) if p.api_key else "",
            "model": p.model,
            "enabled": p.enabled,
            "priority": p.priority,
            "timeout_s": p.timeout_s,
        }
        for p in payload.ai_providers
    ]
    cfg["map"]["providers"] = [
        {
            "id": p.id,
            "key_enc": encrypt(p.key) if p.key else "",
            "style_url": p.style_url,
            "tile_url_template": p.tile_url_template,
            "default_style": p.default_style,
            "coord_system": p.coord_system,
            "attribution": p.attribution,
            "audit_number": p.audit_number,
            "enabled": p.enabled,
            "needs_token": p.needs_token,
        }
        for p in payload.map_providers
    ]
    return cfg


def _sync_provider_tables(db: Session, cfg: dict) -> None:
    """把 config.json 的供应商配置镜像到 DB（按 provider_id 幂等 upsert）。"""
    for p in (cfg.get("ai") or {}).get("providers", []) or []:
        row = (
            db.query(AiProviderConfig)
            .filter(AiProviderConfig.provider_id == p["id"])
            .first()
        )
        if row is None:
            row = AiProviderConfig(provider_id=p["id"])
            db.add(row)
        row.base_url = p.get("base_url", "")
        row.api_key_enc = p.get("api_key_enc", "")
        row.model = p.get("model", "")
        row.enabled = bool(p.get("enabled", True))
        row.priority = int(p.get("priority", 0))
        row.timeout_s = int(p.get("timeout_s", 60))
        row.supports_stream = True
    for p in (cfg.get("map") or {}).get("providers", []) or []:
        row = (
            db.query(MapProviderConfig)
            .filter(MapProviderConfig.provider_id == p["id"])
            .first()
        )
        if row is None:
            row = MapProviderConfig(provider_id=p["id"])
            db.add(row)
        row.key_enc = p.get("key_enc", "")
        row.style_url = p.get("style_url", "")
        row.tile_url_template = p.get("tile_url_template", "")
        row.default_style = p.get("default_style", "")
        row.coord_system = p.get("coord_system", "WGS84")
        row.attribution = p.get("attribution", "")
        row.audit_number = p.get("audit_number", "")
        row.enabled = bool(p.get("enabled", True))
        row.needs_token = bool(p.get("needs_token", False))


def _sync_preferences(db: Session, cfg: dict, *, admin_id: str | None = None) -> None:
    """AI 工具总开关 / 默认底图同步到用户偏好。"""
    ai_tools = bool((cfg.get("security") or {}).get("ai_tools_enabled"))
    default_map = (cfg.get("map") or {}).get("default_provider_id", "openfreemap")
    rows = db.query(UserPreferences).all()
    for row in rows:
        row.ai_tools_enabled = ai_tools
        row.default_map_provider_id = default_map
    if admin_id is not None and not any(r.user_id == admin_id for r in rows):
        db.add(
            UserPreferences(
                user_id=admin_id,
                current_trip_id=None,
                theme="light",
                default_map_provider_id=default_map,
                ai_tools_enabled=ai_tools,
            )
        )


def _seed_database(db: Session, payload: InstallIn, cfg: dict) -> None:
    """创建 argon2 管理员 + 写供应商表 / 用户偏好 / 安装状态单例。"""
    admin = db.query(User).filter(User.username == payload.admin.username).first()
    if admin is None:
        admin = auth_service.create_user(
            db,
            username=payload.admin.username,
            password=payload.admin.password,
            role="owner",
            email=payload.admin.email,
            phone=payload.admin.phone,
            display_name=payload.admin.display_name,
        )
    else:
        # 重装（已解锁）时复用账号并重置密码/角色
        admin.password_hash = hash_password(payload.admin.password)
        admin.role = "owner"
        admin.is_active = True
        admin.must_set_password = False
        admin.password_set_at = datetime.now(timezone.utc)

    _sync_provider_tables(db, cfg)
    _sync_preferences(db, cfg, admin_id=admin.id)

    # 迁移版本以 alembic_version 为准，绝不硬编码 revision（新增迁移后自动跟随 head）
    try:
        schema_version = str(
            db.execute(text("SELECT version_num FROM alembic_version")).scalar() or ""
        )
    except Exception:  # noqa: BLE001  极端情况下表尚未就绪，留空由 health 兜底
        schema_version = ""
    now = datetime.now(timezone.utc)
    state = db.get(InstallState, 1)
    if state is None:
        db.add(
            InstallState(
                id=1,
                installed=True,
                schema_version=schema_version,
                install_completed_at=now,
                unlocked_at=None,
                unlock_actor_id=None,
            )
        )
    else:
        state.installed = True
        state.schema_version = schema_version
        state.install_completed_at = now


# ---------------------------------------------------------------- 安装 / 回滚

def _alembic_config() -> AlembicConfig:
    cfg = AlembicConfig(str(_BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_BACKEND_ROOT / "alembic"))
    return cfg


def _validate_install(payload: InstallIn) -> None:
    """逐项校验向导输入；真实连通性只探测 DB（AI/地图/Redis 由独立 test-* 端点先行验证）。"""
    if not payload.database_url.strip():
        raise AppError(ErrorCode.VALIDATION, "数据库连接串不能为空")
    if not payload.admin.username.strip() or len(payload.admin.password) < 8:
        raise AppError(ErrorCode.VALIDATION, "管理员账号或密码不合法（密码至少 8 位）")
    seen: set[str] = set()
    for p in payload.ai_providers:
        if p.id in seen:
            raise AppError(ErrorCode.VALIDATION, f"AI 供应商 id 重复：{p.id}")
        seen.add(p.id)
        if p.enabled and not p.base_url.strip():
            raise AppError(ErrorCode.VALIDATION, f"AI 供应商 {p.id} 未配置 base_url")
    seen.clear()
    for p in payload.map_providers:
        if p.id in seen:
            raise AppError(ErrorCode.VALIDATION, f"地图供应商 id 重复：{p.id}")
        seen.add(p.id)
        if p.needs_token and not p.key:
            raise AppError(ErrorCode.VALIDATION, f"地图供应商 {p.id} 需要 token/key")
    test_database(DbTestIn(url=payload.database_url))


def _rollback_install(alembic_cfg: AlembicConfig | None, original_raw: str | None, had_marker: bool) -> None:
    """删除半成品配置并尽力回滚迁移，恢复安装前现场。"""
    if alembic_cfg is not None:
        try:
            command.downgrade(alembic_cfg, "base")
        except Exception:  # noqa: BLE001  回滚失败不掩盖原始错误
            log.warning("wizard.downgrade_failed")
    reset_engine()
    path = config_path()
    try:
        if original_raw is None:
            if path.exists():
                path.unlink()
        else:
            path.write_text(original_raw, encoding="utf-8")
    except OSError:
        log.warning("wizard.config_restore_failed")
    marker = installed_marker_path()
    try:
        if had_marker and not marker.exists():
            marker.write_text("installed\n", encoding="utf-8")
        elif not had_marker and marker.exists():
            marker.unlink()
    except OSError:
        log.warning("wizard.marker_restore_failed")


def perform_install(payload: InstallIn) -> dict:
    """原子安装：任一步失败删除半成品配置并回滚，绝不留下 installed=true 的假象。"""
    store = get_config_store()
    if store.is_installed() and not store.is_unlocked():
        raise AppError(ErrorCode.INSTALL_LOCKED, "系统已安装且未解锁，请先解锁后再重新配置")
    _validate_install(payload)

    env_secret = get_settings().SECRET_KEY
    if env_secret:
        # env 优先级高于 config.json，必须沿用，否则新旧密钥不一致
        secret_key, need_backup = env_secret, False
    elif payload.secret_key:
        secret_key, need_backup = payload.secret_key, True
    else:
        secret_key, need_backup = secrets.token_urlsafe(48), True

    original_raw: str | None = None
    if config_path().exists():
        try:
            original_raw = config_path().read_text(encoding="utf-8")
        except OSError:
            original_raw = None
    had_marker = installed_marker_path().exists()

    db: Session | None = None
    alembic_cfg: AlembicConfig | None = None
    try:
        # ① 未完成态骨架：先落盘主密钥，保证 encrypt()/decrypt() 可用
        store.save(_base_config(payload, secret_key))
        # ② 完整配置（仍为 installed=false）
        cfg = _build_config(payload, secret_key)
        store.save(cfg)
        # ③ 重建引擎 → alembic upgrade head
        reset_engine()
        alembic_cfg = _alembic_config()
        command.upgrade(alembic_cfg, "head")
        # ④ 业务数据（argon2 管理员、供应商、偏好、单例状态）
        SessionLocal = get_session()
        db = SessionLocal()
        _seed_database(db, payload, cfg)
        db.commit()
        # ⑤ 标记安装完成
        cfg["installed_at"] = datetime.now(timezone.utc).isoformat()
        store.mark_installed(cfg)
    except Exception as exc:
        if db is not None:
            db.rollback()
        _rollback_install(alembic_cfg, original_raw, had_marker)
        if isinstance(exc, AppError):
            raise
        log.error("wizard.install_failed", error=type(exc).__name__)
        raise AppError(ErrorCode.INTERNAL, "安装失败，已回滚半成品配置") from exc
    finally:
        if db is not None:
            db.close()

    result: dict[str, Any] = {"installed": True, "need_backup_secret": need_backup}
    if need_backup:
        result["secret_key"] = secret_key
    return result


# ---------------------------------------------------------------- 解锁 / 配置更新 / 轮换

def unlock(db: Session, payload: UnlockIn) -> dict:
    """校验管理员密码 + 写审计 + 设置 cfg['unlocked_at']。"""
    store = get_config_store()
    user = (
        db.query(User)
        .filter(User.username == payload.username, User.is_active.is_(True))
        .first()
    )
    if user is None or not verify_password(user.password_hash, payload.password):
        raise AppError(ErrorCode.UNAUTHORIZED, "管理员密码错误")
    if user.role not in ("owner", "admin"):
        raise AppError(ErrorCode.FORBIDDEN, "需要 owner / admin 权限")

    now = datetime.now(timezone.utc)
    state = db.get(InstallState, 1)
    if state is not None:
        state.unlocked_at = now
        state.unlock_actor_id = user.id
    db.add(
        AppConfig(
            key=f"audit:unlock:{new_id()}",
            value_plain=json.dumps(
                {
                    "action": "wizard:unlock",
                    "actor_id": user.id,
                    "username": user.username,
                    "at": now.isoformat(),
                },
                ensure_ascii=False,
            ),
        )
    )
    db.commit()
    cfg = store.load()
    cfg["unlocked_at"] = now.isoformat()
    store.save(cfg)
    return {"unlocked": True, "unlocked_at": now.isoformat()}


def _merge_config(cfg: dict, payload: ConfigUpdateIn) -> dict:
    """合并更新；未重新提供明文 key 的供应商保留原有密文，避免误清密钥。"""
    cfg.setdefault("redis", {})
    cfg.setdefault("ai", {"providers": []})
    cfg.setdefault("map", {"providers": [], "default_provider_id": "openfreemap", "audit_number": ""})
    cfg.setdefault("security", {"ai_tools_enabled": False})

    if payload.redis_url is not None:
        cfg["redis"]["url"] = payload.redis_url
    if payload.redis_enabled is not None:
        cfg["redis"]["enabled"] = bool(payload.redis_enabled and cfg["redis"].get("url"))
    if payload.ai_tools_enabled is not None:
        cfg["security"]["ai_tools_enabled"] = payload.ai_tools_enabled
    if payload.map_default_provider_id is not None:
        cfg["map"]["default_provider_id"] = payload.map_default_provider_id
    if payload.audit_number is not None:
        cfg["map"]["audit_number"] = payload.audit_number

    if payload.ai_providers is not None:
        old = {p.get("id"): p for p in cfg["ai"].get("providers", []) or []}
        merged = []
        for p in payload.ai_providers:
            enc = encrypt(p.api_key) if p.api_key else (old.get(p.id, {}).get("api_key_enc", ""))
            merged.append(
                {
                    "id": p.id,
                    "base_url": p.base_url,
                    "api_key_enc": enc,
                    "model": p.model,
                    "enabled": p.enabled,
                    "priority": p.priority,
                    "timeout_s": p.timeout_s,
                }
            )
        cfg["ai"]["providers"] = merged

    if payload.map_providers is not None:
        old = {p.get("id"): p for p in cfg["map"].get("providers", []) or []}
        merged = []
        for p in payload.map_providers:
            enc = encrypt(p.key) if p.key else (old.get(p.id, {}).get("key_enc", ""))
            merged.append(
                {
                    "id": p.id,
                    "key_enc": enc,
                    "style_url": p.style_url,
                    "tile_url_template": p.tile_url_template,
                    "default_style": p.default_style,
                    "coord_system": p.coord_system,
                    "attribution": p.attribution,
                    "audit_number": p.audit_number,
                    "enabled": p.enabled,
                    "needs_token": p.needs_token,
                }
            )
        cfg["map"]["providers"] = merged
    return cfg


def update_config(db: Session, payload: ConfigUpdateIn) -> dict:
    """PUT 配置：需要解锁（由 API 层校验），config.json 与 DB 同步。"""
    store = get_config_store()
    cfg = _merge_config(store.load(), payload)
    _sync_provider_tables(db, cfg)
    _sync_preferences(db, cfg)
    db.commit()
    store.save(cfg)
    return read_config_sanitized()


def rotate_secret(db: Session) -> dict:
    """轮换主密钥：解密所有 *_enc → 写新密钥 → 用新密钥重加密（DB + config.json）。"""
    if get_settings().SECRET_KEY:
        raise AppError(
            ErrorCode.VALIDATION,
            "主密钥由环境变量 FLASHTRIP_SECRET_KEY 提供，请直接更换该变量并重启",
        )
    store = get_config_store()
    original = deepcopy(store.load())

    # ① 用旧密钥解出全部明文（只保留纯值，不再持有 ORM 对象）
    ai_plain = {
        r.id: decrypt(r.api_key_enc)
        for r in db.query(AiProviderConfig).all()
        if r.api_key_enc
    }
    map_plain = {
        r.id: decrypt(r.key_enc)
        for r in db.query(MapProviderConfig).all()
        if r.key_enc
    }
    app_plain = {
        r.key: decrypt(r.value_enc)
        for r in db.query(AppConfig).filter(AppConfig.value_enc.isnot(None)).all()
        if r.value_enc
    }
    cfg_ai_plain = [
        decrypt(p.get("api_key_enc", ""))
        for p in (original.get("ai") or {}).get("providers", []) or []
    ]
    cfg_map_plain = [
        decrypt(p.get("key_enc", ""))
        for p in (original.get("map") or {}).get("providers", []) or []
    ]
    db.rollback()  # 结束只读事务，避免与 ConfigStore 独立连接争用 SQLite 写锁

    new_key = secrets.token_urlsafe(48)
    new_cfg = deepcopy(original)
    new_cfg["secret_key"] = new_key
    try:
        # ② 先切换 config.json 主密钥，此后 encrypt() 使用新密钥
        store.save(new_cfg)
        # ③ 用新密钥重加密 DB
        for row in db.query(AiProviderConfig).all():
            if row.id in ai_plain:
                row.api_key_enc = encrypt(ai_plain[row.id])
        for row in db.query(MapProviderConfig).all():
            if row.id in map_plain:
                row.key_enc = encrypt(map_plain[row.id])
        for row in db.query(AppConfig).filter(AppConfig.value_enc.isnot(None)).all():
            if row.key in app_plain:
                row.value_enc = encrypt(app_plain[row.key])
        db.commit()
        # ④ 用新密钥重加密 config.json 中的供应商密文并写回
        for i, provider in enumerate((new_cfg.get("ai") or {}).get("providers", []) or []):
            provider["api_key_enc"] = encrypt(cfg_ai_plain[i]) if cfg_ai_plain[i] else ""
        for i, provider in enumerate((new_cfg.get("map") or {}).get("providers", []) or []):
            provider["key_enc"] = encrypt(cfg_map_plain[i]) if cfg_map_plain[i] else ""
        store.save(new_cfg)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        store.save(original)
        log.error("secret.rotate_failed", error=type(exc).__name__)
        raise AppError(ErrorCode.INTERNAL, "密钥轮换失败，已回滚至原主密钥") from exc

    return {"rotated": True, "need_backup_secret": True, "secret_key": new_key}


# ---------------------------------------------------------------- 体检

def doctor() -> dict:
    """CLI 体检：配置、密钥来源、DB 连通/表清单、迁移版本、静态产物。"""
    store = get_config_store()
    cfg = store.load()
    result: dict[str, Any] = {
        "version": __version__,
        "data_dir": str(data_dir()),
        "config_exists": config_path().exists(),
        "installed": store.is_installed(),
        "unlocked": store.is_unlocked(),
        "secret_key_source": "env" if get_settings().SECRET_KEY else "config",
        "static_dir_exists": (static_dir() / "index.html").is_file(),
        "database": {"ok": False},
        "tables": [],
    }
    url = resolve_database_url()
    if not url:
        return result
    engine = create_engine(
        url,
        connect_args={"timeout": 3} if url.startswith("sqlite") else {},
        pool_pre_ping=True,
    )
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            result["database"] = {"ok": True, "dialect": conn.dialect.name}
            result["tables"] = sorted(inspect(conn).get_table_names())
            if "alembic_version" in result["tables"]:
                result["migrations_rev"] = conn.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalar()
    except Exception as exc:  # noqa: BLE001
        result["database"] = {"ok": False, "error": type(exc).__name__}
    finally:
        engine.dispose()
    return result
