"""行李清单：清单 -> 条目一对多，用 sort_key 维持展示顺序。"""
from __future__ import annotations

from sqlalchemy import Boolean, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.security import new_id
from app.db.base import Base, SoftDeleteMixin, TimestampMixin


class PackingList(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "packing_lists"
    __table_args__ = (Index("ix_packing_lists_trip_id", "trip_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    trip_id: Mapped[str] = mapped_column(String(36), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False, default="默认清单")
    sort_key: Mapped[str] = mapped_column(Text, nullable=False, default="")


class PackingItem(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "packing_items"
    __table_args__ = (Index("ix_packing_items_list_id", "list_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    list_id: Mapped[str] = mapped_column(String(36), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    qty: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    checked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    assignee_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    sort_key: Mapped[str] = mapped_column(Text, nullable=False, default="")
