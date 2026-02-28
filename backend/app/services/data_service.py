"""数据同步与缓存服务"""
from datetime import datetime
from typing import List, Optional

import pandas as pd
from sqlalchemy.orm import Session

from app.models.stock import StockBasic
from app.models.quote import DailyQuote
from app.services.tushare_adapter import TushareAdapter


class DataService:
    """数据同步服务"""

    def __init__(self, db: Session):
        self.db = db
        self.adapter = TushareAdapter()

    def sync_stock_basic(self) -> int:
        """同步 A 股股票列表到本地"""
        df = self.adapter.get_stock_basic()
        if df.empty:
            return 0

        count = 0
        for _, row in df.iterrows():
            st = self.db.query(StockBasic).filter(StockBasic.ts_code == row["ts_code"]).first()
            if st:
                st.symbol = row.get("symbol", st.symbol)
                st.name = row.get("name", st.name)
                st.area = row.get("area")
                st.industry = row.get("industry")
                st.market = row.get("market")
                st.list_date = str(row.get("list_date", "")) if pd.notna(row.get("list_date")) else None
                st.list_status = row.get("list_status", "L")
                st.is_hs = str(row.get("is_hs", "")) if pd.notna(row.get("is_hs")) else None
            else:
                st = StockBasic(
                    ts_code=row["ts_code"],
                    symbol=str(row.get("symbol", "")),
                    name=str(row.get("name", "")),
                    area=str(row.get("area", "")) if pd.notna(row.get("area")) else None,
                    industry=str(row.get("industry", "")) if pd.notna(row.get("industry")) else None,
                    market=str(row.get("market", "")) if pd.notna(row.get("market")) else None,
                    list_date=str(row.get("list_date", "")) if pd.notna(row.get("list_date")) else None,
                    list_status=str(row.get("list_status", "L")),
                    is_hs=str(row.get("is_hs", "")) if pd.notna(row.get("is_hs")) else None,
                )
                self.db.add(st)
            count += 1
        self.db.commit()
        return count

    def sync_daily_range(
        self,
        start_date: str,
        end_date: str,
        ts_codes: Optional[List[str]] = None,
    ) -> int:
        """
        同步指定日期范围的日线数据
        :param start_date: YYYYMMDD
        :param end_date: YYYYMMDD
        :param ts_codes: 股票代码列表，为空则拉取全市场（需先有 stock_basic）
        """
        if ts_codes is None:
            stocks = self.db.query(StockBasic).filter(StockBasic.list_status == "L").all()
            ts_codes = [s.ts_code for s in stocks]
        if not ts_codes:
            return 0

        total = 0
        for ts_code in ts_codes:
            try:
                df = self.adapter.pro.daily(
                    ts_code=ts_code,
                    start_date=start_date,
                    end_date=end_date,
                )
            except Exception:
                continue
            if df.empty:
                continue
            for _, row in df.iterrows():
                q = self.db.query(DailyQuote).filter(
                    DailyQuote.ts_code == row["ts_code"],
                    DailyQuote.trade_date == row["trade_date"],
                ).first()
                if not q:
                    q = DailyQuote(
                        ts_code=row["ts_code"],
                        trade_date=row["trade_date"],
                        open=float(row.get("open", 0)),
                        high=float(row.get("high", 0)),
                        low=float(row.get("low", 0)),
                        close=float(row.get("close", 0)),
                        pre_close=float(row.get("pre_close", 0)) if pd.notna(row.get("pre_close")) else None,
                        change=float(row.get("change", 0)) if pd.notna(row.get("change")) else None,
                        pct_chg=float(row.get("pct_chg", 0)) if pd.notna(row.get("pct_chg")) else None,
                        vol=int(row.get("vol", 0)) if pd.notna(row.get("vol")) else None,
                        amount=float(row.get("amount", 0)) if pd.notna(row.get("amount")) else None,
                    )
                    self.db.add(q)
                    total += 1
            self.db.commit()
        return total
