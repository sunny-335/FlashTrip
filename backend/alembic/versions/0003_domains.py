"""M3–M6 领域表：业务 7 tab + 协作/权限/邀请 + 同步事件 + AI 会话/消息/审计。

仅使用 create_table / create_index，无任何 ALTER，天然兼容 SQLite（batch 亦无害）。
列定义与 app.models 下对应模型严格对齐（含 TimestampMixin / SoftDeleteMixin 三列）。

Revision ID: 0003_domains
Revises: 0002_plan
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0003_domains"
down_revision = "0002_plan"
branch_labels = None
depends_on = None

def _ts():
    """返回新的列对象列表（Column 不能跨 create_table 复用）。"""
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    ]


def upgrade() -> None:
    # ---- 业务域 ----
    op.create_table(
        "bookings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("trip_id", sa.String(36), nullable=False),
        sa.Column("plan_item_id", sa.String(36), nullable=True),
        sa.Column("type", sa.String(32), nullable=False),
        sa.Column("vendor", sa.String(128), nullable=True),
        sa.Column("booking_no", sa.String(128), nullable=True),
        sa.Column("holder", sa.String(128), nullable=True),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("currency", sa.String(8), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("attachment_id", sa.String(36), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        *_ts(),
    )
    op.create_index("ix_bookings_trip_id", "bookings", ["trip_id"], unique=False)

    op.create_table(
        "transports",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("trip_id", sa.String(36), nullable=False),
        sa.Column("plan_item_id", sa.String(36), nullable=True),
        sa.Column("mode", sa.String(32), nullable=False),
        sa.Column("from_name", sa.String(128), nullable=True),
        sa.Column("to_name", sa.String(128), nullable=True),
        sa.Column("from_lng", sa.Float(), nullable=True),
        sa.Column("from_lat", sa.Float(), nullable=True),
        sa.Column("to_lng", sa.Float(), nullable=True),
        sa.Column("to_lat", sa.Float(), nullable=True),
        sa.Column("coord_system", sa.String(16), nullable=False),
        sa.Column("depart_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("arrive_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("carrier", sa.String(128), nullable=True),
        sa.Column("seat", sa.String(64), nullable=True),
        sa.Column("price", sa.Numeric(12, 2), nullable=True),
        sa.Column("route_geojson", sa.Text(), nullable=True),
        sa.Column("sort_key", sa.Text(), nullable=False),
        *_ts(),
    )
    op.create_index("ix_transports_trip_id", "transports", ["trip_id"], unique=False)

    op.create_table(
        "expenses",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("trip_id", sa.String(36), nullable=False),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(8), nullable=False),
        sa.Column("exchange_rate", sa.Numeric(12, 4), nullable=True),
        sa.Column("paid_by", sa.String(36), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("split_json", sa.Text(), nullable=True),
        sa.Column("attachment_id", sa.String(36), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        *_ts(),
    )
    op.create_index("ix_expenses_trip_id", "expenses", ["trip_id"], unique=False)

    op.create_table(
        "packing_lists",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("trip_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("sort_key", sa.Text(), nullable=False),
        *_ts(),
    )
    op.create_index("ix_packing_lists_trip_id", "packing_lists", ["trip_id"], unique=False)

    op.create_table(
        "packing_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("list_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("qty", sa.Integer(), nullable=False),
        sa.Column("checked", sa.Boolean(), nullable=False),
        sa.Column("assignee_id", sa.String(36), nullable=True),
        sa.Column("sort_key", sa.Text(), nullable=False),
        *_ts(),
    )
    op.create_index("ix_packing_items_list_id", "packing_items", ["list_id"], unique=False)

    op.create_table(
        "moments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("trip_id", sa.String(36), nullable=False),
        sa.Column("day_id", sa.String(36), nullable=True),
        sa.Column("plan_item_id", sa.String(36), nullable=True),
        sa.Column("author_id", sa.String(36), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("mood", sa.String(32), nullable=True),
        sa.Column("lng", sa.Float(), nullable=True),
        sa.Column("lat", sa.Float(), nullable=True),
        sa.Column("coord_system", sa.String(16), nullable=False),
        sa.Column("taken_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("media_json", sa.Text(), nullable=True),
        *_ts(),
    )
    op.create_index("ix_moments_trip_id", "moments", ["trip_id"], unique=False)

    op.create_table(
        "attachments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("trip_id", sa.String(36), nullable=False),
        sa.Column("uploader_id", sa.String(36), nullable=True),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("storage_path", sa.String(512), nullable=False),
        sa.Column("mime", sa.String(128), nullable=True),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("checksum", sa.String(64), nullable=True),
        sa.Column("kind", sa.String(32), nullable=True),
        *_ts(),
    )
    op.create_index("ix_attachments_trip_id", "attachments", ["trip_id"], unique=False)

    # ---- 协作 / 权限 / 邀请 ----
    op.create_table(
        "trip_members",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("trip_id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("role", sa.String(24), nullable=False),
        sa.Column("invited_by", sa.String(36), nullable=True),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("trip_id", "user_id", name="uq_trip_members_trip_user"),
        *_ts(),
    )
    op.create_index("ix_trip_members_trip_id", "trip_members", ["trip_id"], unique=False)

    op.create_table(
        "permissions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("trip_member_id", sa.String(36), nullable=False),
        sa.Column("permission_key", sa.String(48), nullable=False),
        sa.Column("granted", sa.Boolean(), nullable=False),
        sa.Column("granted_by", sa.String(36), nullable=True),
        sa.UniqueConstraint("trip_member_id", "permission_key", name="uq_permissions_member_key"),
        *_ts(),
    )
    op.create_index("ix_permissions_member_id", "permissions", ["trip_member_id"], unique=False)

    op.create_table(
        "invitations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("trip_id", sa.String(36), nullable=False),
        # 只存 token hash，明文不入库
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("channel", sa.String(16), nullable=False),
        sa.Column("target_value", sa.String(256), nullable=False),
        sa.Column("permission_keys_json", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("max_uses", sa.Integer(), nullable=False),
        sa.Column("used_count", sa.Integer(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by", sa.String(36), nullable=True),
        sa.Column("created_by", sa.String(36), nullable=True),
        sa.UniqueConstraint("token_hash", name="uq_invitations_token_hash"),
        *_ts(),
    )
    op.create_index("ix_invitations_trip_id", "invitations", ["trip_id"], unique=False)

    # ---- 同步事件（自增整数 id 作为 SSE 补发游标）----
    op.create_table(
        "sync_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("trip_id", sa.String(36), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=True),
        sa.Column("actor_id", sa.String(36), nullable=True),
        *_ts(),
    )
    op.create_index("ix_sync_events_trip_id_id", "sync_events", ["trip_id", "id"], unique=False)

    # ---- AI 会话 / 消息 / 审计 ----
    op.create_table(
        "ai_conversations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("trip_id", sa.String(36), nullable=True),
        sa.Column("scope", sa.String(32), nullable=True),
        sa.Column("title", sa.String(256), nullable=True),
        sa.Column("context_json", sa.Text(), nullable=True),
        *_ts(),
    )
    op.create_index("ix_ai_conversations_user_id", "ai_conversations", ["user_id"], unique=False)
    op.create_index("ix_ai_conversations_trip_id", "ai_conversations", ["trip_id"], unique=False)

    op.create_table(
        "ai_messages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("conversation_id", sa.String(36), nullable=False),
        sa.Column("role", sa.String(24), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("tool_calls_json", sa.Text(), nullable=True),
        sa.Column("tool_call_id", sa.String(128), nullable=True),
        sa.Column("provider", sa.String(32), nullable=True),
        sa.Column("model", sa.String(128), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("cost", sa.Numeric(12, 6), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        *_ts(),
    )
    op.create_index("ix_ai_messages_conversation_id", "ai_messages", ["conversation_id"], unique=False)

    op.create_table(
        "ai_audit_logs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=True),
        sa.Column("trip_id", sa.String(36), nullable=True),
        sa.Column("provider", sa.String(32), nullable=True),
        sa.Column("model", sa.String(128), nullable=True),
        sa.Column("action", sa.String(48), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        *_ts(),
    )
    op.create_index("ix_ai_audit_logs_user_id", "ai_audit_logs", ["user_id"], unique=False)
    op.create_index("ix_ai_audit_logs_trip_id", "ai_audit_logs", ["trip_id"], unique=False)


def downgrade() -> None:
    # 反向顺序 drop；索引由数据库随表一并删除（SQLite / PG 均如此）
    for table in (
        "ai_audit_logs", "ai_messages", "ai_conversations",
        "sync_events",
        "invitations", "permissions", "trip_members",
        "attachments", "moments", "packing_items", "packing_lists",
        "expenses", "transports", "bookings",
    ):
        op.drop_table(table)
