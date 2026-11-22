"""计划项 / 批量拖拽 / 导入 的请求与响应 schema。"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel

PlanType = Literal["place", "hotel", "transport", "activity", "note"]


class PlanItemCreate(BaseModel):
    day_id: str | None = None
    bucket: str = "main"
    type: PlanType = "place"
    title: str = Field(min_length=1, max_length=255)
    subtitle: str | None = None
    address: str | None = None
    category: str | None = None
    lng: float | None = None
    lat: float | None = None
    coord_system: str = "WGS84"
    start_time: datetime | None = None
    end_time: datetime | None = None
    duration_min: int | None = None
    note: str | None = None
    payload_json: str | None = None
    source: str = "manual"
    external_id: str | None = None
    # 前端可用 keyBetween 计算；不传时后端追加到末尾（非 fractional indexing）
    sort_key: str | None = None


class PlanItemUpdate(BaseModel):
    day_id: str | None = None
    bucket: str | None = None
    type: PlanType | None = None
    title: str | None = Field(default=None, min_length=1, max_length=255)
    subtitle: str | None = None
    address: str | None = None
    category: str | None = None
    lng: float | None = None
    lat: float | None = None
    coord_system: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    duration_min: int | None = None
    note: str | None = None
    payload_json: str | None = None
    source: str | None = None
    external_id: str | None = None
    sort_key: str | None = None


class PlanItemOut(ORMModel):
    id: str
    trip_id: str
    day_id: str | None = None
    bucket: str = "main"
    type: str = "place"
    title: str
    subtitle: str | None = None
    address: str | None = None
    category: str | None = None
    lng: float | None = None
    lat: float | None = None
    coord_system: str = "WGS84"
    start_time: datetime | None = None
    end_time: datetime | None = None
    duration_min: int | None = None
    note: str | None = None
    payload_json: str | None = None
    source: str = "manual"
    external_id: str | None = None
    sort_key: str
    created_by: str | None = None
    created_at: datetime | None = None


class MoveIn(BaseModel):
    """单条拖拽。new_sort_key 由前端 keyBetween 计算，后端仅做字典序校验。

    before_sort_key / after_sort_key 是目标位置相邻两项的键（None 表示到端点），
    只用于校验 before < new < after，不参与落库。
    """

    item_id: str
    to_day_id: str | None = None
    to_bucket: str = "main"
    new_sort_key: str = Field(min_length=1)
    before_sort_key: str | None = None
    after_sort_key: str | None = None


class MovesIn(BaseModel):
    moves: list[MoveIn] = Field(min_length=1)


class ImportIn(BaseModel):
    """前端解析文件/清单后提交结构化条目。"""

    items: list[PlanItemCreate] = Field(min_length=1)
