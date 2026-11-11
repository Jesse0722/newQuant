"""Complete message evidence and review schema without replacing existing data.

Revision ID: 2a1e7c90b311
Revises: 1f4b0c7d9e2a
"""
from alembic import op
import sqlalchemy as sa

revision = "2a1e7c90b311"
down_revision = "1f4b0c7d9e2a"
branch_labels = None
depends_on = None


def upgrade():
    # SQLite MVP databases may already contain these additions from create_all.
    bind = op.get_bind()
    existing = {c["name"] for c in sa.inspect(bind).get_columns("message_opportunity")}
    columns = [
        sa.Column("evidence_score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("mapping_confidence", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("review_status", sa.String(16), nullable=False, server_default="reviewed"),
        sa.Column("review_reason", sa.Text()),
        sa.Column("generated_by", sa.String(16), nullable=False, server_default="manual"),
        sa.Column("accepted_at", sa.DateTime()),
        sa.Column("dismissed_at", sa.DateTime()),
    ]
    for column in columns:
        if column.name not in existing:
            op.add_column("message_opportunity", column)
    indexes = {i["name"] for i in sa.inspect(bind).get_indexes("message_opportunity")}
    if "ix_message_opportunity_review_status" not in indexes:
        op.create_index("ix_message_opportunity_review_status", "message_opportunity", ["review_status"])
    tables = set(sa.inspect(bind).get_table_names())
    if "message_evidence" not in tables:
        op.create_table(
            "message_evidence",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("source_item_id", sa.String(36), sa.ForeignKey("message_source_item.id"), nullable=False),
            sa.Column("trade_date", sa.String(8), nullable=False),
            sa.Column("channel", sa.String(32), nullable=False),
            sa.Column("theme", sa.String(64)),
            sa.Column("ts_code", sa.String(16)),
            sa.Column("evidence_text", sa.Text(), nullable=False),
            sa.Column("stance", sa.String(16), nullable=False),
            sa.Column("quality_score", sa.Integer(), nullable=False),
            sa.Column("credibility_score", sa.Integer(), nullable=False),
            sa.Column("confidence", sa.Integer(), nullable=False),
            sa.Column("extraction_method", sa.String(16), nullable=False),
            sa.Column("extractor_name", sa.String(64), nullable=False),
            sa.Column("extractor_version", sa.String(16), nullable=False),
            sa.Column("raw_json", sa.JSON()),
            sa.Column("status", sa.String(16), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("source_item_id", "extractor_name", "extractor_version", "stance", name="uq_message_evidence_source_extractor_stance"),
        )
        for field in ("source_item_id", "trade_date", "channel", "theme", "ts_code", "stance", "status"):
            op.create_index("ix_message_evidence_" + field, "message_evidence", [field])
        op.create_index("ix_message_evidence_date_theme", "message_evidence", ["trade_date", "theme"])
        op.create_index("ix_message_evidence_date_stock", "message_evidence", ["trade_date", "ts_code"])
    if "message_opportunity_evidence" not in tables:
        op.create_table(
            "message_opportunity_evidence",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("opportunity_id", sa.String(36), sa.ForeignKey("message_opportunity.id"), nullable=False),
            sa.Column("evidence_id", sa.String(36), sa.ForeignKey("message_evidence.id"), nullable=False),
            sa.Column("role", sa.String(16), nullable=False),
            sa.Column("weight", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("opportunity_id", "evidence_id", "role", name="uq_message_opportunity_evidence_role"),
        )
        for field in ("opportunity_id", "evidence_id"):
            op.create_index("ix_message_opportunity_evidence_" + field, "message_opportunity_evidence", [field])
        op.create_index("ix_message_opportunity_evidence_opp_role", "message_opportunity_evidence", ["opportunity_id", "role"])
    if "message_agent_run" not in tables:
        op.create_table(
            "message_agent_run",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("agent_name", sa.String(64), nullable=False),
            sa.Column("agent_version", sa.String(16), nullable=False),
            sa.Column("trade_date", sa.String(8)),
            sa.Column("input_ref_type", sa.String(32)),
            sa.Column("input_ref_id", sa.String(64)),
            sa.Column("input_digest", sa.String(64)),
            sa.Column("output_json", sa.JSON()),
            sa.Column("model_provider", sa.String(32), nullable=False),
            sa.Column("model_name", sa.String(80), nullable=False),
            sa.Column("prompt_version", sa.String(16)),
            sa.Column("status", sa.String(16), nullable=False),
            sa.Column("error_message", sa.Text()),
            sa.Column("started_at", sa.DateTime(), nullable=False),
            sa.Column("finished_at", sa.DateTime()),
            sa.Column("duration_ms", sa.Integer()),
        )
        for field in ("agent_name", "trade_date", "input_digest", "status"):
            op.create_index("ix_message_agent_run_" + field, "message_agent_run", [field])
        op.create_index("ix_message_agent_run_date_agent", "message_agent_run", ["trade_date", "agent_name"])


def downgrade():
    for table in ("message_opportunity_evidence", "message_evidence", "message_agent_run"):
        op.drop_table(table)
    op.drop_index("ix_message_opportunity_review_status", table_name="message_opportunity")
    with op.batch_alter_table("message_opportunity") as batch:
        for name in ("dismissed_at", "accepted_at", "generated_by", "review_reason", "review_status", "mapping_confidence", "evidence_score"):
            batch.drop_column(name)
