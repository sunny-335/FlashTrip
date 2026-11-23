"""家庭 / 常用人员 CRUD 与行程快速选人 API 契约测试。"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1 import deps
from app.core.errors import ErrorCode
from app.db.base import Base
from app.models.people import (
    FrequentTraveler,
    Household,
    HouseholdMember,
    TripParticipant,
)
from app.models.trip import Trip
from app.models.user import User

_TABLES = [
    Trip.__table__, User.__table__,
    Household.__table__, HouseholdMember.__table__,
    FrequentTraveler.__table__, TripParticipant.__table__,
]


@pytest.fixture()
def env(client, monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine, tables=_TABLES)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    db = Session()

    owner = User(
        id="owner-1", username="owner", password_hash="x",
        role="owner", is_active=True, must_set_password=False,
    )
    trip = Trip(id="trip-1", owner_id=owner.id, title="出行", traveler_count=1)
    trip2 = Trip(id="trip-2", owner_id=owner.id, title="只有儿童", traveler_count=1)
    db.add_all([owner, trip, trip2])
    db.commit()

    fake_user = SimpleNamespace(id=owner.id, role="owner", must_set_password=False)
    monkeypatch.setitem(client.app.dependency_overrides, deps.require_user, lambda: fake_user)
    monkeypatch.setitem(client.app.dependency_overrides, deps.get_db, lambda: db)
    yield SimpleNamespace(client=client, db=db, owner=owner)
    db.close()
    engine.dispose()


def test_household_crud_with_members(env):
    created = env.client.post(
        "/api/v1/households",
        json={
            "name": "张家",
            "note": "常驻北京",
            "members": [
                {"name": "爸爸"},
                {"name": "小明", "is_child": True, "note": "8 岁"},
            ],
        },
    )
    assert created.status_code == 200, created.text
    data = created.json()["data"]
    assert data["name"] == "张家"
    assert {m["name"] for m in data["members"]} == {"爸爸", "小明"}
    household_id = data["id"]

    updated = env.client.put(f"/api/v1/households/{household_id}", json={"name": "张氏家庭"})
    assert updated.status_code == 200
    assert updated.json()["data"]["name"] == "张氏家庭"

    detail = env.client.get(f"/api/v1/households/{household_id}").json()["data"]
    assert detail["note"] == "常驻北京"
    assert len(detail["members"]) == 2

    listed = env.client.get("/api/v1/households").json()["data"]
    assert len(listed) == 1

    deleted = env.client.delete(f"/api/v1/households/{household_id}")
    assert deleted.status_code == 200
    assert env.client.get(f"/api/v1/households/{household_id}").status_code == 404


def test_frequent_traveler_crud(env):
    created = env.client.post("/api/v1/frequent-travelers", json={"name": "李雷", "note": "老同学"})
    assert created.status_code == 200, created.text
    traveler_id = created.json()["data"]["id"]

    assert len(env.client.get("/api/v1/frequent-travelers").json()["data"]) == 1

    updated = env.client.put(f"/api/v1/frequent-travelers/{traveler_id}", json={"name": "李雷雷"})
    assert updated.json()["data"]["name"] == "李雷雷"

    assert env.client.delete(f"/api/v1/frequent-travelers/{traveler_id}").status_code == 200
    assert env.client.get("/api/v1/frequent-travelers").json()["data"] == []


def test_add_member_from_frequent_traveler(env):
    traveler = env.client.post("/api/v1/frequent-travelers", json={"name": "韩梅梅", "note": "同事"}).json()["data"]
    household = env.client.post("/api/v1/households", json={"name": "同行小组"}).json()["data"]

    resp = env.client.post(
        f"/api/v1/households/{household['id']}/members",
        json={"frequent_traveler_id": traveler["id"]},
    )
    assert resp.status_code == 200, resp.text
    member = resp.json()["data"]
    assert member["name"] == "韩梅梅"
    assert member["frequent_traveler_id"] == traveler["id"]
    assert member["note"] == "同事"


def test_quick_add_from_household_and_frequent(env):
    household = env.client.post(
        "/api/v1/households",
        json={"name": "王家", "members": [
            {"name": "王先生"}, {"name": "王太太"}, {"name": "小王", "is_child": True},
        ]},
    ).json()["data"]
    frequent = env.client.post("/api/v1/frequent-travelers", json={"name": "导游阿明"}).json()["data"]

    resp = env.client.post(
        "/api/v1/trips/trip-1/participants/quick-add",
        json={"household_ids": [household["id"]], "frequent_traveler_ids": [frequent["id"]]},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert len(data["created"]) == 4
    assert data["traveler_count"] == 4
    assert data["children_count"] == 1
    assert data["has_children"] is True

    # 同一来源重复带入应被跳过，人数不变
    again = env.client.post(
        "/api/v1/trips/trip-1/participants/quick-add",
        json={"household_ids": [household["id"]], "frequent_traveler_ids": [frequent["id"]]},
    ).json()["data"]
    assert again["created"] == []
    assert again["traveler_count"] == 4

    listed = env.client.get("/api/v1/trips/trip-1/participants").json()["data"]
    assert len(listed) == 4
    assert next(p for p in listed if p["name"] == "小王")["family"] == "王家"


def test_participants_split_view_is_compatible(env):
    env.client.post(
        "/api/v1/trips/trip-1/participants",
        json={"participants": [{"name": "甲"}, {"name": "乙", "is_child": True}]},
    )
    rows = env.client.get("/api/v1/trips/trip-1/participants/split").json()["data"]
    assert [set(row) for row in rows] == [
        {"id", "name", "is_child", "family"},
        {"id", "name", "is_child", "family"},
    ]
    assert sorted(row["name"] for row in rows) == ["乙", "甲"]


def test_quick_add_all_children_is_rejected(env):
    household = env.client.post(
        "/api/v1/households",
        json={"name": "儿童团", "members": [{"name": "小朋友", "is_child": True}]},
    ).json()["data"]

    resp = env.client.post(
        "/api/v1/trips/trip-2/participants/quick-add",
        json={"household_ids": [household["id"]]},
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == ErrorCode.VALIDATION
    assert "成人" in resp.json()["message"]
    # 事务回滚，未留下参与人
    assert env.client.get("/api/v1/trips/trip-2/participants").json()["data"] == []


def test_household_is_owner_isolated(env):
    other = Household(id="h-other", owner_id="owner-2", name="别人家")
    env.db.add(other)
    env.db.commit()
    assert env.client.get("/api/v1/households/h-other").status_code == 404
