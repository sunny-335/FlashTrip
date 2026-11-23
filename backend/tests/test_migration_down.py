"""迁移可逆性测试：在临时 SQLite 上 upgrade 到 head 再 downgrade 回 0005，验证新表/新列正确增删。"""
from __future__ import annotations

from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config as AlembicConfig

_BACKEND = Path(__file__).resolve().parents[1]
_NEW_TABLES = {
    "budget_categories",
    "households",
    "household_members",
    "frequent_travelers",
    "trip_participants",
}


def _columns(engine, table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(engine).get_columns(table)}


def test_upgrade_creates_tables_and_downgrade_removes_them(tmp_path, monkeypatch):
    db_path = tmp_path / "migration.db"
    url = f"sqlite:///{db_path.as_posix()}"
    # 让 alembic env.py 在导入时拿到临时库连接串
    monkeypatch.setattr("app.core.config.resolve_database_url", lambda: url)

    cfg = AlembicConfig(str(_BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(_BACKEND / "alembic"))

    command.upgrade(cfg, "head")
    engine = sa.create_engine(url)
    try:
        tables = set(sa.inspect(engine).get_table_names())
        assert _NEW_TABLES <= tables
        assert "total_budget" in _columns(engine, "trips")
        assert "backend" in _columns(engine, "attachments")
    finally:
        engine.dispose()

    command.downgrade(cfg, "0005_extended")
    engine = sa.create_engine(url)
    try:
        tables = set(sa.inspect(engine).get_table_names())
        assert not (_NEW_TABLES & tables)
        assert "total_budget" not in _columns(engine, "trips")
        assert "backend" not in _columns(engine, "attachments")
    finally:
        engine.dispose()
