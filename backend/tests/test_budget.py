"""预算设置 / 查询 / 费用对比 API 契约测试（内存 SQLite + 依赖覆盖）。"""
from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1 import deps
from app.core.errors import ErrorCode
from app.db.base import Base
from app.models.budget import BudgetCategory
from app.models.expense import Expense
from app.models.trip import Trip
from app.models.user import User

_TABLES = [Trip.__table__, BudgetCategory.__table__, Expense.__table__, User.__table__]


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
    trip = Trip(id="trip-1", owner_id=owner.id, title="预算行程", currency="CNY")
    db.add_all([owner, trip])
    db.commit()

    fake_user = SimpleNamespace(id=owner.id, role="owner", must_set_password=False)
    monkeypatch.setitem(client.app.dependency_overrides, deps.require_user, lambda: fake_user)
    monkeypatch.setitem(client.app.dependency_overrides, deps.get_db, lambda: db)
    yield SimpleNamespace(client=client, db=db, owner=owner, trip=trip)
    db.close()
    engine.dispose()


def test_set_and_get_budget(env):
    resp = env.client.put(
        "/api/v1/trips/trip-1/budget",
        json={"total_budget": 5000, "categories": [
            {"category": "food", "amount": 1500, "note": "吃货基金"},
            {"category": "transport", "amount": 800},
        ]},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["total_budget"] == 5000.0
    assert {row["category"] for row in data["categories"]} == {"food", "transport"}

    got = env.client.get("/api/v1/trips/trip-1/budget").json()["data"]
    assert got["total_budget"] == 5000.0
    food = next(row for row in got["categories"] if row["category"] == "food")
    assert food["amount"] == 1500.0
    assert food["label"] == "餐饮"
    assert any(item["value"] == "other" for item in got["available_categories"])


def test_upsert_category_does_not_duplicate(env):
    env.client.put("/api/v1/trips/trip-1/budget", json={"categories": [{"category": "food", "amount": 100}]})
    resp = env.client.put("/api/v1/trips/trip-1/budget", json={"categories": [{"category": "food", "amount": 300}]})
    assert resp.status_code == 200
    rows = [row for row in resp.json()["data"]["categories"] if row["category"] == "food"]
    assert len(rows) == 1
    assert rows[0]["amount"] == 300.0


def test_budget_comparison_reports_spent_and_over_budget(env):
    env.client.put(
        "/api/v1/trips/trip-1/budget",
        json={"total_budget": 1000, "categories": [
            {"category": "food", "amount": 200},
            {"category": "transport", "amount": 500},
        ]},
    )
    env.db.add_all([
        Expense(trip_id="trip-1", category="food", amount=Decimal("150.00"), currency="CNY"),
        Expense(trip_id="trip-1", category="food", amount=Decimal("100.00"), currency="CNY"),
        Expense(trip_id="trip-1", category="transport", amount=Decimal("600.00"), currency="CNY"),
    ])
    env.db.commit()

    data = env.client.get("/api/v1/trips/trip-1/budget/comparison").json()["data"]
    assert data["total_spent"] == 850.0
    assert data["total_remaining"] == 150.0
    assert data["total_over_budget"] is False
    assert data["total_usage_rate"] == 85.0

    by_category = {row["category"]: row for row in data["by_category"]}
    assert by_category["food"]["spent"] == 250.0
    assert by_category["food"]["remaining"] == -50.0
    assert by_category["food"]["over_budget"] is True
    assert by_category["transport"]["remaining"] == -100.0
    assert by_category["transport"]["over_budget"] is True


def test_comparison_with_exchange_rate(env):
    env.client.put("/api/v1/trips/trip-1/budget", json={"total_budget": 1000})
    # 100 USD * 7 = 700 CNY
    env.db.add(Expense(
        trip_id="trip-1", category="shopping", amount=Decimal("100.00"),
        currency="USD", exchange_rate=Decimal("7.0000"),
    ))
    env.db.commit()
    data = env.client.get("/api/v1/trips/trip-1/budget/comparison").json()["data"]
    assert data["total_spent"] == 700.0
    assert data["total_remaining"] == 300.0


def test_total_budget_can_be_cleared(env):
    env.client.put("/api/v1/trips/trip-1/budget", json={"total_budget": 2000})
    resp = env.client.put("/api/v1/trips/trip-1/budget", json={"total_budget": None})
    assert resp.status_code == 200
    assert resp.json()["data"]["total_budget"] is None


def test_delete_category_budget(env):
    env.client.put(
        "/api/v1/trips/trip-1/budget",
        json={"categories": [{"category": "food", "amount": 500}]},
    )
    resp = env.client.delete("/api/v1/trips/trip-1/budget/categories/food")
    assert resp.status_code == 200
    assert resp.json()["data"]["deleted"] is True

    left = env.client.get("/api/v1/trips/trip-1/budget").json()["data"]["categories"]
    assert left == []

    missing = env.client.delete("/api/v1/trips/trip-1/budget/categories/food")
    assert missing.status_code == 404
    assert missing.json()["code"] == ErrorCode.NOT_FOUND
