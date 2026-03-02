from datetime import datetime
from sqlalchemy import Column, String, Integer, Float, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from app.database import Base
from app.models.pool import gen_uuid

class TradePlan(Base):
    __tablename__ = "trade_plan"
    id = Column(String(36), primary_key=True, default=gen_uuid)
    ts_code = Column(String(16), nullable=False)
    stock_name = Column(String(32))
    plan_type = Column(String(16), nullable=False)
    risk_level = Column(Integer, nullable=False, default=3)
    status = Column(String(16), nullable=False, default="pending")
    trigger_strategy = Column(Text)
    alert_id = Column(String(36), ForeignKey("alert.id"), nullable=True)
    event_note = Column(Text)
    action_suggestion = Column(String(16))
    planned_buy_price = Column(Float)
    target_price = Column(Float)
    stop_loss_price = Column(Float)
    risk_reward_ratio = Column(Float)
    position_plan = Column(String(32))
    actual_pnl = Column(Float)
    review_summary = Column(Text)
    lessons_learned = Column(Text)
    note = Column(Text)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    details = relationship("TradeDetail", back_populates="plan", cascade="all, delete-orphan")

class TradeDetail(Base):
    __tablename__ = "trade_detail"
    id = Column(String(36), primary_key=True, default=gen_uuid)
    plan_id = Column(String(36), ForeignKey("trade_plan.id"), nullable=False)
    trade_date = Column(String(8), nullable=False)
    trade_time = Column(String(8))
    direction = Column(String(4), nullable=False)
    price = Column(Float, nullable=False)
    quantity = Column(Integer, nullable=False)
    amount = Column(Float, nullable=False)
    commission = Column(Float, default=0)
    stamp_tax = Column(Float, default=0)
    exec_note = Column(Text)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    plan = relationship("TradePlan", back_populates="details")
