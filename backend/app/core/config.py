"""全局配置：环境变量只承载引导级参数，业务配置一律来自 /data/config.json。"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_SQLITE_URL = "sqlite:////data/flashtrip.db"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="FLASHTRIP_",
        env_file=None,
        extra="ignore",
        case_sensitive=False,
    )

    DATA_DIR: Path = Path("/data")
    STATIC_DIR: Path = Path("/app/app/static")
    SECRET_KEY: str = ""
    DATABASE_URL: str = ""
    REDIS_URL: str = ""
    LOG_LEVEL: str = "INFO"
    TZ: str = "Asia/Shanghai"
    VERSION: str = "0.1.0"


@lru_cache
def get_settings() -> Settings:
    return Settings()


def data_dir() -> Path:
    """返回数据目录并确保存在。本机开发（无 /data 权限）时回退到项目内 ./data。"""
    settings = get_settings()
    candidate = Path(settings.DATA_DIR)
    try:
        candidate.mkdir(parents=True, exist_ok=True)
        return candidate
    except OSError:
        fallback = Path(__file__).resolve().parents[2] / "data"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


def config_path() -> Path:
    return data_dir() / "config.json"


def installed_marker_path() -> Path:
    return data_dir() / ".installed"


def static_dir() -> Path:
    settings = get_settings()
    env = os.getenv("FLASHTRIP_STATIC_DIR")
    candidate = Path(env) if env else Path(settings.STATIC_DIR)
    if (candidate / "index.html").is_file():
        return candidate
    # 本机开发回退：frontend/dist（容器里始终使用注入的 /app/app/static）
    local = Path(__file__).resolve().parents[3] / "frontend" / "dist"
    if (local / "index.html").is_file():
        return local
    return candidate


def load_config() -> dict:
    """只读地读取 config.json；不存在返回 {'installed': False}（绝不回退出厂默认）。"""
    path = config_path()
    if not path.exists():
        return {"installed": False}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"installed": False, "corrupted": True}


def resolve_database_url() -> str:
    """优先级：FLASHTRIP_DATABASE_URL > config.json.database.url > 默认 SQLite。

    连接串必须先于数据库存在，因此 config.json 是权威源（不能只存 DB）。
    """
    settings = get_settings()
    if settings.DATABASE_URL:
        return settings.DATABASE_URL
    cfg = load_config()
    url = (cfg.get("database") or {}).get("url")
    if url:
        return str(url)
    if cfg.get("installed"):
        # 已安装但连接串缺失：不静默回退，交给上层报错
        return ""
    db_path = data_dir() / "flashtrip.db"
    return f"sqlite:///{db_path.as_posix()}" if not str(db_path).startswith("/") else DEFAULT_SQLITE_URL


def resolve_redis_url() -> str:
    settings = get_settings()
    if settings.REDIS_URL:
        return settings.REDIS_URL
    return str((load_config().get("redis") or {}).get("url") or "")
