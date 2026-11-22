"""config.json（权威）+ DB app_config（镜像）双写兜底。

写入：tmp + fsync + os.replace 原子替换，再尽力镜像到 DB（失败仅告警）。
读取：config.json 存在则以它为准；缺失时若 DB 有镜像则恢复并原子回写；
      两者皆无返回 installed=False，进入安装向导，**绝不静默回退出厂默认**。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from app.core.config import config_path, data_dir, installed_marker_path, load_config, resolve_database_url
from app.core.logging import get_logger

log = get_logger(__name__)
_FULL_KEY = "__full_config__"


def _db_engine() -> Engine | None:
    url = resolve_database_url()
    if not url:
        return None
    try:
        return create_engine(url, connect_args={"timeout": 3} if url.startswith("sqlite") else {}, pool_pre_ping=True)
    except Exception as exc:  # noqa: BLE001
        log.warning("config_store.db_engine_failed", error=str(exc))
        return None


def _mirror_to_db(cfg: dict[str, Any]) -> None:
    engine = _db_engine()
    if engine is None:
        log.warning("config_store.mirror_skipped", reason="no_database_url")
        return
    try:
        with engine.begin() as conn:
            conn.execute(text(
                "CREATE TABLE IF NOT EXISTS app_config "
                "(key VARCHAR(64) PRIMARY KEY, value_plain TEXT NULL, value_enc TEXT NULL, "
                " updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
            ))
            payload = json.dumps(cfg, ensure_ascii=False)
            if engine.dialect.name == "sqlite":
                conn.execute(text(
                    "INSERT INTO app_config(key, value_plain) VALUES(:k, :v) "
                    "ON CONFLICT(key) DO UPDATE SET value_plain=excluded.value_plain, "
                    "updated_at=CURRENT_TIMESTAMP"
                ), {"k": _FULL_KEY, "v": payload})
            else:
                conn.execute(text(
                    "INSERT INTO app_config(key, value_plain) VALUES(:k, :v) "
                    "ON CONFLICT(key) DO UPDATE SET value_plain=EXCLUDED.value_plain, "
                    "updated_at=CURRENT_TIMESTAMP"
                ), {"k": _FULL_KEY, "v": payload})
    except Exception as exc:  # noqa: BLE001  DB 不可用不能影响 installed 判定
        log.warning("config_store.mirror_failed", error=str(exc))
    finally:
        engine.dispose()


def _restore_from_db() -> dict[str, Any] | None:
    engine = _db_engine()
    if engine is None:
        return None
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT value_plain FROM app_config WHERE key=:k"), {"k": _FULL_KEY}
            ).first()
        if row and row[0]:
            return json.loads(row[0])
    except Exception as exc:  # noqa: BLE001  表不存在/库不可用均视为无镜像
        log.warning("config_store.restore_failed", error=str(exc))
    finally:
        engine.dispose()
    return None


class ConfigStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or config_path()

    def load(self) -> dict[str, Any]:
        if self.path.exists():
            try:
                return json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                log.error("config_store.corrupted", error=str(exc))
                restored = _restore_from_db()
                if restored:
                    self.save(restored)
                    return restored
                return {"installed": False, "corrupted": True}
        restored = _restore_from_db()
        if restored:
            log.info("config_store.restored_from_db")
            self.save(restored)
            return restored
        return {"installed": False}

    def save(self, cfg: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        payload = json.dumps(cfg, ensure_ascii=False, indent=2)
        # 以可写句柄写入并 fsync：Windows 上以 "rb" 打开的只读句柄调用
        # os.fsync 会抛 OSError(Errno 9)；个别文件系统不支持 fsync 时
        # os.replace 本身仍是原子操作，故降级为 best-effort。
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(payload)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass
        os.replace(tmp, self.path)  # 原子
        _mirror_to_db(cfg)

    def is_installed(self) -> bool:
        cfg = load_config()
        if bool(cfg.get("installed")):
            return True
        return installed_marker_path().exists()

    def mark_installed(self, cfg: dict[str, Any]) -> dict[str, Any]:
        cfg = dict(cfg)
        cfg["installed"] = True
        self.save(cfg)
        installed_marker_path().write_text("installed\n", encoding="utf-8")
        return cfg

    def mark_uninstalled(self) -> None:
        marker = installed_marker_path()
        if marker.exists():
            marker.unlink()
        cfg = self.load()
        cfg["installed"] = False
        self.save(cfg)

    def is_unlocked(self) -> bool:
        return bool(self.load().get("unlocked_at"))


_store: ConfigStore | None = None


def get_config_store() -> ConfigStore:
    global _store
    if _store is None:
        _store = ConfigStore()
    return _store


def data_subdir(name: str) -> Path:
    p = data_dir() / name
    p.mkdir(parents=True, exist_ok=True)
    return p
