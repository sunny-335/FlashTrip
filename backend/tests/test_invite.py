"""邀请链接：带密码一次激活 scope=full、不带密码不消耗次数且 setupToken 可完成设密、
过期/撤销 INVITE_INVALID、已有密码 action=login、force_reset 走重置、成员联系方式落库。

直接调 invite_service + 临时 SQLite；token 用真实 create/decode_access_token，
不涉及真实网络与 SMTP。
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.errors import AppError, ErrorCode
from app.core.security import decode_access_token, hash_password, new_id, verify_password
from app.db.base import Base
from app.models.collab import Invitation, Permission, TripMember
from app.models.trip import Trip
from app.models.user import User
from app.services import invite_service as svc

_TABLES = [User.__table__, Trip.__table__, TripMember.__table__,
           Permission.__table__, Invitation.__table__]


@pytest.fixture()
def env(tmp_path):
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'invite.db').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine, tables=_TABLES)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    db = Session()
    trip = Trip(id=new_id(), owner_id="owner-1", title="苏州三日游")
    db.add(trip)
    db.commit()
    try:
        yield SimpleNamespace(db=db, trip=trip)
    finally:
        db.close()
        engine.dispose()


def _invite(db, trip_id, **kwargs):
    target = kwargs.pop("target_value", "guest")
    return svc.create_invitation(
        db, trip_id=trip_id, channel="username", target_value=target, **kwargs
    )


def _existing_user(db, username="guest", password="OldPass9x"):
    user = User(
        id=new_id(), username=username, password_hash=hash_password(password),
        role="member", is_active=True, must_set_password=False,
        password_set_at=datetime.now(timezone.utc),
    )
    db.add(user)
    db.commit()
    return user


def test_accept_with_password_activates_once(env):
    inv = _invite(env.db, env.trip.id)
    result = svc.accept(env.db, inv["token"], password="Abc!9xQz")
    assert result["scope"] == "full"
    assert result["tripId"] == env.trip.id
    assert result["accessToken"]
    assert decode_access_token(result["accessToken"])["scope"] == "full"
    assert env.db.get(Invitation, inv["invitation"]["id"]).used_count == 1
    assert env.db.query(TripMember).filter(TripMember.trip_id == env.trip.id).count() == 1

    # 次数用尽后统一 INVITE_INVALID，不泄露行程
    with pytest.raises(AppError) as err:
        svc.accept(env.db, inv["token"], password="Abc!9xQz")
    assert err.value.code == ErrorCode.INVITE_INVALID


def test_accept_without_password_uses_setup_token(env):
    inv = _invite(env.db, env.trip.id)
    with pytest.raises(AppError) as err:
        svc.accept(env.db, inv["token"])
    assert err.value.code == ErrorCode.PASSWORD_REQUIRED
    detail = json.loads(err.value.detail)
    assert detail["scope"] == "setup"
    assert detail["setupToken"]

    inv_row = env.db.get(Invitation, inv["invitation"]["id"])
    assert inv_row.used_count == 0
    assert env.db.query(TripMember).count() == 0

    claims = decode_access_token(detail["setupToken"])
    result = svc.activate_from_setup(env.db, claims, "NewPass9x")
    assert result["scope"] == "full"
    assert env.db.get(Invitation, inv["invitation"]["id"]).used_count == 1
    user = env.db.get(User, detail["userId"])
    assert user.must_set_password is False
    assert verify_password(user.password_hash, "NewPass9x")


def test_expired_and_revoked_are_invalid(env):
    inv = _invite(env.db, env.trip.id, expires_days=1)
    row = env.db.get(Invitation, inv["invitation"]["id"])
    row.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
    env.db.commit()
    with pytest.raises(AppError) as err:
        svc.public_info(env.db, inv["token"])
    assert err.value.code == ErrorCode.INVITE_INVALID
    with pytest.raises(AppError) as err:
        svc.accept(env.db, inv["token"], password="Abc!9xQz")
    assert err.value.code == ErrorCode.INVITE_INVALID

    inv2 = _invite(env.db, env.trip.id, target_value="guest2")
    svc.revoke_invitation(env.db, env.trip.id, inv2["invitation"]["id"], "owner-1")
    with pytest.raises(AppError) as err:
        svc.public_info(env.db, inv2["token"])
    assert err.value.code == ErrorCode.INVITE_INVALID
    with pytest.raises(AppError) as err:
        svc.accept(env.db, inv2["token"])
    assert err.value.code == ErrorCode.INVITE_INVALID


def test_existing_password_user_gets_login_action(env):
    _existing_user(env.db)
    inv = _invite(env.db, env.trip.id, force_reset=False,
                  nickname="老王", email="wang@example.com")
    info = svc.public_info(env.db, inv["token"])
    assert info["action"] == "login"
    assert info["hasPassword"] is True
    assert info["forceReset"] is False
    assert info["nickname"] == "老王"
    assert info["email"] == "wang@example.com"
    assert info["next"] == f"/invite/{inv['token']}"

    result = svc.accept(env.db, inv["token"], password="Abc!9xQz")
    assert result["action"] == "login"
    assert result["tripId"] == env.trip.id
    assert result.get("accessToken") is None
    # 不消耗次数、不建成员、不签发凭证
    assert env.db.get(Invitation, inv["invitation"]["id"]).used_count == 0
    assert env.db.query(TripMember).count() == 0


def test_force_reset_routes_to_reset_scope(env):
    user = _existing_user(env.db)
    old_hash = user.password_hash
    inv = _invite(env.db, env.trip.id, force_reset=True)

    info = svc.public_info(env.db, inv["token"])
    assert info["forceReset"] is True
    assert info["hasPassword"] is True
    assert info["action"] == "reset"
    assert info["requiresPassword"] is True

    with pytest.raises(AppError) as err:
        svc.accept(env.db, inv["token"], password="Abc!9xQz")
    assert err.value.code == ErrorCode.PASSWORD_REQUIRED
    detail = json.loads(err.value.detail)
    assert detail["scope"] == "reset"
    assert detail["setupToken"]
    assert env.db.get(Invitation, inv["invitation"]["id"]).used_count == 0

    claims = decode_access_token(detail["setupToken"])
    result = svc.activate_from_setup(env.db, claims, "Brand9xQz")
    assert result["scope"] == "full"
    assert result["userId"] == user.id

    fresh = env.db.get(User, user.id)
    assert fresh.must_set_password is False
    assert fresh.password_hash != old_hash  # 已有密码也被强制覆盖
    assert verify_password(fresh.password_hash, "Brand9xQz")
    assert env.db.get(Invitation, inv["invitation"]["id"]).used_count == 1
    member = env.db.query(TripMember).filter(TripMember.trip_id == env.trip.id).one()
    assert member.user_id == user.id


def test_member_contacts_persist_on_activation(env):
    inv = _invite(env.db, env.trip.id, nickname="小张", email="zhang@example.com")
    assert inv["invitation"]["nickname"] == "小张"
    assert inv["invitation"]["email"] == "zhang@example.com"
    assert inv["invitation"]["forceReset"] is False

    svc.accept(env.db, inv["token"], password="Abc!9xQz")
    member = env.db.query(TripMember).filter(TripMember.trip_id == env.trip.id).one()
    assert member.nickname == "小张"
    assert member.email == "zhang@example.com"
    assert env.db.query(Permission).filter(Permission.trip_member_id == member.id).count() >= 1


def test_weak_password_rejected_by_accept(env):
    inv = _invite(env.db, env.trip.id)
    with pytest.raises(AppError) as err:
        svc.accept(env.db, inv["token"], password="abcd1234")
    assert err.value.code == ErrorCode.VALIDATION
    assert env.db.get(Invitation, inv["invitation"]["id"]).used_count == 0
