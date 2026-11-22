"""健康检查：未安装也可用（公开），暴露 dist 是否注入以便提前发现构建问题。"""
from __future__ import annotations

import time

from fastapi import APIRouter, Request
from sqlalchemy import text

from app import __version__
from app.core.config import resolve_database_url, static_dir
from app.core.config_store import get_config_store
from app.core.response import ok
from app.db.session import get_engine

router = APIRouter(tags=["health"])


def _probe_db() -> dict:
    url = resolve_database_url()
    if not url:
        return {"ok": False, "dialect": "", "latency_ms": 0, "error": "database url missing"}
    started = time.perf_counter()
    try:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            try:
                migration_rev = str(
                    conn.execute(text("SELECT version_num FROM alembic_version")).scalar() or ""
                )
            except Exception:  # noqa: BLE001  未迁移的库没有该表
                migration_rev = ""
        return {
            "ok": True,
            "dialect": engine.dialect.name,
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "migration_rev": migration_rev,
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "dialect": url.split(":")[0], "latency_ms": 0, "error": str(exc), "migration_rev": ""}


@router.get("/health")
def health(request: Request):
    cfg = get_config_store().load()
    static = static_dir()
    db = _probe_db()
    return ok(
        {
            "status": "ok" if db["ok"] and (static / "index.html").is_file() else "degraded",
            "version": __version__,
            "installed": get_config_store().is_installed(),
            "db": db,
            "redis": {"enabled": bool((cfg.get("redis") or {}).get("url"))},
            "ai": {"enabled": bool((cfg.get("ai") or {}).get("providers"))},
            "static_dir_exists": (static / "index.html").is_file(),
            "static_dir": str(static),
            "migrations_rev": db.get("migration_rev", ""),
        },
        request_id=getattr(request.state, "request_id", ""),
    )


@router.get("/health/ready")
def ready(request: Request):
    from app.core.errors import AppError, ErrorCode

    db = _probe_db()
    if not db["ok"] or not (static_dir() / "index.html").is_file():
        raise AppError(ErrorCode.INTERNAL, "服务未就绪：数据库或前端产物不可用")
    return ok({"ready": True}, request_id=getattr(request.state, "request_id", ""))
