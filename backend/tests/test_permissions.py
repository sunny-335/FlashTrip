"""权限矩阵：默认只读成员任何写操作返回 1003（FORBIDDEN）。

用 monkeypatch 注入假的 trip 模块与内存态 db/user，完全不依赖真实数据库表，
且直接调用 require_permission 生成的依赖闭包，验证「与人工同一套判定」。
"""
from __future__ import annotations

import sys
import types
from types import SimpleNamespace

import pytest

from app.api.v1 import deps
from app.core.errors import AppError, ErrorCode
from app.models.collab import Permission, TripMember


class _FakeQuery:
    def __init__(self, model, db: "_FakeDB") -> None:
        self.model = model
        self.db = db
        self._key = None

    def filter(self, *conditions):
        # 从 SQLAlchemy 表达式里解析 permission_key 的绑定值
        for condition in conditions:
            try:
                left, right = condition.left, condition.right
                if getattr(left, "key", None) == "permission_key":
                    self._key = getattr(right, "value", None)
            except (AttributeError, TypeError):
                continue
        return self

    def first(self):
        if self.model is TripMember:
            return self.db.member
        if self.model is Permission:
            return SimpleNamespace(granted=True) if self._key in self.db.granted_keys else None
        return None


class _FakeDB:
    def __init__(self, *, member=True, granted_keys=("trip:read",), owner_id="owner-1") -> None:
        self.trip = SimpleNamespace(owner_id=owner_id)
        self.member = SimpleNamespace(id="tm-1") if member else None
        self.granted_keys = set(granted_keys)

    def get(self, model, key):
        return self.trip

    def query(self, model):
        return _FakeQuery(model, self)


@pytest.fixture()
def fake_trip_module(monkeypatch):
    module = types.ModuleType("app.models.trip")

    class Trip:  # noqa: D401  仅用于 deps 内的运行时 import
        pass

    module.Trip = Trip
    monkeypatch.setitem(sys.modules, "app.models.trip", module)
    return module


def _call(key: str, *, db: _FakeDB, user: SimpleNamespace, trip_id: str = "trip-1"):
    dependency = deps.require_permission(key)
    request = SimpleNamespace(path_params={"trip_id": trip_id})
    return dependency(request=request, db=db, user=user)


def _member(**overrides) -> SimpleNamespace:
    base = {"id": "member-1", "role": "member", "must_set_password": False}
    base.update(overrides)
    return SimpleNamespace(**base)


def test_default_permission_keys_is_readonly():
    assert deps.DEFAULT_PERMISSION_KEYS == ("trip:read",)
    assert "plan:write" in deps.PERMISSION_KEYS


def test_default_readonly_member_write_is_forbidden(fake_trip_module):
    db = _FakeDB(granted_keys=("trip:read",))
    with pytest.raises(AppError) as exc:
        _call("plan:write", db=db, user=_member())
    assert exc.value.code == ErrorCode.FORBIDDEN
    assert exc.value.status == 403


@pytest.mark.parametrize("key", ["plan:write", "booking:write", "expense:write", "member:manage"])
def test_all_write_keys_rejected_for_readonly(fake_trip_module, key):
    with pytest.raises(AppError) as exc:
        _call(key, db=_FakeDB(), user=_member())
    assert exc.value.code == 1003


def test_no_permission_records_rejected(fake_trip_module):
    with pytest.raises(AppError) as exc:
        _call("moment:write", db=_FakeDB(granted_keys=()), user=_member())
    assert exc.value.code == ErrorCode.FORBIDDEN


def test_non_member_rejected(fake_trip_module):
    with pytest.raises(AppError) as exc:
        _call("plan:write", db=_FakeDB(member=False), user=_member())
    assert exc.value.code == ErrorCode.FORBIDDEN


def test_read_permission_granted_to_default_member(fake_trip_module):
    result = _call("trip:read", db=_FakeDB(), user=_member())
    assert result.id == "member-1"


def test_owner_bypasses_permission_table(fake_trip_module):
    owner = _member(id="owner-1")
    assert _call("plan:write", db=_FakeDB(), user=owner) is owner


def test_admin_bypasses_permission_table(fake_trip_module):
    admin = _member(role="admin")
    assert _call("member:manage", db=_FakeDB(granted_keys=()), user=admin) is admin


def test_granted_write_key_allowed(fake_trip_module):
    member = _member()
    result = _call("plan:write", db=_FakeDB(granted_keys=("trip:read", "plan:write")), user=member)
    assert result is member


def test_unknown_permission_key_rejected():
    with pytest.raises(ValueError):
        deps.require_permission("not:a:key")
