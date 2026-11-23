"""0006 预算 / 家庭 / 常用人员 / 行程参与人 / 对象存储后端标记。

新增：
- trips.total_budget：行程总预算；
- budget_categories：分类预算（trip_id+category 唯一）；
- households / household_members / frequent_travelers：家庭与常用人员库；
- trip_participants：行程参与人（快速选人结果，供费用分账复用）；
- attachments.backend：存储后端标记（local/oss/s3）。

仅使用 add_column / create_table / create_index，downgrade 用 batch_alter_table 删列，
SQLite 与 PostgreSQL 双兼容；列名与 app.models 严格对齐。

Revision ID: 0006_budget_people
Revises: 0005_extended
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006_budget_people"
down_revision = "0005_extended"
branch_labels = None
depends_on = None


def _ts() -> list[sa.Column]:
    """时间戳 + 软删三列（与 TimestampMixin / SoftDeleteMixin 对齐）。"""
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    ]


def upgrade() -> None:
    # ---- trips：总预算 ----
    op.add_column("trips", sa.Column("total_budget", sa.Numeric(14, 2), nullable=True))

    # ---- attachments：存储后端标记，已有附件全部视为 local ----
    op.add_column(
        "attachments",
        sa.Column("backend", sa.String(length=16), nullable=False, server_default=sa.text("'local'")),
    )

    # ---- budget_categories：分类预算 ----
    op.create_table(
        "budget_categories",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("trip_id", sa.String(36), nullable=False),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False, server_default=sa.text("0")),
        sa.Column("note", sa.Text(), nullable=True),
        *_ts(),
        sa.UniqueConstraint("trip_id", "category", name="uq_budget_categories_trip_category"),
    )
    op.create_index("ix_budget_categories_trip_id", "budget_categories", ["trip_id"], unique=False)

    # ---- households：家庭 ----
    op.create_table(
        "households",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        *_ts(),
    )
    op.create_index("ix_households_owner_id", "households", ["owner_id"], unique=False)

    # ---- household_members：家庭成员（可标记儿童、可关联来源常用人员）----
    op.create_table(
        "household_members",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("household_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("is_child", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("frequent_traveler_id", sa.String(36), nullable=True),
        *_ts(),
    )
    op.create_index("ix_household_members_household", "household_members", ["household_id"], unique=False)
    op.create_index(
        "ix_household_members_frequent", "household_members", ["frequent_traveler_id"], unique=False
    )

    # ---- frequent_travelers：常用人员库 ----
    op.create_table(
        "frequent_travelers",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        *_ts(),
    )
    op.create_index("ix_frequent_travelers_owner_id", "frequent_travelers", ["owner_id"], unique=False)

    # ---- trip_participants：行程参与人 ----
    op.create_table(
        "trip_participants",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("trip_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("is_child", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("family", sa.String(64), nullable=False, server_default=sa.text("''")),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("source_type", sa.String(16), nullable=False, server_default=sa.text("'manual'")),
        sa.Column("source_id", sa.String(36), nullable=True),
        *_ts(),
    )
    op.create_index("ix_trip_participants_trip", "trip_participants", ["trip_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_trip_participants_trip", table_name="trip_participants")
    op.drop_table("trip_participants")
    op.drop_index("ix_frequent_travelers_owner_id", table_name="frequent_travelers")
    op.drop_table("frequent_travelers")
    op.drop_index("ix_household_members_frequent", table_name="household_members")
    op.drop_index("ix_household_members_household", table_name="household_members")
    op.drop_table("household_members")
    op.drop_index("ix_households_owner_id", table_name="households")
    op.drop_table("households")
    op.drop_index("ix_budget_categories_trip_id", table_name="budget_categories")
    op.drop_table("budget_categories")

    with op.batch_alter_table("attachments") as batch_op:
        batch_op.drop_column("backend")
    with op.batch_alter_table("trips") as batch_op:
        batch_op.drop_column("total_budget")
