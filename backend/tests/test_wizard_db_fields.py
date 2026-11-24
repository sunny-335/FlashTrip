"""安装向导的数据库与 Redis 结构化配置：连接串拼装、自动建库、SQLite 免连接串。"""
from __future__ import annotations

import pytest

from app.core.errors import AppError, ErrorCode
from app.services import install_service as svc


def test_sqlite_url_is_fixed_and_ignores_fields():
    """SQLite 不需要用户填任何连接信息，连接串由服务端固定。"""
    url = svc.build_database_url("sqlite", host="ignored", port=1234,
                                 username="u", password="p", database="x")
    assert url == svc.DEFAULT_SQLITE_URL
    assert url.endswith("flashtrip.db")


def test_postgresql_url_is_built_from_structured_fields():
    url = svc.build_database_url("postgresql", host="db.example.com", port=5432,
                                 username="traveler", password="p@ss word", database="flashtrip")
    assert url.startswith("postgresql://traveler:")
    # 特殊字符必须被转义，否则连接串无法解析
    assert "p%40ss%20word" in url
    assert url.endswith("@db.example.com:5432/flashtrip")


def test_postgresql_url_allows_passwordless_user():
    url = svc.build_database_url("postgresql", host="127.0.0.1", port=5432,
                                 username="traveler", password="", database="flashtrip")
    assert url == "postgresql://traveler@127.0.0.1:5432/flashtrip"


def test_postgresql_requires_host():
    with pytest.raises(AppError) as exc:
        svc.build_database_url("postgresql", host="", username="u", password="p")
    assert exc.value.code == ErrorCode.VALIDATION


def test_redis_url_is_built_from_structured_fields():
    url = svc.build_redis_url(host="10.0.0.5", port=6380, password="s3cret", database=2)
    assert url == "redis://:s3cret@10.0.0.5:6380/2"


def test_redis_url_without_password_omits_auth():
    url = svc.build_redis_url(host="127.0.0.1", port=6379, password="", database=0)
    assert url == "redis://127.0.0.1:6379/0"


def test_redis_url_empty_host_returns_empty():
    assert svc.build_redis_url(host="", port=6379) == ""


def test_install_payload_resolves_structured_database_url():
    payload = svc.InstallIn(
        admin=svc.AdminIn(username="owner", password="Kq9#mZ2!vTn"),
        database_dialect="postgresql",
        db_host="db.example.com",
        db_port=5432,
        db_username="traveler",
        db_password="secret",
        db_name="flashtrip",
    )
    url, dialect = svc._resolved_database_url(payload)
    assert dialect == "postgresql"
    assert "db.example.com:5432/flashtrip" in url
    assert "traveler" in url


def test_install_payload_falls_back_to_sqlite_without_fields():
    payload = svc.InstallIn(
        admin=svc.AdminIn(username="owner", password="Kq9#mZ2!vTn"),
        database_dialect="sqlite",
    )
    url, dialect = svc._resolved_database_url(payload)
    assert dialect == "sqlite"
    assert url == svc.DEFAULT_SQLITE_URL


def test_install_payload_resolves_structured_redis_url():
    payload = svc.InstallIn(
        admin=svc.AdminIn(username="owner", password="Kq9#mZ2!vTn"),
        redis_host="10.0.0.5",
        redis_port=6380,
        redis_password="pw",
        redis_db=3,
        redis_enabled=True,
    )
    assert svc._resolved_redis_url(payload) == "redis://:pw@10.0.0.5:6380/3"
    cfg = svc._base_config(payload, "secret")
    assert cfg["redis"]["enabled"] is True


def test_install_validation_requires_postgres_host_and_user():
    payload = svc.InstallIn(
        admin=svc.AdminIn(username="owner", password="Kq9#mZ2!vTn"),
        database_dialect="postgresql",
        db_host="",
        db_username="",
    )
    with pytest.raises(AppError) as exc:
        svc._validate_install(payload)
    assert exc.value.code == ErrorCode.VALIDATION


def test_install_validation_rejects_missing_required_map_key(monkeypatch):
    payload = svc.InstallIn(
        admin=svc.AdminIn(username="owner", password="Kq9#mZ2!vTn"),
        map_default_provider_id="tianditu",
        map_providers=[svc.MapProviderIn(id="tianditu", key="", enabled=True)],
    )
    with pytest.raises(AppError, match="需要配置 token/key"):
        svc._validate_install(payload)


def test_install_validation_allows_skipped_map_connectivity_without_required_key(monkeypatch):
    payload = svc.InstallIn(
        admin=svc.AdminIn(username="owner", password="Kq9#mZ2!vTn"),
        map_providers=[svc.MapProviderIn(id="tianditu", key="  ", enabled=True)],
    )
    with pytest.raises(AppError, match="连通性探测可以跳过"):
        svc._validate_install(payload)


def test_db_test_uses_structured_fields(monkeypatch):
    """test-db 收到结构化字段时应拼装连接串再探测，而不是直接用空 url。"""
    seen: dict[str, str] = {}

    class _FakeConn:
        dialect = type("D", (), {"name": "postgresql"})()

        def execute(self, *args, **kwargs):
            return type("R", (), {"scalar": lambda self: "PostgreSQL 16"})()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    class _FakeEngine:
        def connect(self):
            return _FakeConn()

        def dispose(self):
            pass

    def fake_create_engine(url, **kwargs):
        seen["url"] = url
        return _FakeEngine()

    monkeypatch.setattr(svc, "create_engine", fake_create_engine)
    result = svc.test_database(svc.DbTestIn(
        dialect="postgresql", host="db.example.com", port=5432,
        username="traveler", password="pw", database="flashtrip",
    ))
    assert result["ok"] is True
    assert "db.example.com:5432/flashtrip" in seen["url"]


def test_ensure_pg_database_uses_autocommit(monkeypatch):
    seen: dict = {"statements": []}

    class _FakeConn:
        def execute(self, statement, params=None):
            seen["statements"].append(str(statement))
            if "pg_database" in str(statement):
                return type("R", (), {"scalar": lambda self: None})()
            return type("R", (), {"scalar": lambda self: 1})()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    class _FakeEngine:
        def connect(self):
            return _FakeConn()

        def dispose(self):
            pass

    def fake_create_engine(url, **kwargs):
        seen["url"] = url
        seen["kwargs"] = kwargs
        return _FakeEngine()

    monkeypatch.setattr(svc, "create_engine", fake_create_engine)

    svc._ensure_pg_database("postgresql://traveler:pw@db.example.com:5432/flashtrip", "flashtrip")

    assert seen["kwargs"]["isolation_level"] == "AUTOCOMMIT"
    assert any('CREATE DATABASE "flashtrip"' in statement for statement in seen["statements"])
