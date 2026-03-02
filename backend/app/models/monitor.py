from datetime import datetime
from sqlalchemy import Column, String, Boolean, JSON, DateTime, ForeignKey
from app.database import Base
from app.models.pool import gen_uuid

class MonitorRule(Base):
    __tablename__ = "monitor_rule"
    id = Column(String(36), primary_key=True, default=gen_uuid)
    pool_id = Column(String(36), ForeignKey("watch_pool.id"), nullable=True)
    stock_id = Column(String(36), ForeignKey("watch_stock.id"), nullable=True)
    template_id = Column(String(32))
    params = Column(JSON)
    logic = Column(String(8), default="and")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

class Alert(Base):
    __tablename__ = "alert"
    id = Column(String(36), primary_key=True, default=gen_uuid)
    stock_id = Column(String(36), ForeignKey("watch_stock.id"), nullable=False)
    rule_id = Column(String(36), ForeignKey("monitor_rule.id"), nullable=False)
    ts_code = Column(String(16), nullable=False)
    trigger_date = Column(String(8), nullable=False)
    status = Column(String(16), nullable=False, default="pending")
    plan_id = Column(String(36), ForeignKey("trade_plan.id"), nullable=True)
    snapshot = Column(JSON)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
