from sqlalchemy import Column, String, DateTime, Text
from sqlalchemy.sql import func
from app.database import Base


class SyncLog(Base):
    """同步任务记录，持久化到数据库"""
    __tablename__ = "sync_log"
    id = Column(String(36), primary_key=True)
    task_type = Column(String(32), nullable=False)  # full_market, pool, stock
    target = Column(String(64))  # pool_id 或 ts_code，全市场为 null
    status = Column(String(16), nullable=False)  # running, completed, failed
    started_at = Column(DateTime, nullable=False, server_default=func.now())
    completed_at = Column(DateTime)
    result = Column(Text)  # JSON: success_count, failed_count, skipped_count, message 等
