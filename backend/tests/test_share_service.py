"""分享服务契约：token 只存 hash、公开视图裁剪、过期/撤销失败、访问计数。"""
from __future__ import annotations

import hashlib
import json
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.errors import AppError, ErrorCode
from app.db.base import Base
from app.models.booking import Booking
from app.models.expense import Expense
from app.models.moment import Moment
from app.models.packing import PackingItem, PackingList
from app.models.share import ShareLink
from app.models.transport import Transport
from app.models.trip import Trip
from app.services import share_service as ss


@pytest.fixture()
def db():
    import app.models  # 触发动态导入，填充 Base.metadata

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture()
def trip(db):
    row = Trip(
        id="t1", owner_id="u1", title="苏州三日游", destination="苏州",
        start_date=date(2026, 11, 25), end_date=date(2026, 11, 27),
        status="planned", cover_url="https://example.test/cover.jpg",
    )
    db.add(row)
    db.commit()
    return row


def test_token_only_hash_stored(db, trip):
    result = ss.create_share(db, "t1", title="公开版", include_expenses=False)
    assert result["token"]
    assert result["url"] == f"/share/{result['token']}"
    row = db.get(ShareLink, result["id"])
    assert row.token_hash != result["token"]
    assert row.token_hash == hashlib.sha256(result["token"].encode()).hexdigest()
    assert "token" not in row.__dict__  # 明文绝不落库


def test_public_view_trims_expenses(db, trip):
    db.add(Expense(trip_id="t1", amount=Decimal("88.50"), category="food"))
    db.add(Transport(trip_id="t1", mode="train", from_name="上海", to_name="苏州",
                     price=Decimal("39.5")))
    db.add(Booking(trip_id="t1", type="hotel", vendor="某酒店", amount=Decimal("300")))
    db.commit()

    result = ss.create_share(db, "t1", include_expenses=False)
    view = ss.public_view(db, result["token"])
    assert view["expenses"] is None
    dumped = json.dumps(view, ensure_ascii=False)
    assert "amount" not in dumped and "88.5" not in dumped
    assert view["trip"]["title"] == "苏州三日游"
    assert view["transports"] and view["bookings"]


def test_public_view_includes_expenses_when_enabled(db, trip):
    db.add(Expense(trip_id="t1", amount=Decimal("88.50"), category="food"))
    db.commit()
    result = ss.create_share(db, "t1", include_expenses=True)
    view = ss.public_view(db, result["token"])
    assert isinstance(view["expenses"], list) and len(view["expenses"]) == 1
    assert view["expenses"][0]["amount"] == 88.5


def test_moments_only_public(db, trip):
    db.add(Moment(trip_id="t1", content="公开的瞬间", is_public=True))
    db.add(Moment(trip_id="t1", content="私密的瞬间", is_public=False))
    db.commit()
    result = ss.create_share(db, "t1", include_moments=True)
    view = ss.public_view(db, result["token"])
    assert len(view["moments"]) == 1
    assert view["moments"][0]["content"] == "公开的瞬间"


def test_packing_shape(db, trip):
    db.add(PackingList(id="pl1", trip_id="t1", name="默认清单", sort_key="a"))
    db.add(PackingItem(list_id="pl1", name="雨伞", qty=1, checked=False, sort_key="a"))
    db.commit()
    result = ss.create_share(db, "t1", include_packing=True)
    view = ss.public_view(db, result["token"])
    assert view["packing"][0]["list"]["name"] == "默认清单"
    assert view["packing"][0]["items"][0]["name"] == "雨伞"


def test_expired_and_revoked_fail(db, trip):
    expired = ss.create_share(db, "t1", expires_days=-1)
    with pytest.raises(AppError) as exc:
        ss.validate(db, expired["token"])
    assert exc.value.code == ErrorCode.NOT_FOUND

    revoked = ss.create_share(db, "t1")
    ss.revoke_share(db, "t1", revoked["id"])
    with pytest.raises(AppError) as exc:
        ss.validate(db, revoked["token"])
    assert exc.value.code == ErrorCode.NOT_FOUND


def test_view_count_and_list_shapes(db, trip):
    result = ss.create_share(db, "t1")
    ss.public_view(db, result["token"])
    ss.public_view(db, result["token"])
    assert db.get(ShareLink, result["id"]).view_count == 2
    items = ss.list_shares(db, "t1")
    assert items
    assert all("token" not in item and "token_hash" not in item for item in items)
