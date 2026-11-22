"""0002 plan：行程 / 行程日 / 计划项 / 拖拽移动日志 + 索引。

Revision ID: 0002_plan
Revises: 0001_init
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002_plan"
down_revision = "0001_init"
branch_labels = None
depends_on = None


def _ts_columns() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    ]


def upgrade() -> None:
    op.create_table(
        "trips",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("destination", sa.String(length=255), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("cover_url", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("visibility", sa.String(length=16), nullable=False),
        *_ts_columns(),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_trips_owner_status_start_date",
        "trips",
        ["owner_id", "status", "start_date"],
        unique=False,
    )

    op.create_table(
        "trip_days",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("trip_id", sa.String(length=36), nullable=False),
        sa.Column("day_index", sa.Integer(), nullable=False),
        sa.Column("date", sa.Date(), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("weather_json", sa.Text(), nullable=True),
        sa.Column("collapsed", sa.Boolean(), nullable=False),
        sa.Column("sort_key", sa.String(length=128), nullable=False),
        *_ts_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("trip_id", "day_index", name="uq_trip_days_trip_day"),
    )
    op.create_index("ix_trip_days_trip_sort", "trip_days", ["trip_id", "sort_key"], unique=False)

    op.create_table(
        "plan_items",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("trip_id", sa.String(length=36), nullable=False),
        sa.Column("day_id", sa.String(length=36), nullable=True),
        sa.Column("bucket", sa.String(length=32), nullable=False),
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("subtitle", sa.String(length=255), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("category", sa.String(length=64), nullable=True),
        sa.Column("lng", sa.Float(), nullable=True),
        sa.Column("lat", sa.Float(), nullable=True),
        sa.Column("coord_system", sa.String(length=16), nullable=False),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_min", sa.Integer(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("payload_json", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("external_id", sa.String(length=128), nullable=True),
        sa.Column("sort_key", sa.String(length=128), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=True),
        *_ts_columns(),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_plan_items_trip_day_sort",
        "plan_items",
        ["trip_id", "day_id", "sort_key"],
        unique=False,
    )
    op.create_index(
        "ix_plan_items_trip_bucket_sort",
        "plan_items",
        ["trip_id", "bucket", "sort_key"],
        unique=False,
    )

    op.create_table(
        "plan_move_logs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("trip_id", sa.String(length=36), nullable=False),
        sa.Column("item_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=True),
        sa.Column("batch_id", sa.String(length=36), nullable=False),
        sa.Column("before_day_id", sa.String(length=36), nullable=True),
        sa.Column("before_sort_key", sa.String(length=128), nullable=True),
        sa.Column("after_day_id", sa.String(length=36), nullable=True),
        sa.Column("after_sort_key", sa.String(length=128), nullable=True),
        sa.Column("undone_at", sa.DateTime(timezone=True), nullable=True),
        *_ts_columns(),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_plan_move_logs_trip_batch",
        "plan_move_logs",
        ["trip_id", "batch_id"],
        unique=False,
    )
    op.create_index(
        "ix_plan_move_logs_trip_undone",
        "plan_move_logs",
        ["trip_id", "undone_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_plan_move_logs_trip_undone", table_name="plan_move_logs")
    op.drop_index("ix_plan_move_logs_trip_batch", table_name="plan_move_logs")
    op.drop_table("plan_move_logs")
    op.drop_index("ix_plan_items_trip_bucket_sort", table_name="plan_items")
    op.drop_index("ix_plan_items_trip_day_sort", table_name="plan_items")
    op.drop_table("plan_items")
    op.drop_index("ix_trip_days_trip_sort", table_name="trip_days")
    op.drop_table("trip_days")
    op.drop_index("ix_trips_owner_status_start_date", table_name="trips")
    op.drop_table("trips")
