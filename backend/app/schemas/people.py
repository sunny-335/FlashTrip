"""家庭 / 常用人员 / 行程参与人的请求与响应 schema。"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


# ---------------------------------------------------------------- 家庭成员

class HouseholdMemberCreate(BaseModel):
    """添加家庭成员：可直接填姓名，也可用 frequent_traveler_id 从常用人员带入。"""

    name: str | None = Field(default=None, max_length=128)
    is_child: bool = False
    note: str | None = None
    frequent_traveler_id: str | None = None


class HouseholdMemberUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    is_child: bool | None = None
    note: str | None = None


class HouseholdMemberOut(ORMModel):
    id: str
    household_id: str
    name: str
    is_child: bool = False
    note: str | None = None
    frequent_traveler_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


# ---------------------------------------------------------------- 家庭

class HouseholdCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    note: str | None = None
    members: list[HouseholdMemberCreate] | None = None


class HouseholdUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    note: str | None = None


class HouseholdOut(ORMModel):
    id: str
    owner_id: str
    name: str
    note: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


# ---------------------------------------------------------------- 常用人员

class FrequentTravelerCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    note: str | None = None


class FrequentTravelerUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    note: str | None = None


class FrequentTravelerOut(ORMModel):
    id: str
    owner_id: str
    name: str
    note: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


# ---------------------------------------------------------------- 行程参与人

class TripParticipantIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    is_child: bool = False
    family: str = Field(default="", max_length=64)
    note: str | None = None


class TripParticipantsIn(BaseModel):
    participants: list[TripParticipantIn] = Field(min_length=1)


class TripParticipantQuickAddIn(BaseModel):
    """快速选人：按常用人员 / 家庭批量带入，二者可同时提交。"""

    frequent_traveler_ids: list[str] | None = None
    household_ids: list[str] | None = None


class TripParticipantOut(ORMModel):
    id: str
    trip_id: str
    name: str
    is_child: bool = False
    family: str = ""
    note: str | None = None
    source_type: str = "manual"
    source_id: str | None = None
    created_at: datetime | None = None
