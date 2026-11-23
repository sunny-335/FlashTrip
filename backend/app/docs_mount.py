"""VitePress 文档站挂载：/FlashTrip → 静态目录下 docs 子目录。

文档构建产物由 Dockerfile 的 docs 阶段复制到 `static/docs`（VitePress base 为
/FlashTrip/）。本模块暴露 `mount_docs(app)`，在 FastAPI 应用创建时调用一次即可，
同时提供无斜杠访问 `/FlashTrip` → `/FlashTrip/` 的 307 重定向。

集成位置（app/main.py 的 create_app 内，建议紧跟 /assets 挂载之后、
SPA catch-all `/{full_path:path}` 注册之前）：

    from app.docs_mount import mount_docs
    ...
    mount_docs(app)

即使调用点晚于 catch-all 注册，本模块也会把挂载点移动到 catch-all 之前，
确保 /FlashTrip/* 不被 SPA 回退吞掉；文档目录缺失（未构建）时静默跳过。
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.core.config import static_dir

_MOUNT_PATH = "/FlashTrip"
_MOUNT_NAME = "flashtrip-docs"
_ENTRY_NAME = "flashtrip-docs-entry"
_CATCH_ALL_PATH = "/{full_path:path}"


def docs_dir() -> Path:
    return Path(static_dir()) / "docs"


def mount_docs(app: FastAPI) -> bool:
    """把 VitePress 构建产物挂载到 /FlashTrip；返回是否实际挂载（幂等）。"""
    directory = docs_dir()
    if not (directory / "index.html").is_file():
        return False  # 未构建文档：静默跳过，不影响应用其余部分
    routes = app.routes
    for route in routes:
        if getattr(route, "name", None) in (_MOUNT_NAME, _ENTRY_NAME):
            return True  # 已挂载
    # 无斜杠访问重定向到目录入口（Mount 仅匹配 /FlashTrip/…）
    @app.get(_MOUNT_PATH, include_in_schema=False, name=_ENTRY_NAME)
    def docs_entry() -> RedirectResponse:
        return RedirectResponse(url=f"{_MOUNT_PATH}/", status_code=307)

    app.mount(_MOUNT_PATH, StaticFiles(directory=str(directory), html=True), name=_MOUNT_NAME)
    _reorder_before_catch_all(app, (_ENTRY_NAME, _MOUNT_NAME))
    return True


def _reorder_before_catch_all(app: FastAPI, names: tuple[str, ...]) -> None:
    """把文档相关路由移动到 SPA catch-all 之前（迟到调用时的兜底）。"""
    routes = app.routes
    catch_idx = next(
        (i for i, r in enumerate(routes) if getattr(r, "path", "") == _CATCH_ALL_PATH),
        None,
    )
    if catch_idx is None:
        return
    pending = [r for r in routes if getattr(r, "name", "") in names]
    if not pending:
        return
    for route in pending:
        routes.remove(route)
    catch_idx = next(
        (i for i, r in enumerate(routes) if getattr(r, "path", "") == _CATCH_ALL_PATH),
        None,
    )
    for offset, route in enumerate(pending):
        routes.insert(catch_idx + offset, route)
