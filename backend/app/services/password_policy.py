"""密码强度策略：长度 / 字符类别 / 连续串 / 管理员强制四类。

规则统一由 validate_password 与 password_strength 共用，避免安装向导、
设密、重置密码等调用方出现口径不一致。
"""
from __future__ import annotations

from app.core.errors import AppError, ErrorCode

CHAR_CLASSES = ("lower", "upper", "digit", "special")

_MIN_LEN = 8
_MAX_LEN = 32
_SEQ_LEN = 4  # 连续/重复串的判定窗口长度


def _classes(password: str) -> set[str]:
    """按 ASCII 归类字符；非字母数字一律视为 special（中文亦归入此类）。"""
    result: set[str] = set()
    for ch in password:
        if "a" <= ch <= "z":
            result.add("lower")
        elif "A" <= ch <= "Z":
            result.add("upper")
        elif "0" <= ch <= "9":
            result.add("digit")
        else:
            result.add("special")
    return result


def _has_sequence(password: str) -> bool:
    """连续串检测：>=4 递增/递减数字、>=4 递增/递减字母、>=4 重复字符。"""
    if len(password) < _SEQ_LEN:
        return False
    for i in range(len(password) - _SEQ_LEN + 1):
        window = password[i:i + _SEQ_LEN]
        # 4 位以上重复字符，如 aaaa / 1111
        if len(set(window)) == 1:
            return True
        # 连续数字递增 / 递减，如 1234 / 4321
        if window.isdigit():
            nums = [int(ch) for ch in window]
            diffs = [nums[j + 1] - nums[j] for j in range(_SEQ_LEN - 1)]
            if all(d == 1 for d in diffs) or all(d == -1 for d in diffs):
                return True
        # 连续字母递增 / 递减，如 abcd / dcba（大小写不敏感）
        if window.isalpha():
            nums = [ord(ch.lower()) for ch in window]
            diffs = [nums[j + 1] - nums[j] for j in range(_SEQ_LEN - 1)]
            if all(d == 1 for d in diffs) or all(d == -1 for d in diffs):
                return True
    return False


def validate_password(password: str, *, is_admin: bool = False) -> None:
    """校验失败抛 AppError(VALIDATION, 中文原因)；通过返回 None。"""
    value = password or ""
    if not (_MIN_LEN <= len(value) <= _MAX_LEN):
        raise AppError(ErrorCode.VALIDATION, "密码长度须为 8–32 位")

    count = len(_classes(value))
    if is_admin:
        if count < len(CHAR_CLASSES):
            raise AppError(ErrorCode.VALIDATION, "管理员密码须同时包含大写字母、小写字母、数字和特殊字符")
    elif count < 2:
        raise AppError(ErrorCode.VALIDATION, "密码至少包含 2 类字符（小写、大写、数字、特殊字符）")

    if _has_sequence(value):
        raise AppError(ErrorCode.VALIDATION, "密码不得包含连续或重复字符串（如 1234、abcd、aaaa）")


def password_strength(password: str) -> dict:
    """返回前端强度条的完整指标，不抛异常（空串也可安全评估）。"""
    value = password or ""
    length_ok = _MIN_LEN <= len(value) <= _MAX_LEN
    class_count = len(_classes(value))
    has_sequence = _has_sequence(value)
    valid = length_ok and class_count >= 2 and not has_sequence
    admin_ok = length_ok and class_count == len(CHAR_CLASSES) and not has_sequence

    score = 0
    if length_ok:
        score += 1
    if class_count >= 2:
        score += 1
    if class_count >= 3:
        score += 1
    if class_count >= 4 and len(value) >= 12 and not has_sequence:
        score += 1
    if has_sequence:
        score = min(score, 1)
    score = max(0, min(4, score))
    label = {0: "弱", 1: "弱", 2: "一般", 3: "较强", 4: "强"}[score]

    hints: list[str] = []
    if not length_ok:
        hints.append("密码长度须为 8–32 位")
    if class_count < 2:
        hints.append("建议至少混合 2 类字符（小写、大写、数字、特殊字符）")
    if class_count < len(CHAR_CLASSES):
        hints.append("增加大写字母、数字或特殊字符可提升强度")
    if has_sequence:
        hints.append("避免使用连续或重复字符串（如 1234、abcd、aaaa）")
    if not hints:
        hints.append("密码强度良好")

    return {
        "score": score,
        "label": label,
        "hints": hints,
        "valid": valid,
        "lengthOk": length_ok,
        "classCount": class_count,
        "hasSequence": has_sequence,
        "adminOk": admin_ok,
    }
