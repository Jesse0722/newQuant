"""Persist task lifecycle, scheduler claims and report input/output audit.

Revision ID: 3b2f8da1c422
Revises: 2a1e7c90b311
"""
from alembic import op
import sqlalchemy as sa

revision = "3b2f8da1c422"
down_revision = "2a1e7c90b311"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    columns = {c["name"] for c in sa.inspect(bind).get_columns("industry_daily_report")}
    for column in (sa.Column("input_snapshot", sa.JSON()), sa.Column("raw_response", sa.Text())):
        if column.name not in columns:
            op.add_column("industry_daily_report", column)
    tables = set(sa.inspect(bind).get_table_names())
    if "background_task" not in tables:
        op.create_table(
            "background_task",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("type", sa.String(64), nullable=False),
            sa.Column("status", sa.String(16), nullable=False),
            sa.Column("progress", sa.Float(), nullable=False),
            sa.Column("message", sa.Text(), nullable=False),
            sa.Column("result", sa.JSON()),
            sa.Column("owner_id", sa.String(96), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("heartbeat_at", sa.DateTime(), nullable=False),
            sa.Column("completed_at", sa.DateTime()),
        )
        op.create_index("ix_background_task_status_heartbeat", "background_task", ["status", "heartbeat_at"])
        op.create_index("ix_background_task_created", "background_task", ["created_at"])
    if "scheduler_lease" not in tables:
        op.create_table(
            "scheduler_lease",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("owner_id", sa.String(96), nullable=False),
            sa.Column("heartbeat_at", sa.DateTime(), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
        )
    if "scheduled_job_run" not in tables:
        op.create_table(
            "scheduled_job_run",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("job_key", sa.String(96), nullable=False),
            sa.Column("slot", sa.String(32), nullable=False),
            sa.Column("status", sa.String(16), nullable=False),
            sa.Column("started_at", sa.DateTime(), nullable=False),
            sa.Column("completed_at", sa.DateTime()),
            sa.Column("error", sa.Text()),
            sa.UniqueConstraint("job_key", "slot", name="uq_scheduled_job_run_slot"),
        )
        op.create_index("ix_scheduled_job_run_started", "scheduled_job_run", ["started_at"])


def downgrade():
    for table in ("scheduled_job_run", "scheduler_lease", "background_task"):
        op.drop_table(table)
    with op.batch_alter_table("industry_daily_report") as batch:
        batch.drop_column("raw_response")
        batch.drop_column("input_snapshot")
