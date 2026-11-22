"""pytest 全局夹具：隔离数据目录与静态目录，避免污染真实 /data。"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND = REPO_ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

_TMP = REPO_ROOT / ".pytest-tmp"
_TMP.mkdir(exist_ok=True)
_DATA = _TMP / "data"
_DATA.mkdir(exist_ok=True)
_STATIC = _TMP / "static"
(_STATIC / "assets").mkdir(parents=True, exist_ok=True)
(_STATIC / "index.html").write_text("<!doctype html><title>FlashTrip</title><div id='app'></div>", encoding="utf-8")
(_STATIC / "assets" / "app.js").write_text("// test asset", encoding="utf-8")

os.environ["FLASHTRIP_DATA_DIR"] = str(_DATA)
os.environ["FLASHTRIP_STATIC_DIR"] = str(_STATIC)
os.environ["FLASHTRIP_DATABASE_URL"] = f"sqlite:///{( _DATA / 'test.db').as_posix()}"
os.environ["FLASHTRIP_SECRET_KEY"] = "test-secret-key-do-not-use-in-production"


@pytest.fixture(scope="session", autouse=True)
def _installed_marker():
    """默认以「已安装」状态跑 API 测试，绕过安装守卫；单独用例可覆盖。"""
    cfg = {
        "installed": True,
        "secret_key": os.environ["FLASHTRIP_SECRET_KEY"],
        "database": {"url": os.environ["FLASHTRIP_DATABASE_URL"], "dialect": "sqlite"},
        "redis": {},
        "ai": {},
        "map": {},
    }
    (_DATA / "config.json").write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    yield


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app()) as c:
        yield c


@pytest.fixture()
def static_dir() -> Path:
    return _STATIC


@pytest.fixture()
def data_dir() -> Path:
    return _DATA
