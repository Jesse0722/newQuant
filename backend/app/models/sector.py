from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, Float, Index, Integer, String, UniqueConstraint

from app.database import Base
from app.models.pool import gen_uuid


class SectorBasic(Base):
    __tablename__ = "sector_basic"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    sector_code = Column(String(32), nullable=False, unique=True, index=True)
    sector_name = Column(String(64), nullable=False, index=True)
    sector_type = Column(String(16), nullable=False, default="concept", index=True)
    source = Column(String(32), nullable=False, default="eastmoney", index=True)
    raw_code = Column(String(32), nullable=True)
    rank = Column(Integer, nullable=True)
    latest_pct_chg = Column(Float, nullable=True)
    latest_hot = Column(Float, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class StockSectorMap(Base):
    __tablename__ = "stock_sector_map"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    ts_code = Column(String(16), nullable=False, index=True)
    sector_code = Column(String(32), nullable=False, index=True)
    sector_name = Column(String(64), nullable=False, index=True)
    sector_type = Column(String(16), nullable=False, default="concept", index=True)
    source = Column(String(32), nullable=False, default="eastmoney", index=True)
    weight = Column(Float, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("ts_code", "sector_code", "source", name="uq_stock_sector_source"),
        Index("ix_stock_sector_type_code", "sector_type", "sector_code"),
    )


class SectorDailyQuote(Base):
    __tablename__ = "sector_daily_quote"

    sector_code = Column(String(32), primary_key=True)
    trade_date = Column(String(8), primary_key=True)
    sector_name = Column(String(64), nullable=False, index=True)
    sector_type = Column(String(16), nullable=False, default="concept", index=True)
    source = Column(String(32), nullable=False, default="eastmoney", index=True)
    open = Column(Float, nullable=True)
    high = Column(Float, nullable=True)
    low = Column(Float, nullable=True)
    close = Column(Float, nullable=True)
    pct_chg = Column(Float, nullable=True)
    change = Column(Float, nullable=True)
    vol = Column(Float, nullable=True)
    amount = Column(Float, nullable=True)
    turnover_rate = Column(Float, nullable=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("ix_sector_daily_type_date", "sector_type", "trade_date"),
    )


class SectorQuoteSyncState(Base):
    __tablename__ = "sector_quote_sync_state"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    sector_code = Column(String(32), nullable=False, index=True)
    sector_name = Column(String(64), nullable=False, index=True)
    sector_type = Column(String(16), nullable=False, default="concept", index=True)
    source = Column(String(32), nullable=False, default="eastmoney_direct", index=True)
    status = Column(String(16), nullable=False, default="pending", index=True)
    target_days = Column(Integer, nullable=True)
    quote_count = Column(Integer, nullable=False, default=0)
    first_trade_date = Column(String(8), nullable=True)
    last_trade_date = Column(String(8), nullable=True)
    attempts = Column(Integer, nullable=False, default=0)
    last_error = Column(String(512), nullable=True)
    next_retry_at = Column(DateTime, nullable=True)
    last_success_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("sector_code", "source", name="uq_sector_quote_sync_source"),
        Index("ix_sector_quote_sync_status_retry", "status", "next_retry_at"),
    )
