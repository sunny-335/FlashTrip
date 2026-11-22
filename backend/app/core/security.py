"""安全：Fernet 加密、argon2 密码哈希、JWT。

主密钥来源优先级：FLASHTRIP_SECRET_KEY（env） > config.json.secret_key。
未安装/未生成主密钥时抛 RuntimeError，绝不回退内置硬编码密钥。
"""
from __future__ import annotations

import base64
import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings, load_config

_ph = PasswordHasher()
_TOKEN_TTL_HOURS = 24 * 7


def get_secret_key() -> str:
    settings = get_settings()
    if settings.SECRET_KEY:
        return settings.SECRET_KEY
    key = str(load_config().get("secret_key") or "")
    if not key:
        raise RuntimeError("主密钥未配置：请在安装向导中生成并备份 FLASHTRIP_SECRET_KEY")
    return key


@lru_cache(maxsize=8)
def _fernet(key: str) -> Fernet:
    derived = base64.urlsafe_b64encode(hashlib.sha256(key.encode("utf-8")).digest())
    return Fernet(derived)


def encrypt(plain: str) -> str:
    if not plain:
        return ""
    return "ENC:" + _fernet(get_secret_key()).encrypt(plain.encode("utf-8")).decode("ascii")


def decrypt(token: str) -> str:
    if not token:
        return ""
    if not token.startswith("ENC:"):
        return token  # 兼容迁移前的明文（不推荐）
    try:
        return _fernet(get_secret_key()).decrypt(token[4:].encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise RuntimeError("无法解密：主密钥可能已更换，请重新填写该密钥") from exc


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(hashed: str, password: str) -> bool:
    try:
        return _ph.verify(hashed, password)
    except (VerifyMismatchError, ValueError):
        return False


def create_access_token(user_id: str, extra: dict[str, Any] | None = None, ttl_hours: int = _TOKEN_TTL_HOURS) -> str:
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": user_id,
        "iat": now,
        "exp": now + timedelta(hours=ttl_hours),
        "jti": uuid.uuid4().hex,
        "type": "access",
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, get_secret_key(), algorithm="HS256")


def decode_access_token(token: str) -> dict[str, Any]:
    return jwt.decode(token, get_secret_key(), algorithms=["HS256"])


def new_id() -> str:
    return uuid.uuid4().hex
