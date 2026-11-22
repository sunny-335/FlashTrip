"""行程 / 行程日 请求与响应 schema。"""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel

# 字段名叫 `date` 会遮蔽同名类型；用别名供这些类的注解求值使用。
Date = date

TripStatus = Literal["planned", "ongoing", "completed", "archived"]


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
