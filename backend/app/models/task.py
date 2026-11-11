from __future__ import annotations

from datetime import datetime
from sqlalchemy import Column, DateTime, Float, Index, JSON, String, Text, UniqueConstraint
from app.database import Base


class BackgroundTask(Base):
    """Durable task state; callable arguments/credentials are never stored."""
    __tablename__ = "background_task"
    id = Column(String(36), primary_key=True)
    type = Column(String(64), nullable=False)
    status = Column(String(16), nullable=False)
    progress = Column(Float, nullable=False, default=0)
    message = Column(Text, nullable=False, default="")
    result = Column(JSON)
    owner_id = Column(String(96), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    heartbeat_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    completed_at = Column(DateTime)
    __table_args__ = (Index("ix_background_task_status_heartbeat", "status", "heartbeat_at"),
                      Index("ix_background_task_created", "created_at"))


class SchedulerLease(Base):
    __tablename__ = "scheduler_lease"
    id = Column(String(64), primary_key=True)
    owner_id = Column(String(96), nullable=False)
    heartbeat_at = Column(DateTime, nullable=False)
    expires_at = Column(DateTime, nullable=False)


class ScheduledJobRun(Base):
    __tablename__ = "scheduled_job_run"
    id = Column(String(36), primary_key=True)
    job_key = Column(String(96), nullable=False)
    slot = Column(String(32), nullable=False)
    status = Column(String(16), nullable=False)
    started_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    completed_at = Column(DateTime)
    error = Column(Text)
    __table_args__ = (UniqueConstraint("job_key", "slot", name="uq_scheduled_job_run_slot"),
                      Index("ix_scheduled_job_run_started", "started_at"))
