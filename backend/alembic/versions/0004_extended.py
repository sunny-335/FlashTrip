"""0004 extended：行程人群/家庭模式、预订与交通按天归集、费用分账扩展。

仅使用 add_column + create_index，不做任何列类型变更，SQLite 与 PostgreSQL 均兼容。
列名与上游 app.models 新增字段严格对齐，供多个并行领域模型共用。

Revision ID: 0004_extended
Revises: 0003_domains
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004_extended"
down_revision = "0003_domains"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---- trips：出行人群与家庭模式 ----
    op.add_column(
        "trips",
        sa.Column("traveler_count", sa.Integer(), nullable=False, server_default=sa.text("1")),
    )
    op.add_column(
        "trips",
        sa.Column("has_children", sa.Boolean(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "trips",
        sa.Column("children_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "trips",
        sa.Column("family_mode", sa.Boolean(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column("trips", sa.Column("family_name", sa.String(length=128), nullable=True))

    # ---- bookings：按行程日归集 ----
    op.add_column("bookings", sa.Column("day_id", sa.String(length=36), nullable=True))
    op.create_index("ix_bookings_trip_day", "bookings", ["trip_id", "day_id"], unique=False)

    # ---- transports：按行程日归集 ----
    op.add_column("transports", sa.Column("day_id", sa.String(length=36), nullable=True))
    op.create_index("ix_transports_trip_day", "transports", ["trip_id", "day_id"], unique=False)

    # ---- expenses：关联计划项 / 行程日 + 分账模式 ----
    op.add_column("expenses", sa.Column("day_id", sa.String(length=36), nullable=True))
    op.add_column("expenses", sa.Column("plan_item_id", sa.String(length=36), nullable=True))
    op.add_column(
        "expenses",
        sa.Column(
            "split_mode",
            sa.String(length=24),
            nullable=False,
            server_default=sa.text("'equal'"),
        ),
    )
    op.add_column("expenses", sa.Column("split_detail_json", sa.Text(), nullable=True))


def downgrade() -> None:
    # 先删索引，再逐列删除；SQLite 需借助 batch_alter_table 重建表
    op.drop_index("ix_bookings_trip_day", table_name="bookings")
    op.drop_index("ix_transports_trip_day", table_name="transports")

    with op.batch_alter_table("trips") as batch_op:
        batch_op.drop_column("family_name")
        batch_op.drop_column("family_mode")
        batch_op.drop_column("children_count")
        batch_op.drop_column("has_children")
        batch_op.drop_column("traveler_count")

    with op.batch_alter_table("bookings") as batch_op:
        batch_op.drop_column("day_id")

    with op.batch_alter_table("transports") as batch_op:
        batch_op.drop_column("day_id")

    with op.batch_alter_table("expenses") as batch_op:
        batch_op.drop_column("split_detail_json")
        batch_op.drop_column("split_mode")
        batch_op.drop_column("plan_item_id")
        batch_op.drop_column("day_id")
