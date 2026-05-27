from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint

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


class MessageKeywordSeed(Base):
    __tablename__ = "message_keyword_seed"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    keyword = Column(String(80), nullable=False)
    type = Column(String(24), nullable=False, default="industry")
    theme = Column(String(64), nullable=False)
    priority = Column(Integer, nullable=False, default=3)
    language = Column(String(8), nullable=False, default="zh")
    status = Column(String(16), nullable=False, default="active")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("keyword", "type", "theme", "language", name="uq_message_keyword_seed"),
        Index("ix_message_keyword_seed_theme_priority", "theme", "priority"),
    )


class MessageSourceItem(Base):
    __tablename__ = "message_source_item"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    trade_date = Column(String(8), nullable=False, index=True)
    channel = Column(String(32), nullable=False, index=True)
    source_name = Column(String(64), nullable=True)
    external_id = Column(String(128), nullable=True)
    title = Column(String(200), nullable=True)
    content = Column(Text, nullable=False)
    url = Column(String(500), nullable=True)
    published_at = Column(DateTime, nullable=True)
    captured_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    theme = Column(String(64), nullable=True, index=True)
    ts_code = Column(String(16), nullable=True, index=True)
    stock_name = Column(String(32), nullable=True)
    tags = Column(JSON, nullable=True)
    sentiment = Column(String(16), nullable=False, default="neutral")
    heat_score = Column(Integer, nullable=False, default=50)
    credibility_score = Column(Integer, nullable=False, default=50)
    dedupe_key = Column(String(64), nullable=False, unique=True, index=True)
    raw_payload = Column(JSON, nullable=True)
    status = Column(String(16), nullable=False, default="new")

    __table_args__ = (
        Index("ix_message_source_item_date_theme", "trade_date", "theme"),
        Index("ix_message_source_item_date_stock", "trade_date", "ts_code"),
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


class MessageEntity(Base):
    __tablename__ = "message_entity"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    entity_type = Column(String(32), nullable=False, index=True)
    name = Column(String(128), nullable=False)
    normalized_name = Column(String(128), nullable=False)
    ts_code = Column(String(16), nullable=True, index=True)
    aliases = Column(JSON, nullable=True)
    extra_metadata = Column(JSON, nullable=True)
    confidence = Column(Integer, nullable=False, default=70)
    status = Column(String(16), nullable=False, default="active", index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("entity_type", "normalized_name", name="uq_message_entity_type_name"),
        Index("ix_message_entity_type_status", "entity_type", "status"),
    )


class MessageRelation(Base):
    __tablename__ = "message_relation"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    source_entity_id = Column(String(36), ForeignKey("message_entity.id"), nullable=False, index=True)
    relation_type = Column(String(40), nullable=False, index=True)
    target_entity_id = Column(String(36), ForeignKey("message_entity.id"), nullable=False, index=True)
    confidence = Column(Integer, nullable=False, default=60)
    strength = Column(Integer, nullable=False, default=50)
    polarity = Column(String(16), nullable=False, default="neutral")
    valid_from = Column(String(8), nullable=True)
    valid_to = Column(String(8), nullable=True)
    evidence_count = Column(Integer, nullable=False, default=0)
    source_type = Column(String(16), nullable=False, default="seed")
    status = Column(String(16), nullable=False, default="active", index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint(
            "source_entity_id",
            "relation_type",
            "target_entity_id",
            "source_type",
            name="uq_message_relation_edge_source",
        ),
        Index("ix_message_relation_type_status", "relation_type", "status"),
    )


class MessageRelationEvidence(Base):
    __tablename__ = "message_relation_evidence"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    relation_id = Column(String(36), ForeignKey("message_relation.id"), nullable=False, index=True)
    source_item_id = Column(String(36), ForeignKey("message_source_item.id"), nullable=True, index=True)
    evidence_text = Column(Text, nullable=False)
    evidence_url = Column(String(500), nullable=True)
    source_channel = Column(String(32), nullable=True)
    extraction_method = Column(String(16), nullable=False, default="seed")
    confidence = Column(Integer, nullable=False, default=60)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_message_relation_evidence_relation_created", "relation_id", "created_at"),
    )


class IndustryDailyReport(Base):
    __tablename__ = "industry_daily_report"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    trade_date = Column(String(8), nullable=False, unique=True, index=True)
    title = Column(String(128), nullable=False)
    headline = Column(String(200), nullable=True)
    summary = Column(Text, nullable=True)
    report_json = Column(JSON, nullable=True)
    model_provider = Column(String(32), nullable=True)
    model_name = Column(String(80), nullable=True)
    prompt_version = Column(String(16), nullable=False, default="1.0")
    status = Column(String(16), nullable=False, default="success", index=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class IndustryReportCandidate(Base):
    __tablename__ = "industry_report_candidate"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    report_id = Column(String(36), ForeignKey("industry_daily_report.id"), nullable=False, index=True)
    trade_date = Column(String(8), nullable=False, index=True)
    ts_code = Column(String(16), nullable=False, index=True)
    stock_name = Column(String(32), nullable=True)
    theme = Column(String(64), nullable=False, index=True)
    path_json = Column(JSON, nullable=True)
    evidence_json = Column(JSON, nullable=True)
    path_score = Column(Integer, nullable=False, default=0)
    evidence_score = Column(Integer, nullable=False, default=0)
    heat_score = Column(Integer, nullable=False, default=0)
    crowding_score = Column(Integer, nullable=False, default=0)
    risk_score = Column(Integer, nullable=False, default=0)
    final_score = Column(Float, nullable=False, default=0)
    grade = Column(String(16), nullable=False, default="weak", index=True)
    reason = Column(Text, nullable=True)
    risks = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("report_id", "ts_code", "theme", name="uq_industry_report_candidate"),
        Index("ix_industry_candidate_date_score", "trade_date", "final_score"),
    )
