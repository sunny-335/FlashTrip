"""ConfigStore：原子写、DB 镜像恢复回写、config.json 损坏回退。"""
from __future__ import annotations

import json

import pytest

from app.core.config import get_settings
from app.core.config_store import ConfigStore


@pytest.fixture()
def isolated(tmp_path, monkeypatch):
    """隔离 DATA_DIR / DATABASE_URL，避免污染 conftest 的会话级数据目录。"""
    db_url = f"sqlite:///{(tmp_path / 'cfg.db').as_posix()}"
    monkeypatch.setenv("FLASHTRIP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("FLASHTRIP_DATABASE_URL", db_url)
    get_settings.cache_clear()
    try:
        yield tmp_path, db_url
    finally:
        get_settings.cache_clear()


def _sample(db_url: str) -> dict:
    return {
        "installed": True,
        "installed_at": "2026-01-01T00:00:00+00:00",
        "version": "0.1.0",
        "secret_key": "unit-test-secret",
        "database": {"url": db_url, "dialect": "sqlite"},
        "redis": {"url": "", "enabled": False},
        "ai": {"providers": []},
        "map": {"providers": [], "default_provider_id": "openfreemap", "audit_number": ""},
        "security": {"ai_tools_enabled": False},
    }


def test_atomic_write(isolated):
    tmp_path, db_url = isolated
    path = tmp_path / "config.json"
    store = ConfigStore(path=path)
    cfg = _sample(db_url)

    store.save(cfg)

    # 落盘内容是完整合法 JSON（tmp 无残留，已被 os.replace 原子替换）
    assert path.exists()
    assert json.loads(path.read_text(encoding="utf-8")) == cfg
    assert not (tmp_path / "config.json.tmp").exists()
    assert not list(tmp_path.glob("*.tmp"))


def test_restore_from_db_mirror_rewrites_config(isolated):
    tmp_path, db_url = isolated
    path = tmp_path / "config.json"
    store = ConfigStore(path=path)
    cfg = _sample(db_url)
    store.save(cfg)  # config.json + DB app_config 镜像

    # 模拟 config.json 丢失（容器卷只丢了文件，DB 仍在）
    path.unlink()
    assert not path.exists()

    loaded = store.load()

    assert loaded["installed"] is True
    assert loaded["secret_key"] == cfg["secret_key"]
    assert loaded["database"]["url"] == db_url
    # 恢复后必须原子回写 config.json
    assert path.exists()
    assert json.loads(path.read_text(encoding="utf-8"))["installed"] is True


def test_corrupted_config_restores_from_db(isolated):
    tmp_path, db_url = isolated
    path = tmp_path / "config.json"
    store = ConfigStore(path=path)
    cfg = _sample(db_url)
    store.save(cfg)

    # 模拟 config.json 写坏
    path.write_text("{ this is not json", encoding="utf-8")

    loaded = store.load()

    assert loaded["installed"] is True
    assert loaded["secret_key"] == cfg["secret_key"]
    # 损坏文件被有效配置覆盖
    assert json.loads(path.read_text(encoding="utf-8")) == loaded


def test_corrupted_config_without_mirror_falls_back_to_uninstalled(isolated):
    tmp_path, _ = isolated
    path = tmp_path / "config.json"
    store = ConfigStore(path=path)
    # 无 DB 镜像（cfg.db 尚不存在），损坏后只能回退到安全态，绝不回退出厂默认
    path.write_text("not-json-at-all", encoding="utf-8")

    loaded = store.load()

    assert loaded["installed"] is False
    assert loaded.get("corrupted") is True
    assert "secret_key" not in loaded
