"""模型包：动态导入 models/ 下所有模块以填充 Base.metadata（Alembic 依赖）。"""
from __future__ import annotations

from importlib import import_module
from pathlib import Path

_PKG = __package__ or "app.models"

for _path in sorted(Path(__file__).parent.glob("*.py")):
    if _path.stem.startswith("_") or _path.stem == "base":
        continue
    import_module(f"{_PKG}.{_path.stem}")
