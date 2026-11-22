"""分账服务：三种模式金额精确、儿童免账、尾差归集、split_summary 自洽。

直接调 expense_service + 临时 SQLite（沿用 test_plan_moves.py 的隔离方式），
不经过 API 权限依赖、不发起任何网络或 SMTP 请求。
"""
from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.errors import AppError, ErrorCode
from app.core.security import new_id
from app.db.base import Base
from app.models.expense import Expense
from app.models.trip import Trip
from app.services import expense_service as svc

_TABLES = [Trip.__table__, Expense.__table__]
ZERO = Decimal("0")


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'split.db').as_posix()}",
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


def _trip(adults: int = 3, children: int = 0) -> SimpleNamespace:
    return SimpleNamespace(traveler_count=adults + children, children_count=children)


@pytest.mark.parametrize("mode", ["equal", "child_free", "custom"])
@pytest.mark.parametrize("amount", ["100.00", "100.01", "0.03", "999.99"])
def test_shares_sum_exactly_equals_amount(mode, amount):
    """三种模式下各份额 amount 之和必须精确等于量化后的费用金额（Decimal）。"""
    total = Decimal(amount)
    shares = svc.compute_shares(total, mode, _trip(adults=2, children=1))
    assert all(isinstance(item["amount"], Decimal) for item in shares)
    assert sum((item["amount"] for item in shares), ZERO) == total


def test_child_free_children_share_zero():
    """儿童免账：儿童 share=0、amount=0，且不参与尾差分摊。"""
    shares = svc.compute_shares(Decimal("90.00"), "child_free", _trip(adults=2, children=1))
    by_id = {item["participant_id"]: item for item in shares}
    assert by_id["p3"]["share"] == 0
    assert by_id["p3"]["amount"] == ZERO
    assert sum((item["amount"] for item in shares), ZERO) == Decimal("90.00")


def test_remainder_goes_to_last_effective_participant():
    """不能整除时尾差归入最后一位有效份额者，合计仍精确。"""
    shares = svc.compute_shares(Decimal("100.00"), "equal", _trip(adults=3))
    amounts = [item["amount"] for item in shares]
    assert amounts == [Decimal("33.33"), Decimal("33.33"), Decimal("33.34")]
    assert sum(amounts, ZERO) == Decimal("100.00")


def test_custom_explicit_amounts_must_match_total():
    """自定义模式传入显式金额时，合计不符必须 VALIDATION。"""
    detail = {
        "participants": [
            {"id": "a", "name": "A", "is_child": False},
            {"id": "b", "name": "B", "is_child": False},
        ],
        "shares": [
            {"participant_id": "a", "amount": "60.00"},
            {"participant_id": "b", "amount": "40.00"},
        ],
    }
    shares = svc.compute_shares(Decimal("100.00"), "custom", _trip(), detail)
    assert sum((item["amount"] for item in shares), ZERO) == Decimal("100.00")

    bad = dict(detail)
    bad["shares"] = [
        {"participant_id": "a", "amount": "60.00"},
        {"participant_id": "b", "amount": "30.00"},
    ]
    with pytest.raises(AppError) as err:
        svc.compute_shares(Decimal("100.00"), "custom", _trip(), bad)
    assert err.value.code == ErrorCode.VALIDATION


def test_split_summary_is_self_consistent(db):
    """汇总：total = 各笔费用之和；owed 合计 = total；balance 之和恒为 0。"""
    trip = Trip(id=new_id(), owner_id="owner-1", title="分账行程",
                traveler_count=3, children_count=1)
    db.add(trip)
    db.commit()
    db.add_all([
        Expense(id=new_id(), trip_id=trip.id, amount=Decimal("100.00"),
                paid_by="p1", split_mode="equal"),
        Expense(id=new_id(), trip_id=trip.id, amount=Decimal("50.05"),
                paid_by="p2", split_mode="child_free"),
        Expense(id=new_id(), trip_id=trip.id, amount=Decimal("9.99"),
                paid_by="p3", split_mode="payer_only"),
    ])
    db.commit()

    summary = svc.split_summary(db, trip.id)
    assert Decimal(str(summary["total"])) == Decimal("160.04")
    assert sum((Decimal(str(p["owed"])) for p in summary["participants"]), ZERO) == Decimal("160.04")
    assert sum((Decimal(str(p["balance"])) for p in summary["participants"]), ZERO) == ZERO
    assert summary["travelerCount"] == 3
    assert summary["childrenCount"] == 1
