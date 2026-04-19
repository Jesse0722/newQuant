from __future__ import annotations

import uuid
from datetime import datetime
from sqlalchemy import Column, String, Float, Text, DateTime, JSON, ForeignKey, UniqueConstraint, Boolean, Integer
from sqlalchemy.orm import relationship
from app.database import Base

def gen_uuid():
    return str(uuid.uuid4())

class WatchPool(Base):
    __tablename__ = "watch_pool"
    id = Column(String(36), primary_key=True, default=gen_uuid)
    name = Column(String(64), nullable=False)
    description = Column(Text)
    default_monitor_rule = Column(JSON)
    sort_order = Column(Integer, nullable=False, default=0)  # 用于拖拽排序
    trigger_target_pool_id = Column(String(36), nullable=True)  # 买点触发后加入的池
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    stocks = relationship("WatchStock", back_populates="pool", cascade="all, delete-orphan")

class WatchStock(Base):
    __tablename__ = "watch_stock"
    id = Column(String(36), primary_key=True, default=gen_uuid)
    pool_id = Column(String(36), ForeignKey("watch_pool.id"), nullable=False)
    ts_code = Column(String(16), nullable=False)
    added_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    added_price = Column(Float)
    source = Column(String(16), nullable=False, default="manual")
    monitor_status = Column(String(16), nullable=False, default="monitoring")
    pinned = Column(Boolean, nullable=False, default=False)
    note = Column(Text)
    ai_analysis = Column(Text, nullable=True)  # AI 智能分析结果（JSON 字符串）
    ai_analyzed_at = Column(DateTime, nullable=True)  # AI 分析时间
    limit_up_date = Column(String(8), nullable=True)  # 涨停日期 YYYYMMDD
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    pool = relationship("WatchPool", back_populates="stocks")
    __table_args__ = (UniqueConstraint("pool_id", "ts_code", name="uq_pool_stock"),)
