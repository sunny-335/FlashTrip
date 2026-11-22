"""运行期配置模型：安装状态、配置镜像、AI/地图供应商、用户偏好。

注意：config.json 为权威源；本文件是 DB 侧镜像/落点。AppConfig 刻意不使用
TimestampMixin，以便与 config_store 的裸 SQL（CREATE TABLE IF NOT EXISTS app_config）
列结构完全一致；*_enc 列一律存 encrypt() 密文，绝不落明文。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.security import new_id
from app.db.base import Base, SoftDeleteMixin, TimestampMixin


class InstallState(Base, TimestampMixin, SoftDeleteMixin):
    """安装状态单例（id 固定为 1），与 /data/.installed 标记双写。"""

    __tablename__ = "install_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    installed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    install_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    unlocked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    unlock_actor_id: Mapped[str | None] = mapped_column(String(36), nullable=True)


class AppConfig(Base):
    """config.json 的 DB 镜像/审计落点。列结构须与 config_store 裸 SQL 保持一致。"""

    __tablename__ = "app_config"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value_plain: Mapped[str | None] = mapped_column(Text, nullable=True)
    value_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, server_default=func.now(), onupdate=func.now()
    )


class AiProviderConfig(Base, TimestampMixin, SoftDeleteMixin):
    """AI 供应商：模型名动态来自 /models，绝不硬编码。"""

    __tablename__ = "ai_provider_configs"
    __table_args__ = (Index("ix_ai_provider_enabled_priority", "enabled", "priority"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    provider_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    base_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    api_key_enc: Mapped[str] = mapped_column(Text, nullable=False, default="")
    model: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    timeout_s: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    supports_stream: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class MapProviderConfig(Base, TimestampMixin, SoftDeleteMixin):
    """地图供应商：审图号/合规文案与坐标系标记。"""

    __tablename__ = "map_provider_configs"
    __table_args__ = (Index("ix_map_provider_enabled", "enabled", "provider_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    provider_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    key_enc: Mapped[str] = mapped_column(Text, nullable=False, default="")
    style_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tile_url_template: Mapped[str] = mapped_column(Text, nullable=False, default="")
    default_style: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    coord_system: Mapped[str] = mapped_column(String(16), nullable=False, default="WGS84")
    attribution: Mapped[str] = mapped_column(Text, nullable=False, default="")
    audit_number: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    needs_token: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class UserPreferences(Base, TimestampMixin, SoftDeleteMixin):
    """用户偏好：当前行程、主题、默认底图、AI 工具总开关。"""

    __tablename__ = "user_preferences"

    user_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    current_trip_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # 主题保持 String 存储，值域固定为 light / dark / system（跟随系统）
    theme: Mapped[str] = mapped_column(String(16), nullable=False, default="light")
    default_map_provider_id: Mapped[str] = mapped_column(String(64), nullable=False, default="openfreemap")
    ai_tools_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # 新建旅途瞬间是否默认公开（仅影响公开分享可见性，不改变私有属性）
    moment_default_public: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
