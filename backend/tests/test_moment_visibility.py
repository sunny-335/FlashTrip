"""瞬间可见性：默认私有、协作用户看不到他人私有、public=1 仅公开、
全局默认可见性生效、author_id 服务端注入。

用 conftest 的 client + 独立内存 SQLite（dependency_overrides 注入用户/会话），
monkeypatch 隔离真实网络与 SMTP。
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1 import deps
from app.core.security import new_id
from app.db.base import Base
from app.models.config import UserPreferences
from app.models.moment import Moment
from app.models.trip import Trip
from app.models.user import User

_TABLES = [Trip.__table__, Moment.__table__, User.__table__, UserPreferences.__table__]


@pytest.fixture()
def env(client, monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine, tables=_TABLES)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    db = Session()

    trip = Trip(id="trip-1", owner_id="viewer-1", title="苏州三日游")
    db.add(trip)
    db.commit()

    # owner 身份可短路 require_permission，无需构造协作表
    viewer = SimpleNamespace(id="viewer-1", role="owner", must_set_password=False)
    monkeypatch.setitem(client.app.dependency_overrides, deps.require_user, lambda: viewer)
    monkeypatch.setitem(client.app.dependency_overrides, deps.get_db, lambda: db)
    # 测试期间绝不触碰真实 SMTP / 天气网络
    from app.services import mail_service, weather_service

    monkeypatch.setattr(mail_service, "send_mail", lambda *a, **k: {"ok": True})
    monkeypatch.setattr(
        weather_service, "fetch_weather",
        lambda *a, **k: {"current": {}, "forecast": [], "advice_hints": []},
    )
    yield SimpleNamespace(client=client, db=db, trip=trip)
    db.close()
    engine.dispose()


def _seed(db, trip_id):
    rows = [
        Moment(id=new_id(), trip_id=trip_id, author_id="viewer-1",
               content="我的私有", is_public=False),
        Moment(id=new_id(), trip_id=trip_id, author_id="other-1",
               content="他人私有", is_public=False),
        Moment(id=new_id(), trip_id=trip_id, author_id="other-1",
               content="他人公开", is_public=True),
    ]
    db.add_all(rows)
    db.commit()
    return rows


def _list(env, query=""):
    resp = env.client.get(f"/api/v1/trips/{env.trip.id}/moments{query}")
    assert resp.status_code == 200, resp.text
    return {row["content"] for row in resp.json()["data"]}


def test_default_is_private(env):
    resp = env.client.post(
        f"/api/v1/trips/{env.trip.id}/moments", json={"content": "新建瞬间"}
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["is_public"] is False
    assert data["author_id"] == "viewer-1"


def test_viewer_sees_own_all_and_others_public_only(env):
    _seed(env.db, env.trip.id)
    assert _list(env) == {"我的私有", "他人公开"}


def test_public_flag_returns_only_public(env):
    _seed(env.db, env.trip.id)
    assert _list(env, "?public=1") == {"他人公开"}


def test_single_private_moment_of_others_is_forbidden(env):
    rows = _seed(env.db, env.trip.id)
    private_id = rows[1].id
    resp = env.client.get(f"/api/v1/trips/{env.trip.id}/moments/{private_id}")
    assert resp.status_code == 403


def test_global_default_public_applies(env):
    env.db.add(UserPreferences(user_id="viewer-1", moment_default_public=True))
    env.db.commit()
    resp = env.client.post(
        f"/api/v1/trips/{env.trip.id}/moments", json={"content": "默认公开"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["is_public"] is True
    # 显式提交 is_public=False 时优先于全局默认
    resp2 = env.client.post(
        f"/api/v1/trips/{env.trip.id}/moments",
        json={"content": "显式私有", "is_public": False},
    )
    assert resp2.json()["data"]["is_public"] is False


def test_author_id_cannot_be_forged(env):
    resp = env.client.post(
        f"/api/v1/trips/{env.trip.id}/moments",
        json={"content": "伪造发布者", "author_id": "other-1"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["author_id"] == "viewer-1"


def test_update_is_public_and_keep_author(env):
    rows = _seed(env.db, env.trip.id)
    target = rows[0]
    resp = env.client.put(
        f"/api/v1/trips/{env.trip.id}/moments/{target.id}",
        json={"is_public": True, "author_id": "other-1"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["is_public"] is True
    assert resp.json()["data"]["author_id"] == "viewer-1"
    assert _list(env, "?public=1") >= {"我的私有"}
