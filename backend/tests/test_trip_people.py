"""行程人数 / 儿童数 / 家庭模式 API 契约测试。

用 conftest 的 client + 独立内存 SQLite，覆盖依赖以避开权限表与真实网络。
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1 import deps
from app.core.errors import ErrorCode
from app.db.base import Base
from app.models.plan import PlanItem
from app.models.trip import Trip, TripDay
from app.models.user import User

_TABLES = [Trip.__table__, TripDay.__table__, PlanItem.__table__, User.__table__]


@pytest.fixture()
def env(client, monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine, tables=_TABLES)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    db = Session()

    owner = User(
        id="owner-1", username="owner", password_hash="x",
        role="owner", is_active=True, must_set_password=False,
    )
    db.add(owner)
    db.commit()

    # 让所有端点都以 owner 身份通过（owner 短路 require_permission）
    fake_user = SimpleNamespace(id=owner.id, role="owner", must_set_password=False)
    monkeypatch.setitem(client.app.dependency_overrides, deps.require_user, lambda: fake_user)
    monkeypatch.setitem(client.app.dependency_overrides, deps.get_db, lambda: db)
    # 行程 CRUD 不触发 sync emit，所有读写都落在同一内存会话，无外部副作用
    yield SimpleNamespace(client=client, db=db, owner=owner)
    db.close()
    engine.dispose()


def _create(client, **overrides):
    payload = {"title": "测试行程", **overrides}
    return client.post("/api/v1/trips", json=payload)


def test_traveler_count_must_be_at_least_one(env):
    resp = _create(env.client, traveler_count=0)
    assert resp.status_code == 422
    body = resp.json()
    assert body["code"] == ErrorCode.VALIDATION
    assert "1" in body["message"]


def test_children_count_requires_at_least_one_when_has_children(env):
    resp = _create(env.client, traveler_count=4, has_children=True, children_count=0)
    assert resp.status_code == 422
    assert resp.json()["code"] == ErrorCode.VALIDATION
    assert "儿童" in resp.json()["message"]


def test_children_count_must_be_less_than_traveler_count(env):
    resp = _create(env.client, traveler_count=3, has_children=True, children_count=3)
    assert resp.status_code == 422
    body = resp.json()
    assert body["code"] == ErrorCode.VALIDATION
    assert "小于" in body["message"]


def test_has_children_false_forces_children_count_zero(env):
    resp = _create(env.client, traveler_count=5, has_children=False, children_count=3)
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["traveler_count"] == 5
    assert data["has_children"] is False
    assert data["children_count"] == 0
    assert data["family_mode"] is False
    assert data["family_name"] is None


def test_put_updates_people_fields_roundtrip(env):
    created = _create(env.client, traveler_count=2).json()["data"]
    trip_id = created["id"]
    assert created["traveler_count"] == 2

    resp = env.client.put(
        f"/api/v1/trips/{trip_id}",
        json={
            "traveler_count": 4,
            "has_children": True,
            "children_count": 2,
            "family_mode": True,
            "family_name": "张家",
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert (data["traveler_count"], data["has_children"], data["children_count"]) == (4, True, 2)
    assert data["family_mode"] is True
    assert data["family_name"] == "张家"

    got = env.client.get(f"/api/v1/trips/{trip_id}")
    assert got.json()["data"]["children_count"] == 2
    overview = env.client.get(f"/api/v1/trips/{trip_id}/overview")
    assert overview.json()["data"]["trip"]["traveler_count"] == 4

    # 关闭 has_children 后强制归零（即便未提交 children_count）
    back = env.client.put(f"/api/v1/trips/{trip_id}", json={"has_children": False})
    assert back.status_code == 200
    assert back.json()["data"]["children_count"] == 0


def test_put_partial_update_keeps_people_constraints(env):
    created = _create(env.client, traveler_count=4, has_children=True, children_count=2).json()["data"]
    trip_id = created["id"]
    # 仅改标题，人数约束仍以合并后的值校验，应通过
    assert env.client.put(f"/api/v1/trips/{trip_id}", json={"title": "改名"}).status_code == 200
    # 把总人数降到 2 会使 2 名儿童不再「小于总人数」，必须拒绝
    bad = env.client.put(f"/api/v1/trips/{trip_id}", json={"traveler_count": 2})
    assert bad.status_code == 422
    assert bad.json()["code"] == ErrorCode.VALIDATION
