"""附件：物理文件落在 data_dir()/uploads，DB 只登记元数据。"""
from __future__ import annotations

from sqlalchemy import Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.security import new_id
from app.db.base import Base, SoftDeleteMixin, TimestampMixin


class Attachment(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "attachments"
    __table_args__ = (Index("ix_attachments_trip_id", "trip_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    trip_id: Mapped[str] = mapped_column(String(36), nullable=False)
    uploader_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(512), nullable=False)
    mime: Mapped[str | None] = mapped_column(String(128), nullable=True)
    size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)
    kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # 存储后端：local（默认）/ oss / s3；对象存储时 storage_path 存对象键（object key）
    backend: Mapped[str] = mapped_column(String(16), nullable=False, default="local")
