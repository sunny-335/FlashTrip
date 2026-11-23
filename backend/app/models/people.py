"""家庭 / 家庭成员 / 常用人员 / 行程参与人模型。

- Household：用户级家庭实体（owner_id 逻辑关联 users）；
- HouseholdMember：家庭成员，可直接添加，也可由常用人员「一键加入」（frequent_traveler_id 记录来源）；
- FrequentTraveler：用户级常用人员库，可复用、可加入任意家庭；
- TripParticipant：行程级参与人，支持从常用人员或家庭快速带入多人，并供费用分账复用。

全部沿用项目约定：String(36) 主键 + TimestampMixin + SoftDeleteMixin，trip_id / owner_id 不做物理外键。
"""
from __future__ import annotations

from sqlalchemy import Boolean, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.security import new_id
from app.db.base import Base, SoftDeleteMixin, TimestampMixin


class Household(Base, TimestampMixin, SoftDeleteMixin):
    """家庭：名称 + 成员列表，成员单独成表便于增删。"""

    __tablename__ = "households"
    __table_args__ = (Index("ix_households_owner_id", "owner_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(String(36), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class HouseholdMember(Base, TimestampMixin, SoftDeleteMixin):
    """家庭成员：姓名 / 是否儿童 / 备注，可选关联来源常用人员。"""

    __tablename__ = "household_members"
    __table_args__ = (
        Index("ix_household_members_household", "household_id"),
        Index("ix_household_members_frequent", "frequent_traveler_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    household_id: Mapped[str] = mapped_column(String(36), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    is_child: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 由常用人员加入时记录来源，便于展示「来自常用人员」；直接添加为 NULL
    frequent_traveler_id: Mapped[str | None] = mapped_column(String(36), nullable=True)


class FrequentTraveler(Base, TimestampMixin, SoftDeleteMixin):
    """常用人员库：独立于家庭，可被反复选中加入家庭或行程。"""

    __tablename__ = "frequent_travelers"
    __table_args__ = (Index("ix_frequent_travelers_owner_id", "owner_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(String(36), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class TripParticipant(Base, TimestampMixin, SoftDeleteMixin):
    """行程参与人：快速选人结果落库，费用分账可直接复用其 id/name/is_child。"""

    __tablename__ = "trip_participants"
    __table_args__ = (Index("ix_trip_participants_trip", "trip_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    trip_id: Mapped[str] = mapped_column(String(36), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    is_child: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # 分账「按家庭分摊」使用的家庭分组名，缺省为空串
    family: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # manual / frequent / household：记录快速带入来源
    source_type: Mapped[str] = mapped_column(String(16), nullable=False, default="manual")
    source_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
