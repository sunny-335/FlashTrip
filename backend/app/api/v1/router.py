"""API 路由自动聚合：扫描 api/v1 下的模块，收集各自的 `router`。

约定：每个子模块导出 `router = APIRouter()`，路径为相对路径（如 `/wizard`），
不要自行添加 `/api/v1` 前缀。新增模块无需修改本文件。
"""
from __future__ import annotations

from importlib import import_module
from pathlib import Path

from fastapi import APIRouter

api_router = APIRouter(prefix="/api/v1")

_SKIP = {"__init__", "router", "deps"}
_PKG = __package__ or "app.api.v1"

for _path in sorted(Path(__file__).parent.glob("*.py")):
    _name = _path.stem
    if _name.startswith("_") or _name in _SKIP:
        continue
    _module = import_module(f"{_PKG}.{_name}")
    _sub = getattr(_module, "router", None)
    if _sub is not None:
        api_router.include_router(_sub)
