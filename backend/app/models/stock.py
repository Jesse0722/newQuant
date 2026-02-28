"""股票基础信息模型"""
from sqlalchemy import Column, String, Date, Boolean

from app.database import Base


class StockBasic(Base):
    """A股股票基础信息 - 对应 Tushare stock_basic"""
    __tablename__ = "stock_basic"

    ts_code = Column(String(20), primary_key=True)  # TS代码
    symbol = Column(String(10), nullable=False)    # 股票代码
    name = Column(String(50), nullable=False)       # 股票名称
    area = Column(String(20))                      # 地域
    industry = Column(String(50))                  # 所属行业
    market = Column(String(10))                    # 市场类型
    list_date = Column(String(8))                  # 上市日期 YYYYMMDD
    list_status = Column(String(1), default="L")   # 上市状态 L-上市 D-退市 P-暂停
    is_hs = Column(String(1))                      # 是否沪深港通
