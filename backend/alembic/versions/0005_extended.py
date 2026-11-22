"""0005 extended：公开分享、邮件日志、备份记录、天气缓存 + 业务扩展列。

仅使用 add_column / create_table / create_index，不做任何列类型变更；
downgrade 借助 op.batch_alter_table 逐列删除，兼容 SQLite 与 PostgreSQL。
列名与 app.models 新增字段严格对齐，供多个并行领域模型共用。

Revision ID: 0005_extended
Revises: 0004_extended
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005_extended"
down_revision = "0004_extended"
branch_labels = None
depends_on = None


def _ts():
    """返回新的时间戳/软删列对象列表（Column 不能跨 create_table 复用）。"""
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    ]


def upgrade() -> None:
    # ---- 新增列：add_column + server_default，SQLite 友好 ----
    op.add_column(
        "moments",
        sa.Column("is_public", sa.Boolean(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column("trip_members", sa.Column("nickname", sa.String(length=64), nullable=True))
    op.add_column("trip_members", sa.Column("email", sa.String(length=128), nullable=True))
    op.add_column(
        "invitations",
        sa.Column("force_reset", sa.Boolean(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "user_preferences",
        sa.Column("moment_default_public", sa.Boolean(), nullable=False, server_default=sa.text("0")),
    )

    # ---- share_links：明文 token 不入库，仅存 sha256(token) ----
    op.create_table(
        "share_links",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("trip_id", sa.String(36), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("title", sa.String(255), nullable=False, server_default=sa.text("''")),
        sa.Column("include_transports", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("include_bookings", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("include_packing", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("include_expenses", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("include_moments", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(36), nullable=True),
        sa.Column("view_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.UniqueConstraint("token_hash", name="uq_share_links_token_hash"),
        *_ts(),
    )
    op.create_index("ix_share_links_trip_id", "share_links", ["trip_id"], unique=False)

    # ---- mail_logs：每次发送留痕，供临近行程提醒去重 ----
    op.create_table(
        "mail_logs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("to_addr", sa.String(255), nullable=False, server_default=sa.text("''")),
        sa.Column("subject", sa.String(255), nullable=False, server_default=sa.text("''")),
        sa.Column("template", sa.String(64), nullable=False, server_default=sa.text("'generic'")),
        sa.Column("status", sa.String(16), nullable=False, server_default=sa.text("'sent'")),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("trip_id", sa.String(36), nullable=True),
        sa.Column("created_by", sa.String(36), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        *_ts(),
    )
    op.create_index("ix_mail_logs_trip_id", "mail_logs", ["trip_id"], unique=False)

    # ---- backup_records：导出/导入/定时备份审计 ----
    op.create_table(
        "backup_records",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("filename", sa.String(255), nullable=False, server_default=sa.text("''")),
        sa.Column("size", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("kind", sa.String(16), nullable=False, server_default=sa.text("'manual'")),
        sa.Column("status", sa.String(16), nullable=False, server_default=sa.text("'ok'")),
        sa.Column("checksum", sa.String(64), nullable=False, server_default=sa.text("''")),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("storage_path", sa.String(512), nullable=False, server_default=sa.text("''")),
        *_ts(),
    )
    op.create_index("ix_backup_records_created_at", "backup_records", ["created_at"], unique=False)

    # ---- weather_cache：按 provider+city+days 缓存归一化结果 ----
    op.create_table(
        "weather_cache",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("cache_key", sa.String(128), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False, server_default=sa.text("''")),
        sa.Column("payload_json", sa.Text(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("cache_key", name="uq_weather_cache_key"),
        *_ts(),
    )
    op.create_index("ix_weather_cache_expires_at", "weather_cache", ["expires_at"], unique=False)


def downgrade() -> None:
    # 先删新表（索引随表一并删除），再逐表批量删列
    op.drop_table("weather_cache")
    op.drop_table("backup_records")
    op.drop_table("mail_logs")
    op.drop_table("share_links")

    with op.batch_alter_table("moments") as batch_op:
        batch_op.drop_column("is_public")
    with op.batch_alter_table("trip_members") as batch_op:
        batch_op.drop_column("email")
        batch_op.drop_column("nickname")
    with op.batch_alter_table("invitations") as batch_op:
        batch_op.drop_column("force_reset")
    with op.batch_alter_table("user_preferences") as batch_op:
        batch_op.drop_column("moment_default_public")
