"""密码策略契约：长度、字符类别、管理员四类、连续串拒绝、强度分级。"""
from __future__ import annotations

import pytest

from app.core.errors import AppError, ErrorCode
from app.services import password_policy as pp

# 8 位、4 类齐全、无连续/重复串的合法密码
_VALID = "Xk9!mQ2v"


def _assert_invalid(value: str, *, is_admin: bool = False) -> None:
    with pytest.raises(AppError) as exc:
        pp.validate_password(value, is_admin=is_admin)
    assert exc.value.code == ErrorCode.VALIDATION


def test_char_classes_constant():
    assert pp.CHAR_CLASSES == ("lower", "upper", "digit", "special")


def test_valid_password():
    pp.validate_password(_VALID)
    pp.validate_password(_VALID, is_admin=True)


def test_length_bounds():
    _assert_invalid("Xk9!mQ2")      # 7 位
    _assert_invalid(_VALID * 5)     # 40 位


def test_two_classes_required():
    _assert_invalid("akmzqtvb")     # 仅小写 1 类，且无连续串
    pp.validate_password("akmzqtv7")  # 小写 + 数字 2 类，合法


def test_admin_requires_four_classes():
    _assert_invalid("akmzqtv7", is_admin=True)   # 2 类
    _assert_invalid("Akzq9v7m", is_admin=True)   # 3 类，缺 special


@pytest.mark.parametrize("value", [
    "1234Xk!m", "4321Xk!m", "abcdXk9!", "dcbaXk9!", "aaaaXk9!", "Abcd!234",
])
def test_sequences_rejected(value):
    _assert_invalid(value)


def test_strength_levels_and_shape():
    weak = pp.password_strength("abc")
    strong = pp.password_strength(_VALID)
    assert set(strong) == {
        "score", "label", "hints", "valid", "lengthOk",
        "classCount", "hasSequence", "adminOk",
    }
    assert 0 <= weak["score"] <= 4 and 0 <= strong["score"] <= 4
    assert strong["score"] > weak["score"]
    assert strong["label"] in ("弱", "一般", "较强", "强")
    assert strong["valid"] is True and strong["adminOk"] is True
    assert strong["lengthOk"] is True and strong["classCount"] == 4
    assert strong["hasSequence"] is False
    assert isinstance(strong["hints"], list) and strong["hints"]
    assert weak["valid"] is False


def test_strength_flags_sequence_and_length():
    info = pp.password_strength("1234Xk!m")
    assert info["hasSequence"] is True
    assert info["valid"] is False
    assert pp.password_strength("abc")["lengthOk"] is False
