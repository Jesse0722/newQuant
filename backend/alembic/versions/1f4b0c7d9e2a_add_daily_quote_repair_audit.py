"""add daily quote repair audit tables

Revision ID: 1f4b0c7d9e2a
Revises: c4647a9160ea
Create Date: 2026-11-04
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "1f4b0c7d9e2a"
down_revision = "c4647a9160ea"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "daily_quote_repair_batch",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("plan_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("database_identity", sa.JSON(), nullable=False),
        sa.Column("policy", sa.JSON(), nullable=False),
        sa.Column("backup_manifest", sa.JSON(), nullable=True),
        sa.Column("summary", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("applied_at", sa.DateTime(), nullable=True),
        sa.Column("rolled_back_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "plan_hash",
            name="uq_daily_quote_repair_batch_plan_hash",
        ),
    )
    op.create_table(
        "daily_quote_repair_audit",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("batch_id", sa.String(length=36), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("ts_code", sa.String(length=16), nullable=False),
        sa.Column("trade_date", sa.String(length=8), nullable=False),
        sa.Column("operation", sa.String(length=16), nullable=False),
        sa.Column("old_values", sa.JSON(), nullable=True),
        sa.Column("new_values", sa.JSON(), nullable=False),
        sa.Column("changed_fields", sa.JSON(), nullable=False),
        sa.Column("old_hash", sa.String(length=64), nullable=True),
        sa.Column("new_hash", sa.String(length=64), nullable=False),
        sa.Column("source_json", sa.JSON(), nullable=False),
        sa.Column("applied_at", sa.DateTime(), nullable=False),
        sa.Column("rolled_back_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "operation IN ('insert', 'update')",
            name="ck_daily_quote_repair_audit_operation",
        ),
        sa.ForeignKeyConstraint(
            ["batch_id"],
            ["daily_quote_repair_batch.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "batch_id",
            "ts_code",
            "trade_date",
            name="uq_daily_quote_repair_audit_batch_quote",
        ),
    )
    op.create_index(
        "ix_daily_quote_repair_audit_batch_sequence",
        "daily_quote_repair_audit",
        ["batch_id", "sequence"],
        unique=False,
    )
    op.create_index(
        "ix_daily_quote_repair_audit_quote",
        "daily_quote_repair_audit",
        ["ts_code", "trade_date"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_daily_quote_repair_audit_quote",
        table_name="daily_quote_repair_audit",
    )
    op.drop_index(
        "ix_daily_quote_repair_audit_batch_sequence",
        table_name="daily_quote_repair_audit",
    )
    op.drop_table("daily_quote_repair_audit")
    op.drop_table("daily_quote_repair_batch")
