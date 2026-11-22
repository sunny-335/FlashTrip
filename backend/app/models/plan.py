"""三栏计划模型：PlanItem（day_id 为空即待规划池）与拖拽移动日志。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.security import new_id
from app.db.base import Base, SoftDeleteMixin, TimestampMixin


class PlanItem(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "plan_items"
    __table_args__ = (
        Index("ix_plan_items_trip_day_sort", "trip_id", "day_id", "sort_key"),
        Index("ix_plan_items_trip_bucket_sort", "trip_id", "bucket", "sort_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    trip_id: Mapped[str] = mapped_column(String(36), nullable=False)
    # NULL 表示待规划池（UnplannedPool）
    day_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    bucket: Mapped[str] = mapped_column(String(32), nullable=False, default="main")
    # place / hotel / transport / activity / note
    type: Mapped[str] = mapped_column(String(16), nullable=False, default="place")
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    subtitle: Mapped[str | None] = mapped_column(String(255), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    coord_system: Mapped[str] = mapped_column(String(16), nullable=False, default="WGS84")
    start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 扩展字段，JSON 字符串（Text 存储）
    payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="manual")
    external_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # 拖拽排序键：由前端 fractional indexing 计算，后端仅做字典序校验
    sort_key: Mapped[str] = mapped_column(String(128), nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)


class PlanMoveLog(Base, TimestampMixin, SoftDeleteMixin):
    """一次批量拖拽 = 一个 batch_id；undo 将整批还原到 before_*。"""

    __tablename__ = "plan_move_logs"
    __table_args__ = (
        Index("ix_plan_move_logs_trip_batch", "trip_id", "batch_id"),
        Index("ix_plan_move_logs_trip_undone", "trip_id", "undone_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    trip_id: Mapped[str] = mapped_column(String(36), nullable=False)
    item_id: Mapped[str] = mapped_column(String(36), nullable=False)
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    batch_id: Mapped[str] = mapped_column(String(36), nullable=False)
    # 移动前所在位置（undo 目标）
    before_day_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    before_sort_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # 移动后所在位置
    after_day_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    after_sort_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    undone_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
