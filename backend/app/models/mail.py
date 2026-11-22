"""邮件发送日志：成功/失败均留痕，供临近行程天气提醒按 trip_id 去重。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.security import new_id
from app.db.base import Base, SoftDeleteMixin, TimestampMixin


class MailLog(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "mail_logs"
    __table_args__ = (Index("ix_mail_logs_trip_id", "trip_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    to_addr: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    subject: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    template: Mapped[str] = mapped_column(String(64), nullable=False, default="generic")
    # sent / failed
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="sent")
    # 仅记录异常类型名，绝不写入含密钥/口令的原文
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    trip_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
