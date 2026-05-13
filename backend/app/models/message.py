from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint

from app.database import Base
from app.models.pool import gen_uuid


class MessageTopic(Base):
    __tablename__ = "message_topic"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    trade_date = Column(String(8), nullable=False, index=True)
    theme = Column(String(64), nullable=False)
    summary = Column(Text, nullable=True)
    lifecycle_stage = Column(String(16), nullable=False, default="early")
    sentiment = Column(String(16), nullable=False, default="neutral")
    heat_score = Column(Integer, nullable=False, default=50)
    credibility_score = Column(Integer, nullable=False, default=50)
    crowding_score = Column(Integer, nullable=False, default=30)
    source_platforms = Column(JSON, nullable=True)
    tags = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("trade_date", "theme", name="uq_message_topic_date_theme"),
    )


class MessageOpportunity(Base):
    __tablename__ = "message_opportunity"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    topic_id = Column(String(36), ForeignKey("message_topic.id"), nullable=True)
    trade_date = Column(String(8), nullable=False, index=True)
    theme = Column(String(64), nullable=False)
    ts_code = Column(String(16), nullable=True, index=True)
    stock_name = Column(String(32), nullable=True)
    opportunity_score = Column(Integer, nullable=False, default=50)
    heat_score = Column(Integer, nullable=False, default=50)
    credibility_score = Column(Integer, nullable=False, default=50)
    risk_score = Column(Integer, nullable=False, default=40)
    action_suggestion = Column(String(16), nullable=False, default="watch")
    reason = Column(Text, nullable=True)
    catalysts = Column(JSON, nullable=True)
    risks = Column(JSON, nullable=True)
    source_platforms = Column(JSON, nullable=True)
    source_links = Column(JSON, nullable=True)
    status = Column(String(16), nullable=False, default="active")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_message_opportunity_date_score", "trade_date", "opportunity_score"),
    )
