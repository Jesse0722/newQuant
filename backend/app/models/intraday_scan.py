from datetime import datetime
from sqlalchemy import Column, String, Boolean, Integer, DateTime

from app.database import Base
from app.models.pool import gen_uuid


class IntradayScanConfig(Base):
    __tablename__ = "intraday_scan_config"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    pool_id = Column(String(36), nullable=False)
    strategy_id = Column(String(64), nullable=False)
    enabled = Column(Boolean, nullable=False, default=False)
    interval_minutes = Column(Integer, nullable=False, default=5)
    min_confirm_hits = Column(Integer, nullable=False, default=2)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
