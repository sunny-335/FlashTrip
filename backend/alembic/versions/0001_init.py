"""0001 init：用户 / 安装状态 / 配置镜像 / AI 与地图供应商 / 用户偏好。

Revision ID: 0001_init
Revises: None
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001_init"
down_revision = None
branch_labels = None
depends_on = None


def _ts_columns() -> list[sa.Column]:
    """TimestampMixin + SoftDeleteMixin 的三列（默认由 ORM 侧提供，故不设 server_default）。"""
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    ]


def upgrade() -> None:
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())

    # app_config 可能已被 ConfigStore 的裸 SQL 预建（安装时先写 config.json 再迁移），
    # 因此仅在不存在时创建，避免 "table already exists"。列结构与该裸 SQL 完全一致。
    if "app_config" not in existing:
        op.create_table(
            "app_config",
            sa.Column("key", sa.String(length=64), nullable=False),
            sa.Column("value_plain", sa.Text(), nullable=True),
            sa.Column("value_enc", sa.Text(), nullable=True),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=True,
            ),
            sa.PrimaryKeyConstraint("key"),
        )

    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=False),
        sa.Column("avatar_url", sa.Text(), nullable=True),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("must_set_password", sa.Boolean(), nullable=False),
        sa.Column("password_set_at", sa.DateTime(timezone=True), nullable=True),
        *_ts_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username", name="uq_users_username"),
        sa.UniqueConstraint("email", name="uq_users_email"),
        sa.UniqueConstraint("phone", name="uq_users_phone"),
    )
    op.create_index("ix_users_role_active", "users", ["role", "is_active"], unique=False)

    op.create_table(
        "install_state",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("installed", sa.Boolean(), nullable=False),
        sa.Column("schema_version", sa.String(length=32), nullable=False),
        sa.Column("install_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("unlocked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("unlock_actor_id", sa.String(length=36), nullable=True),
        *_ts_columns(),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "ai_provider_configs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("provider_id", sa.String(length=64), nullable=False),
        sa.Column("base_url", sa.Text(), nullable=False),
        sa.Column("api_key_enc", sa.Text(), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("timeout_s", sa.Integer(), nullable=False),
        sa.Column("supports_stream", sa.Boolean(), nullable=False),
        *_ts_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider_id", name="uq_ai_provider_configs_provider_id"),
    )
    op.create_index(
        "ix_ai_provider_enabled_priority",
        "ai_provider_configs",
        ["enabled", "priority"],
        unique=False,
    )

    op.create_table(
        "map_provider_configs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("provider_id", sa.String(length=64), nullable=False),
        sa.Column("key_enc", sa.Text(), nullable=False),
        sa.Column("style_url", sa.Text(), nullable=False),
        sa.Column("tile_url_template", sa.Text(), nullable=False),
        sa.Column("default_style", sa.String(length=128), nullable=False),
        sa.Column("coord_system", sa.String(length=16), nullable=False),
        sa.Column("attribution", sa.Text(), nullable=False),
        sa.Column("audit_number", sa.String(length=128), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("needs_token", sa.Boolean(), nullable=False),
        *_ts_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider_id", name="uq_map_provider_configs_provider_id"),
    )
    op.create_index(
        "ix_map_provider_enabled",
        "map_provider_configs",
        ["enabled", "provider_id"],
        unique=False,
    )

    op.create_table(
        "user_preferences",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("current_trip_id", sa.String(length=36), nullable=True),
        sa.Column("theme", sa.String(length=16), nullable=False),
        sa.Column("default_map_provider_id", sa.String(length=64), nullable=False),
        sa.Column("ai_tools_enabled", sa.Boolean(), nullable=False),
        *_ts_columns(),
        sa.PrimaryKeyConstraint("user_id"),
    )


def downgrade() -> None:
    op.drop_table("user_preferences")
    op.drop_index("ix_map_provider_enabled", table_name="map_provider_configs")
    op.drop_table("map_provider_configs")
    op.drop_index("ix_ai_provider_enabled_priority", table_name="ai_provider_configs")
    op.drop_table("ai_provider_configs")
    op.drop_table("install_state")
    op.drop_index("ix_users_role_active", table_name="users")
    op.drop_table("users")
    # app_config 可能由 ConfigStore 预建，downgrade 到 base 时一并清理
    bind = op.get_bind()
    if "app_config" in set(sa.inspect(bind).get_table_names()):
        op.drop_table("app_config")
