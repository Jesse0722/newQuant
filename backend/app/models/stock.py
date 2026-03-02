from sqlalchemy import Column, String, Float
from app.database import Base

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
