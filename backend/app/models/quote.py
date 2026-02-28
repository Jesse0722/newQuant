"""日线行情模型"""
from sqlalchemy import Column, String, Date, Float, BigInteger

from app.database import Base


class DailyQuote(Base):
    """日线行情 - 对应 Tushare daily"""
    __tablename__ = "daily_quote"

    ts_code = Column(String(20), primary_key=True)
    trade_date = Column(String(8), primary_key=True)  # YYYYMMDD
    open = Column(Float)
    high = Column(Float)
    low = Column(Float)
    close = Column(Float)
    pre_close = Column(Float)
    change = Column(Float)
    pct_chg = Column(Float)
    vol = Column(BigInteger)   # 成交量
    amount = Column(Float)     # 成交额
