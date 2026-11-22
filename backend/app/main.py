"""FastAPI 应用入口。

注册顺序即正确性：
  1) 中间件（request_id / 安装守卫 / 日志）
  2) 异常处理器
  3) 全部 /api/v1 路由
  4) /assets 静态目录
  5) 最后 catch-all 返回 index.html（内部对 api/ 做 404 双保险）
严禁 app.mount("/", StaticFiles(html=True)) —— 会静默吞掉全部 /api/*。
"""
from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.v1.router import api_router
from app.core.config import get_settings, static_dir
from app.core.config_store import get_config_store
from app.core.errors import ErrorCode
from app.core.logging import configure_logging, get_logger
from app.core.response import envelope, register_exception_handlers

log = get_logger(__name__)

_PUBLIC_API_PREFIXES = (
    "/api/v1/wizard",
    "/api/v1/health",
    "/api/v1/invites/",
    "/api/v1/share/",                     # 公开分享视图（未安装守卫也要放行）
    "/api/v1/uploads/",                   # 公开分享页图片；端点内已按「公开瞬间引用」二次校验
    "/api/v1/auth/password-strength",     # 密码强度实时评估（公开）
)


def _is_public(path: str) -> bool:
    return any(path.startswith(p) for p in _PUBLIC_API_PREFIXES)


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.LOG_LEVEL)
    app = FastAPI(title="FlashTrip API", version=settings.VERSION, docs_url="/api/docs", openapi_url="/api/openapi.json")

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        request.state.request_id = rid
        path = request.url.path
        if path.startswith("/api/v1/") and not _is_public(path) and not get_config_store().is_installed():
            return JSONResponse(
                envelope(ErrorCode.INSTALL_REQUIRED, None, "系统尚未安装，请先访问 /install", rid),
                status_code=503,
            )
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        log.info(
            "http.request",
            request_id=rid,
            method=request.method,
            path=path,
            status=response.status_code,
        )
        return response

    register_exception_handlers(app)

    @app.on_event("startup")
    def _start_backup_scheduler() -> None:
        """启动备份/天气提醒守护线程；任何异常都不得阻断应用启动。"""
        try:
            from app.services import backup_service

            backup_service.start_scheduler()
        except Exception as exc:  # noqa: BLE001
            log.warning("backup.scheduler_startup_failed", error=type(exc).__name__)

    @app.on_event("shutdown")
    def _stop_backup_scheduler() -> None:
        try:
            from app.services import backup_service

            backup_service.stop_scheduler()
        except Exception as exc:  # noqa: BLE001
            log.warning("backup.scheduler_shutdown_failed", error=type(exc).__name__)

    app.include_router(api_router)

    static = static_dir()
    assets = static / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets)), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str, request: Request):  # noqa: ANN001
        if full_path == "api" or full_path.startswith("api/"):
            return JSONResponse(
                envelope(ErrorCode.NOT_FOUND, None, "API 不存在", getattr(request.state, "request_id", "")),
                status_code=404,
            )
        index = static / "index.html"
        if not index.is_file():
            return JSONResponse(
                envelope(
                    ErrorCode.INTERNAL,
                    None,
                    "前端构建产物缺失：请执行 pnpm build 并确认 dist 已注入 /app/app/static",
                    getattr(request.state, "request_id", ""),
                ),
                status_code=503,
            )
        target = static / full_path
        if full_path and target.is_file() and static.resolve() in target.resolve().parents:
            return FileResponse(target)
        return FileResponse(index)

    return app


app = create_app()
