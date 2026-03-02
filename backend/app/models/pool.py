import uuid
from datetime import datetime
from sqlalchemy import Column, String, Float, Text, DateTime, JSON, ForeignKey, UniqueConstraint
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
    note = Column(Text)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    pool = relationship("WatchPool", back_populates="stocks")
    __table_args__ = (UniqueConstraint("pool_id", "ts_code", name="uq_pool_stock"),)
