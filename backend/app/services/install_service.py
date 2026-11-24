"""安装向导服务：连通性探测、原子安装、锁定/解锁、脱敏配置读写、密钥轮换与体检。

安全约定：
- 所有 API Key 经 encrypt() 后存 *_enc；明文绝不落盘、绝不返回前端、绝不写日志。
- 日志只记录异常类型名，不记录异常消息（可能回显 key/连接串）。
- config.json 为权威源，DB 侧由 ConfigStore 镜像兜底。
"""
from __future__ import annotations

import json
import re
import secrets
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

import httpx
from alembic import command
from alembic.config import Config as AlembicConfig
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from app import __version__
from app.core.config import (
    DEFAULT_SQLITE_URL,
    config_path,
    data_dir,
    get_settings,
    installed_marker_path,
    resolve_database_url,
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
from app.services.map.provider_registry import PROVIDER_DEFS, get_provider_key
from app.services.password_policy import validate_password

log = get_logger(__name__)
_BACKEND_ROOT = Path(__file__).resolve().parents[2]

# 供应商配置里所有可能承载密钥的字段：脱敏时一律剔除，只回布尔标记
_SECRET_FIELDS = ("key_enc", "api_key_enc", "token_enc", "key", "api_key", "token")


def _cfg_providers(section: Any) -> list[dict]:
    """把 ai/map 配置节里的 providers（list / dict / None）统一为字典列表。

    字典形式 {id: {...}} 会补上 id；非字典元素直接丢弃，保证遍历不抛异常。
    """
    raw = section.get("providers") if isinstance(section, dict) else None
    if isinstance(raw, dict):
        result: list[dict] = []
        for provider_id, value in raw.items():
            if isinstance(value, dict):
                item = dict(value)
                item.setdefault("id", provider_id)
                result.append(item)
        return result
    if isinstance(raw, list):
        return [dict(p) for p in raw if isinstance(p, dict)]
    return []


# ---------------------------------------------------------------- 请求 DTO

class DbTestIn(BaseModel):
    """数据库连接探测请求。

    兼容两种形态：
    - 结构化字段（推荐）：dialect + host/port/username/password/database；
    - 完整连接串 url（历史兼容，仍然支持）。
    """

    url: str = ""
    dialect: str = ""
    host: str = ""
    port: int = 0
    username: str = ""
    password: str = ""
    database: str = ""


class RedisTestIn(BaseModel):
    """Redis 连接探测请求：地址/端口/密码/库序号，或历史兼容的完整连接串。"""

    url: str = ""
    host: str = ""
    port: int = 0
    password: str = ""
    database: int = 0


class AiTestIn(BaseModel):
    base_url: str = Field(min_length=1)
    api_key: str = ""
    timeout_s: float = 10.0


class MapTestIn(BaseModel):
    # 按预设 provider_id 取元数据做连通性检查；手填 URL 字段保留仅为兼容旧前端，
    # 一律忽略（前端不再提交 Style URL / 瓦片模板）。
    provider_id: str = ""
    style_url: str = ""
    tile_url_template: str = ""
    key: str = ""


class AdminIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    # 必填即可；管理员密码的四类字符 / 8-32 位 / 连续串由 perform_install 统一校验
    password: str = Field(min_length=1, max_length=256)
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
    """设置页只提交业务字段；Style URL / 瓦片模板 / 坐标系 / 署名 / 审图号等
    技术元数据一律由 provider_registry.PROVIDER_DEFS 自动带出，不再手填。"""

    id: str = Field(min_length=1, max_length=64)
    key: str = ""  # 留空表示保留已有密文
    enabled: bool = True


class InstallIn(BaseModel):
    """安装请求体。

    数据库与 Redis 均可只提交结构化字段（地址/端口/用户名/密码/库名），
    由后端拼装连接串；database_url / redis_url 仍作为兼容字段保留。
    """

    database_url: str = ""
    database_dialect: str = ""
    # 结构化数据库字段（PostgreSQL）
    db_host: str = ""
    db_port: int = 0
    db_username: str = ""
    db_password: str = ""
    db_name: str = "flashtrip"
    redis_url: str = ""
    redis_enabled: bool = False
    # 结构化 Redis 字段
    redis_host: str = ""
    redis_port: int = 0
    redis_password: str = ""
    redis_db: int = 0
    admin: AdminIn
    ai_providers: list[AiProviderIn] = Field(default_factory=list)
    map_providers: list[MapProviderIn] = Field(default_factory=list)
    map_default_provider_id: str = "amap"
    audit_number: str = ""
    ai_tools_enabled: bool = True
    # 邮件通知：向导可配置也可跳过；跳过时只写 mail_skipped 标记。
    # 字段与 mail_service._MAIL_DEFAULTS 一致，password 明文仅在内存中，落盘加密。
    mail: dict | None = None
    mail_skipped: bool = False
    # 可选自带主密钥；env FLASHTRIP_SECRET_KEY 优先级更高
    secret_key: str = ""


class MailTestIn(BaseModel):
    """向导/设置页「发送测试邮件」请求体；与 mail 段字段一致。"""

    enabled: bool = True
    host: str = ""
    port: int = 465
    user: str = ""
    password: str = ""
    from_addr: str = ""
    from_name: str = "瞬旅 FlashTrip"
    use_ssl: bool = True
    use_tls: bool = False
    timeout_s: int = 10
    default_recipients: list[str] = Field(default_factory=list)


def test_mail(payload: MailTestIn) -> dict:
    """向导阶段试发邮件：不落盘配置，直接把表单覆盖值交给 mail_service。"""
    from app.services import mail_service  # 局部导入，避免与配置模块形成循环依赖

    return mail_service.test_mail(payload.model_dump())


class ConfigUpdateIn(BaseModel):
    redis_url: str | None = None
    redis_enabled: bool | None = None
    ai_providers: list[AiProviderIn] | None = None
    map_providers: list[MapProviderIn] | None = None
    map_default_provider_id: str | None = None
    audit_number: str | None = None
    ai_tools_enabled: bool | None = None
    # 扩展配置段：由 settings.py 交给 N1 的 save_*_config 落盘；
    # _merge_config 刻意忽略它们，避免把含密文的原始 dict 直接写进 config.json。
    mail: dict | None = None
    weather: dict | None = None
    backup: dict | None = None
    # 新建旅途瞬间是否默认公开（写 user_preferences，不进 config.json）
    moment_default_public: bool | None = None


class UnlockIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


# ---------------------------------------------------------------- 连接串构造

_PG_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")
_DEFAULT_PG_PORT = 5432
_DEFAULT_REDIS_PORT = 6379


def build_database_url(
    dialect: str,
    *,
    host: str = "",
    port: int = 0,
    username: str = "",
    password: str = "",
    database: str = "",
) -> str:
    """按结构化字段拼装连接串；SQLite 固定走数据目录单文件。

    - SQLite：忽略其余字段，返回 sqlite:////data/flashtrip.db。
    - PostgreSQL：缺省端口 5432；用户名/密码为空时省略对应片段。
    """
    if dialect != "postgresql":
        return DEFAULT_SQLITE_URL
    host = (host or "").strip()
    if not host:
        raise AppError(ErrorCode.VALIDATION, "数据库地址不能为空")
    port_num = int(port or _DEFAULT_PG_PORT)
    db_name = (database or "flashtrip").strip() or "flashtrip"
    user = (username or "").strip()
    secret = password or ""
    auth = ""
    if user:
        auth = quote(user, safe="")
        if secret:
            auth += f":{quote(secret, safe='')}"
        auth += "@"
    return f"postgresql://{auth}{host}:{port_num}/{db_name}"


def build_redis_url(
    *,
    host: str = "",
    port: int = 0,
    password: str = "",
    database: int = 0,
) -> str:
    """按结构化字段拼装 Redis 连接串；密码为空时省略认证片段。"""
    host = (host or "").strip()
    if not host:
        return ""
    port_num = int(port or _DEFAULT_REDIS_PORT)
    db_index = int(database or 0)
    auth = ""
    if password:
        auth = f":{quote(password, safe='')}@"
    return f"redis://{auth}{host}:{port_num}/{db_index}"


def _ensure_pg_database(url: str, db_name: str) -> None:
    """连接目标库不存在时自动创建（先连 postgres 维护库执行 CREATE DATABASE）。

    已存在则跳过；权限不足时抛出中文提示，绝不静默继续。
    """
    if not _PG_IDENT_RE.match(db_name):
        raise AppError(ErrorCode.VALIDATION, f"数据库名不合法：{db_name}")
    parts = urlsplit(url)
    maintenance = urlunsplit((parts.scheme, parts.netloc, "/postgres", parts.query, parts.fragment))
    try:
        engine = create_engine(
            maintenance, connect_args={"connect_timeout": 5}, pool_pre_ping=True,
            isolation_level="AUTOCOMMIT",
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("wizard.pg_engine_failed", error=type(exc).__name__)
        return
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": db_name}
            ).scalar()
            if not exists:
                conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    except Exception as exc:  # noqa: BLE001  异常消息可能含连接串，只记录类型
        log.warning("wizard.pg_ensure_database_failed", error=type(exc).__name__)
        raise AppError(
            ErrorCode.DB_CONNECT_FAILED,
            f"无法创建数据库 {db_name}：请确认账号具备建库权限（{type(exc).__name__}）",
        ) from exc
    finally:
        engine.dispose()


# ---------------------------------------------------------------- 连通性探测

def test_database(payload: DbTestIn) -> dict:
    """SELECT 1 + 取版本，3s 超时；失败 DB_CONNECT_FAILED。

    PostgreSQL 场景下会先确保目标库存在（不存在则自动创建），再连目标库校验。
    """
    url = (payload.url or "").strip()
    db_name = (payload.database or "").strip()
    if not url:
        url = build_database_url(
            payload.dialect or "sqlite",
            host=payload.host,
            port=payload.port,
            username=payload.username,
            password=payload.password,
            database=db_name,
        )
    if not url:
        raise AppError(ErrorCode.DB_CONNECT_FAILED, "数据库连接串为空")
    if url.startswith("postgres") and db_name:
        _ensure_pg_database(url, db_name)
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
    url = (payload.url or "").strip()
    if not url:
        url = build_redis_url(
            host=payload.host,
            port=payload.port,
            password=payload.password,
            database=payload.database,
        )
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
    """按 provider_id 从预设取元数据做连通性检查，不再要求手填 Style URL。

    手填的 style_url / tile_url_template 字段保留仅为兼容旧前端，一律忽略；
    探测地址只能来自 PROVIDER_DEFS，避免把矢量底图误配成 raster 代理。
    """
    provider_id = (payload.provider_id or "").strip()
    if not provider_id:
        return {"ok": True, "skipped": True, "message": "未选择地图供应商，跳过探测"}
    defn = next((d for d in PROVIDER_DEFS if d["id"] == provider_id), None)
    if defn is None:
        raise AppError(ErrorCode.MAP_PROVIDER_ERROR, f"未知地图供应商：{provider_id}")
    # 只取 http(s) 地址：mapbox:// 是矢量样式伪协议，改走其瓦片模板
    url = ""
    for candidate in (defn.get("styleUrl"), defn.get("tileUrlTemplate")):
        if isinstance(candidate, str) and candidate.startswith(("http://", "https://")):
            url = candidate.strip()
            break
    if not url:
        return {"ok": True, "skipped": True, "message": "该供应商无可探测地址，跳过探测"}

    # 密钥：请求体优先，否则复用已保存的密文；明文/密文绝不写入日志
    key = payload.key
    if not key and defn.get("needsToken"):
        try:
            key = get_provider_key(get_config_store().load(), provider_id)
        except AppError:
            key = ""
    if any(token in url for token in ("{key}", "{token}", "{access_token}")) and not key:
        return {"ok": True, "skipped": True, "message": "该供应商需要先配置密钥，跳过探测"}
    url = (url.replace("{key}", key)
              .replace("{token}", key)
              .replace("{access_token}", key))
    subs = defn.get("subdomains") or []
    if "{s}" in url:
        url = url.replace("{s}", str(subs[0]) if subs else "0")
    # 用一组固定瓦片坐标展开占位符，仅用于连通性探测
    url = url.replace("{z}", "0").replace("{x}", "0").replace("{y}", "0")
    try:
        resp = httpx.get(url, timeout=3.0, follow_redirects=True)
        if resp.status_code >= 400:
            raise AppError(ErrorCode.MAP_PROVIDER_ERROR, f"地图地址返回 HTTP {resp.status_code}")
        return {"ok": True, "status_code": resp.status_code}
    except AppError:
        raise
    except Exception as exc:  # noqa: BLE001  异常可能回显含密钥的 URL，只记录类型
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
    """脱敏配置：主密钥打码、所有密钥字段替换为布尔标记，密文/明文绝不出后端。

    ai.providers / map.providers 为 list、dict、None 或配置节缺失时均安全处理。
    """
    cfg = deepcopy(get_config_store().load())
    if "secret_key" in cfg:
        cfg["secret_key"] = "***"
    ai_section = cfg.get("ai")
    ai_providers = _cfg_providers(ai_section)
    for provider in ai_providers:
        has_key = any(bool(provider.get(field)) for field in _SECRET_FIELDS)
        for field in _SECRET_FIELDS:
            provider.pop(field, None)
        provider["has_api_key"] = has_key
    if isinstance(ai_section, dict):
        ai_section["providers"] = ai_providers
    map_section = cfg.get("map")
    map_providers = _cfg_providers(map_section)
    for provider in map_providers:
        has_key = any(bool(provider.get(field)) for field in _SECRET_FIELDS)
        for field in _SECRET_FIELDS:
            provider.pop(field, None)
        provider["has_key"] = has_key
    if isinstance(map_section, dict):
        map_section["providers"] = map_providers
    # mail / weather / backup 段可能含 password_enc / *_key_enc 密文，
    # 一律替换为各 service 的脱敏摘要，密文绝不出后端。
    try:
        from app.services import backup_service, mail_service, weather_service

        cfg["mail"] = mail_service.get_mail_config()
        cfg["weather"] = weather_service.get_weather_config()
        cfg["backup"] = backup_service.get_backup_config()
    except Exception as exc:  # noqa: BLE001  摘要读取失败也要保证不泄露原始段
        log.warning("wizard.extended_config_redact_failed", error=type(exc).__name__)
        for section in ("mail", "weather", "backup"):
            cfg.pop(section, None)
    return cfg


# ---------------------------------------------------------------- 配置构造 / DB 同步

def _dialect(url: str) -> str:
    head = url.split(":", 1)[0]
    return "sqlite" if head == "sqlite" else head


def _resolved_database_url(payload: InstallIn) -> tuple[str, str]:
    """返回 (连接串, 方言)。

    优先使用结构化字段拼装；仅当结构化字段为空时回退到提交的连接串。
    """
    dialect = (payload.database_dialect or "").strip()
    structured = bool(payload.db_host.strip()) or dialect == "postgresql"
    if structured:
        if not dialect:
            dialect = "postgresql"
        url = build_database_url(
            dialect,
            host=payload.db_host,
            port=payload.db_port,
            username=payload.db_username,
            password=payload.db_password,
            database=payload.db_name,
        )
        return url, dialect
    url = (payload.database_url or "").strip()
    if not url:
        return DEFAULT_SQLITE_URL, "sqlite"
    return url, (dialect or _dialect(url))


def _resolved_redis_url(payload: InstallIn) -> str:
    """返回 Redis 连接串；结构化字段优先，回退到提交的 url。"""
    if payload.redis_host.strip():
        return build_redis_url(
            host=payload.redis_host,
            port=payload.redis_port,
            password=payload.redis_password,
            database=payload.redis_db,
        )
    return (payload.redis_url or "").strip()


def _base_config(payload: InstallIn, secret_key: str) -> dict:
    db_url, db_dialect = _resolved_database_url(payload)
    redis_url = _resolved_redis_url(payload)
    return {
        "installed": False,
        "installed_at": "",
        "version": __version__,
        "secret_key": secret_key,
        "database": {
            "url": db_url,
            "dialect": db_dialect,
        },
        "redis": {"url": redis_url, "enabled": bool(payload.redis_enabled and redis_url)},
        "ai": {"providers": []},
        "map": {
            "providers": [],
            "default_provider_id": payload.map_default_provider_id,
            "audit_number": payload.audit_number,
        },
        "security": {"ai_tools_enabled": payload.ai_tools_enabled},
        # N1 的 mail / weather / backup service 均以 cfg.get(section, {}) 兜底，
        # 安装时预置空段，保证首次读配置即可用、save_*_config 合并写入不报错。
        "mail": {},
        "weather": {},
        "backup": {},
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
    # config.json 只存业务字段（id / 密钥 / 启用状态）；Style URL、瓦片模板、
    # 坐标系、署名、审图号等元数据一律由 PROVIDER_DEFS 预设带出，不落盘手填值。
    cfg["map"]["providers"] = [
        {
            "id": p.id,
            "key_enc": encrypt(p.key) if p.key else "",
            "enabled": p.enabled,
        }
        for p in payload.map_providers
    ]
    # 邮件通知：向导可配置也可跳过。跳过时保持空段（后续在设置页补齐）；
    # 未跳过则按 mail_service 默认字段做纯内存合并，password 明文只在此处
    # 经 encrypt() 转成 password_enc，绝不写日志、绝不返回前端。
    if payload.mail and not payload.mail_skipped:
        from app.services.mail_service import _MAIL_DEFAULTS  # 局部导入避免循环依赖

        section: dict[str, Any] = dict(_MAIL_DEFAULTS)
        section["default_recipients"] = list(_MAIL_DEFAULTS["default_recipients"])
        for key, value in payload.mail.items():
            if key == "password":
                if str(value or ""):
                    section["password_enc"] = encrypt(str(value))
            elif key in section and key != "password_enc":
                section[key] = value
        cfg["mail"] = section
    return cfg


def _sync_provider_tables(db: Session, cfg: dict) -> None:
    """把 config.json 的供应商配置镜像到 DB（按 provider_id 幂等 upsert）。

    地图供应商的技术元数据（styleUrl / 瓦片模板 / 坐标系 / 署名 / 审图号 /
    needs_token）一律取自 PROVIDER_DEFS 预设，config 只提供密钥与启用状态。
    """
    for p in _cfg_providers(cfg.get("ai")):
        provider_id = str(p.get("id") or "")
        if not provider_id:
            continue
        row = (
            db.query(AiProviderConfig)
            .filter(AiProviderConfig.provider_id == provider_id)
            .first()
        )
        if row is None:
            row = AiProviderConfig(provider_id=provider_id)
            db.add(row)
        row.base_url = p.get("base_url", "")
        row.api_key_enc = p.get("api_key_enc", "")
        row.model = p.get("model", "")
        row.enabled = bool(p.get("enabled", True))
        row.priority = int(p.get("priority", 0))
        row.timeout_s = int(p.get("timeout_s", 60))
        row.supports_stream = True
    presets = {d["id"]: d for d in PROVIDER_DEFS}
    for p in _cfg_providers(cfg.get("map")):
        provider_id = str(p.get("id") or "")
        if not provider_id:
            continue
        preset = presets.get(provider_id, {})
        row = (
            db.query(MapProviderConfig)
            .filter(MapProviderConfig.provider_id == provider_id)
            .first()
        )
        if row is None:
            row = MapProviderConfig(provider_id=provider_id)
            db.add(row)
        row.key_enc = p.get("key_enc", "")
        row.style_url = preset.get("styleUrl") or ""
        row.tile_url_template = preset.get("tileUrlTemplate") or ""
        row.default_style = str(p.get("default_style") or p.get("defaultStyle") or "")
        row.coord_system = preset.get("coordSystem") or "WGS84"
        row.attribution = preset.get("attribution") or ""
        row.audit_number = preset.get("auditNumber") or ""
        row.enabled = bool(p.get("enabled", True))
        row.needs_token = bool(preset.get("needsToken", False))


def _sync_preferences(db: Session, cfg: dict, *, admin_id: str | None = None) -> None:
    """AI 工具总开关 / 默认底图同步到用户偏好。"""
    ai_tools = bool((cfg.get("security") or {}).get("ai_tools_enabled"))
    default_map = (cfg.get("map") or {}).get("default_provider_id", "amap")
    if default_map not in {d["id"] for d in PROVIDER_DEFS if not d.get("internal")}:
        default_map = "amap"
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
    db_url, db_dialect = _resolved_database_url(payload)
    if not db_url.strip():
        raise AppError(ErrorCode.VALIDATION, "数据库连接信息不完整")
    if db_dialect == "postgresql":
        if not payload.db_host.strip():
            raise AppError(ErrorCode.VALIDATION, "数据库地址不能为空")
        if not payload.db_username.strip():
            raise AppError(ErrorCode.VALIDATION, "数据库用户名不能为空")
    if not payload.admin.username.strip():
        raise AppError(ErrorCode.VALIDATION, "管理员账号不能为空")
    # 管理员密码：8-32 位、四类字符齐全、禁连续串（与普通用户口径不同）
    validate_password(payload.admin.password, is_admin=True)
    seen: set[str] = set()
    for p in payload.ai_providers:
        if p.id in seen:
            raise AppError(ErrorCode.VALIDATION, f"AI 供应商 id 重复：{p.id}")
        seen.add(p.id)
        if p.enabled and not p.base_url.strip():
            raise AppError(ErrorCode.VALIDATION, f"AI 供应商 {p.id} 未配置 base_url")
    seen.clear()
    map_presets = {d["id"]: d for d in PROVIDER_DEFS if not d.get("internal")}
    selected_map = map_presets.get(payload.map_default_provider_id)
    if selected_map is None:
        raise AppError(ErrorCode.VALIDATION, f"未知地图供应商：{payload.map_default_provider_id}")
    map_provider_keys: dict[str, str] = {}
    for p in payload.map_providers:
        if p.id in seen:
            raise AppError(ErrorCode.VALIDATION, f"地图供应商 id 重复：{p.id}")
        seen.add(p.id)
        preset = map_presets.get(p.id)
        if preset is None:
            raise AppError(ErrorCode.VALIDATION, f"未知地图供应商：{p.id}")
        map_provider_keys[p.id] = p.key
    # 安装使用的默认底图必须有可用瓦片密钥；连通性探测可跳过，不代表密钥可省略。
    if selected_map.get("needsTileKey") and not map_provider_keys.get(payload.map_default_provider_id, "").strip():
        raise AppError(
            ErrorCode.VALIDATION,
            f"地图供应商 {payload.map_default_provider_id} 需要配置 token/key；可以跳过连通性探测，但安装必须配置密钥",
        )
    # 探测真实连通性；PostgreSQL 目标库不存在时在此自动创建
    test_database(DbTestIn(
        url=db_url,
        dialect=db_dialect,
        database=payload.db_name if db_dialect == "postgresql" else "",
    ))


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
    # 创建管理员（_seed_database -> auth_service.create_user(role="owner")）前，
    # 显式按管理员口径再校验一次，杜绝任何绕过输入校验直接调用本函数的路径。
    validate_password(payload.admin.password, is_admin=True)

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
    """合并更新；未重新提供明文 key 的供应商保留原有密文，避免误清密钥。

    map_providers 按 id 增量合并：未提交的供应商原样保留，仅更新提交项的
    key（非空时重新加密）与 enabled；技术元数据不写入 config，由预设带出。
    """
    # 配置节可能被写成 null / 非字典，统一兜底，避免后续下标赋值抛异常
    defaults = {
        "redis": {},
        "ai": {"providers": []},
        "map": {"providers": [], "default_provider_id": "amap", "audit_number": ""},
        "security": {"ai_tools_enabled": False},
    }
    for section, default in defaults.items():
        if not isinstance(cfg.get(section), dict):
            cfg[section] = dict(default)

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
        old = {str(p.get("id")): p for p in _cfg_providers(cfg["ai"]) if p.get("id")}
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
        # 以已有配置为底：未提交的条目原样保留，不会被整体替换掉
        merged = {str(p.get("id")): dict(p) for p in _cfg_providers(cfg["map"]) if p.get("id")}
        for p in payload.map_providers:
            entry = dict(merged.get(p.id, {"id": p.id}))
            entry["id"] = p.id
            if p.key:
                entry["key_enc"] = encrypt(p.key)  # 非空才重新加密
            else:
                entry.setdefault("key_enc", "")  # 留空保留旧密文
            entry["enabled"] = p.enabled
            # 剥离历史手填的技术元数据，全部改由 PROVIDER_DEFS 预设带出
            for field in (
                "style_url", "tile_url_template", "coord_system",
                "attribution", "audit_number", "needs_token",
            ):
                entry.pop(field, None)
            merged[p.id] = entry
        cfg["map"]["providers"] = list(merged.values())
    return cfg


def update_config(db: Session, payload: ConfigUpdateIn) -> dict:
    """PUT 配置：config.json 与 DB 同步；是否需要解锁由各 API 端点自行决定。"""
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
    # 归一化供应商结构：dict / None 统一为 list，保证明文列表与写回索引严格对应
    for section in ("ai", "map"):
        if isinstance(original.get(section), dict):
            original[section]["providers"] = _cfg_providers(original[section])

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
    ai_entries = _cfg_providers(original.get("ai"))
    map_entries = _cfg_providers(original.get("map"))
    cfg_ai_plain = [decrypt(p.get("api_key_enc", "")) for p in ai_entries]
    cfg_map_plain = [decrypt(p.get("key_enc", "")) for p in map_entries]
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
        # ④ 用新密钥重加密 config.json 中的供应商密文并写回（顺序与明文列表一致）
        new_ai_entries = _cfg_providers(new_cfg.get("ai"))
        for i, provider in enumerate(new_ai_entries):
            provider["api_key_enc"] = encrypt(cfg_ai_plain[i]) if cfg_ai_plain[i] else ""
        if isinstance(new_cfg.get("ai"), dict):
            new_cfg["ai"]["providers"] = new_ai_entries
        new_map_entries = _cfg_providers(new_cfg.get("map"))
        for i, provider in enumerate(new_map_entries):
            provider["key_enc"] = encrypt(cfg_map_plain[i]) if cfg_map_plain[i] else ""
        if isinstance(new_cfg.get("map"), dict):
            new_cfg["map"]["providers"] = new_map_entries
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
