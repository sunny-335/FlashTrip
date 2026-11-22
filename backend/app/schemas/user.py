"""用户相关请求/响应 schema。"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class SetPasswordIn(BaseModel):
    """邀请成员首次设密（凭邀请 token 登录后调用）。"""

    new_password: str = Field(min_length=8, max_length=256)


class ChangePasswordIn(BaseModel):
    old_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=8, max_length=256)


class UserOut(ORMModel):
    id: str
    username: str
    email: str | None = None
    phone: str | None = None
    display_name: str = ""
    avatar_url: str | None = None
    role: str = "member"
    is_active: bool = True
    must_set_password: bool = False
    password_set_at: datetime | None = None
    created_at: datetime | None = None
