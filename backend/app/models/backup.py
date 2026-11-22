"""备份记录：手动 / 定时 / 导入快照的落盘审计。"""
from __future__ import annotations

from sqlalchemy import Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.security import new_id
from app.db.base import Base, SoftDeleteMixin, TimestampMixin


class BackupRecord(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "backup_records"
    __table_args__ = (Index("ix_backup_records_created_at", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    filename: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # manual / scheduled / import
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="manual")
    # ok / failed
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ok")
    checksum: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    storage_path: Mapped[str] = mapped_column(String(512), nullable=False, default="")
