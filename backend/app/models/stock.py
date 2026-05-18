from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, String, Float, DateTime, JSON, Text, Index
from app.database import Base
from app.models.pool import gen_uuid

class StockBasic(Base):
    __tablename__ = "stock_basic"
    ts_code = Column(String(16), primary_key=True)
    symbol = Column(String(10))
    name = Column(String(32), nullable=False)
    area = Column(String(16))
    industry = Column(String(32))
    market = Column(String(16))
    list_date = Column(String(8))
    list_status = Column(String(2))
    float_share = Column(Float, nullable=True)

class DailyQuote(Base):
    __tablename__ = "daily_quote"
    ts_code = Column(String(16), primary_key=True)
    trade_date = Column(String(8), primary_key=True)
    open = Column(Float)
    high = Column(Float)
    low = Column(Float)
    close = Column(Float)
    pre_close = Column(Float)
    change = Column(Float)
    pct_chg = Column(Float)
    vol = Column(Float)
    amount = Column(Float)
    turnover_rate = Column(Float, nullable=True)
    float_share = Column(Float, nullable=True)


class StockAiAnalysis(Base):
    __tablename__ = "stock_ai_analysis"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    ts_code = Column(String(16), nullable=False, index=True)
    scope = Column(String(32), nullable=False, default="stock_detail")
    pool_id = Column(String(36), nullable=True, index=True)
    watch_stock_id = Column(String(36), nullable=True, index=True)
    mode = Column(String(16), nullable=False, default="deep")
    model_provider = Column(String(32), nullable=False)
    model_name = Column(String(80), nullable=False)
    prompt_version = Column(String(16), nullable=False, default="1.0")
    snapshot_json = Column(JSON, nullable=True)
    analysis_json = Column(JSON, nullable=True)
    raw_response = Column(Text, nullable=True)
    data_trade_date = Column(String(8), nullable=True, index=True)
    status = Column(String(16), nullable=False, default="success")
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("ix_stock_ai_analysis_code_created", "ts_code", "created_at"),
    )
