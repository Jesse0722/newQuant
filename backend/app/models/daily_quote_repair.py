from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    UniqueConstraint,
)

from app.database import Base
from app.models.pool import gen_uuid


class DailyQuoteRepairBatch(Base):
    """Immutable repair-plan identity and lifecycle metadata."""

    __tablename__ = "daily_quote_repair_batch"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    plan_hash = Column(String(64), nullable=False)
    status = Column(String(32), nullable=False)
    database_identity = Column(JSON, nullable=False)
    policy = Column(JSON, nullable=False)
    backup_manifest = Column(JSON, nullable=True)
    summary = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    applied_at = Column(DateTime, nullable=True)
    rolled_back_at = Column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint("plan_hash", name="uq_daily_quote_repair_batch_plan_hash"),
    )


class DailyQuoteRepairAudit(Base):
    """Per-quote before/after evidence used to verify or roll back a repair."""

    __tablename__ = "daily_quote_repair_audit"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    batch_id = Column(
        String(36),
        ForeignKey("daily_quote_repair_batch.id", ondelete="RESTRICT"),
        nullable=False,
    )
    sequence = Column(Integer, nullable=False)
    ts_code = Column(String(16), nullable=False)
    trade_date = Column(String(8), nullable=False)
    operation = Column(String(16), nullable=False)
    old_values = Column(JSON, nullable=True)
    new_values = Column(JSON, nullable=False)
    changed_fields = Column(JSON, nullable=False)
    old_hash = Column(String(64), nullable=True)
    new_hash = Column(String(64), nullable=False)
    source_json = Column(JSON, nullable=False)
    applied_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    rolled_back_at = Column(DateTime, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "operation IN ('insert', 'update')",
            name="ck_daily_quote_repair_audit_operation",
        ),
        UniqueConstraint(
            "batch_id",
            "ts_code",
            "trade_date",
            name="uq_daily_quote_repair_audit_batch_quote",
        ),
        Index("ix_daily_quote_repair_audit_batch_sequence", "batch_id", "sequence"),
        Index("ix_daily_quote_repair_audit_quote", "ts_code", "trade_date"),
    )
