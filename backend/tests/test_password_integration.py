"""密码策略集成：管理员四类强制、普通用户两类通过、连续串被拒、
/auth/password-strength 返回分级指标。

服务层用临时 SQLite，HTTP 端点用 conftest 的 client；monkeypatch 隔离网络与 SMTP。
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.errors import AppError, ErrorCode
from app.db.base import Base
from app.models.user import User
from app.services import auth_service, password_policy

_TABLES = [User.__table__]


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'password.db').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine, tables=_TABLES)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture(autouse=True)
def _no_external_io(monkeypatch):
    """测试期间绝不触碰真实 SMTP / 天气网络。"""
    from app.services import mail_service, weather_service

    monkeypatch.setattr(mail_service, "send_mail", lambda *a, **k: {"ok": True})
    monkeypatch.setattr(
        weather_service, "fetch_weather",
        lambda *a, **k: {"current": {}, "forecast": [], "advice_hints": []},
    )


def test_admin_weak_password_rejected(db):
    """仅大小写两类：普通用户可用，但管理员必须四类齐全。"""
    with pytest.raises(AppError) as err:
        auth_service.create_user(db, username="boss", password="AdminPass", role="owner")
    assert err.value.code == ErrorCode.VALIDATION
    assert "管理员" in err.value.message


def test_admin_strong_password_ok(db):
    user = auth_service.create_user(db, username="boss-ok", password="Abc!9xQz", role="owner")
    db.commit()
    assert user.id
    assert user.role == "owner"


def test_normal_user_two_classes_pass(db):
    user = auth_service.create_user(db, username="member-ok", password="akmzqtv7")
    db.commit()
    assert user.must_set_password is False
    assert user.password_hash.startswith("$argon2")


def test_sequence_password_rejected(db):
    with pytest.raises(AppError) as err:
        auth_service.create_user(db, username="seq", password="abcd1234")
    assert err.value.code == ErrorCode.VALIDATION
    assert "连续" in err.value.message


def test_too_short_password_rejected(db):
    with pytest.raises(AppError) as err:
        auth_service.create_user(db, username="short", password="Ab1!")
    assert err.value.code == ErrorCode.VALIDATION
    assert "长度" in err.value.message


def test_install_admin_policy_is_strict():
    with pytest.raises(AppError) as err:
        password_policy.validate_password("password123", is_admin=True)
    assert err.value.code == ErrorCode.VALIDATION
    # 同一口令作为普通用户（两类）是允许的
    password_policy.validate_password("password123")


def test_password_strength_endpoint_returns_graded_result(client):
    weak = client.post("/api/v1/auth/password-strength",
                        json={"password": "abc"}).json()["data"]
    strong = client.post("/api/v1/auth/password-strength",
                         json={"password": "Abc!9xQz"}).json()["data"]
    assert weak["score"] < strong["score"]
    assert weak["label"] in ("弱", "一般", "较强", "强")
    assert weak["valid"] is False
    assert strong["valid"] is True
    assert isinstance(weak["hints"], list) and weak["hints"]
    assert all(key in weak for key in ("adminOk", "lengthOk", "classCount", "hasSequence", "meetsPolicy"))

    admin = client.post("/api/v1/auth/password-strength",
                        json={"password": "Abc!9xQz", "is_admin": True}).json()["data"]
    assert admin["isAdmin"] is True
    assert admin["adminOk"] is True
    assert admin["meetsPolicy"] is True


def test_password_strength_admin_flag_lowers_acceptance(client):
    """同一口令普通用户达标、管理员未达标（四类门槛）。"""
    normal = client.post("/api/v1/auth/password-strength",
                        json={"password": "akmzqtv7"}).json()["data"]
    admin = client.post("/api/v1/auth/password-strength",
                        json={"password": "akmzqtv7", "is_admin": True}).json()["data"]
    assert normal["meetsPolicy"] is True
    assert admin["meetsPolicy"] is False
