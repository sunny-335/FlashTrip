"""行程 / 行程日 请求与响应 schema。"""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.core.errors import AppError, ErrorCode
from app.schemas.common import ORMModel

# 字段名叫 `date` 会遮蔽同名类型；用别名供这些类的注解求值使用。
Date = date

TripStatus = Literal["planned", "ongoing", "completed", "archived"]


def normalize_people(traveler_count: int, has_children: bool, children_count: int) -> tuple[int, int]:
    """校验并规范化出行人群，返回 (traveler_count, children_count)。

    规则：
      - 出行人数不得少于 1 人；
      - 携带儿童时：1 <= 儿童人数 < 出行总人数；
      - 未携带儿童时：儿童人数强制归零。
    违反任一规则抛 AppError(VALIDATION) 并携带中文消息，供 API 层统一返回。
    """
    try:
        tc = int(traveler_count)
        cc = int(children_count or 0)
    except (TypeError, ValueError):
        raise AppError(ErrorCode.VALIDATION, "出行人数格式不正确") from None
    if tc < 1:
        raise AppError(ErrorCode.VALIDATION, "出行人数不得少于 1 人")
    if bool(has_children):
        if cc < 1:
            raise AppError(ErrorCode.VALIDATION, "携带儿童时儿童人数至少为 1")
        if cc >= tc:
            raise AppError(ErrorCode.VALIDATION, "儿童人数必须小于出行总人数")
        return tc, cc
    return tc, 0


class TripCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    destination: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    cover_url: str | None = None
    status: TripStatus = "planned"
    timezone: str = "Asia/Shanghai"
    currency: str = "CNY"
    visibility: str = "private"
    # 出行人群 / 家庭模式
    traveler_count: int = 1
    has_children: bool = False
    children_count: int = 0
    family_mode: bool = False
    family_name: str | None = Field(default=None, max_length=128)


class TripUpdate(BaseModel):
    """仅提交需要变更的字段（用 exclude_unset 落库）。"""

    title: str | None = Field(default=None, min_length=1, max_length=255)
    destination: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    cover_url: str | None = None
    status: TripStatus | None = None
    timezone: str | None = None
    currency: str | None = None
    visibility: str | None = None
    traveler_count: int | None = None
    has_children: bool | None = None
    children_count: int | None = None
    family_mode: bool | None = None
    family_name: str | None = Field(default=None, max_length=128)


class TripOut(ORMModel):
    id: str
    owner_id: str
    title: str
    destination: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    cover_url: str | None = None
    status: str = "planned"
    timezone: str = "Asia/Shanghai"
    currency: str = "CNY"
    visibility: str = "private"
    traveler_count: int = 1
    has_children: bool = False
    children_count: int = 0
    family_mode: bool = False
    family_name: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class TripDayCreate(BaseModel):
    day_index: int | None = None
    # 字段名 `date` 会遮蔽 `from datetime import date` 的类型名，
    # 在 `from __future__ import annotations` 下 Pydantic 求值会变成 `None | None`，
    # 因此这里显式使用别名 `Date`。
    date: Date | None = None
    title: str | None = None
    note: str | None = None
    weather_json: str | None = None
    collapsed: bool = False
    sort_key: str | None = None


class TripDayUpdate(BaseModel):
    day_index: int | None = None
    date: Date | None = None
    title: str | None = None
    note: str | None = None
    weather_json: str | None = None
    collapsed: bool | None = None
    sort_key: str | None = None


class TripDayOut(ORMModel):
    id: str
    trip_id: str
    day_index: int
    date: Date | None = None
    title: str | None = None
    note: str | None = None
    weather_json: str | None = None
    collapsed: bool = False
    sort_key: str = ""
    created_at: datetime | None = None
