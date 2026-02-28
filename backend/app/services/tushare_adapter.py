"""Tushare Pro 数据适配层 - 封装接口便于后续扩展"""
import pandas as pd
from typing import Optional

from app.config import TUSHARE_TOKEN


class TushareAdapter:
    """Tushare Pro 适配器"""

    def __init__(self, token: Optional[str] = None):
        self._token = token or TUSHARE_TOKEN
        self._pro = None

    @property
    def pro(self):
        if self._pro is None:
            if not self._token:
                raise ValueError("请配置 TUSHARE_TOKEN，在 .env 中设置或在 https://tushare.pro 注册获取")
            import tushare as ts
            ts.set_token(self._token)
            self._pro = ts.pro_api()
        return self._pro

    def get_stock_basic(self) -> pd.DataFrame:
        """获取 A 股股票列表"""
        df = self.pro.stock_basic(
            exchange="",
            list_status="L",
            fields="ts_code,symbol,name,area,industry,market,list_date,list_status,is_hs",
        )
        return df

    def get_daily(
        self,
        ts_code: Optional[str] = None,
        trade_date: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        获取日线行情
        :param ts_code: 股票代码，如 000001.SZ
        :param trade_date: 交易日期 YYYYMMDD
        :param start_date: 开始日期
        :param end_date: 结束日期
        """
        if ts_code:
            df = self.pro.daily(
                ts_code=ts_code,
                start_date=start_date or "",
                end_date=end_date or "",
            )
        elif trade_date:
            df = self.pro.daily(trade_date=trade_date)
        elif start_date and end_date:
            # Tushare daily 按股票查，按日期需用 trade_cal + 循环或 daily 按 trade_date
            df = self.pro.daily(trade_date=end_date)  # 单日
            # 多日需用 query 或 trade 接口
            raise NotImplementedError("按日期范围批量拉取请使用 sync_daily_range")
        else:
            raise ValueError("需提供 ts_code 或 trade_date")
        return df

    def get_trade_cal(
        self,
        start_date: str,
        end_date: str,
        exchange: str = "SSE",
    ) -> pd.DataFrame:
        """获取交易日历"""
        return self.pro.trade_cal(
            exchange=exchange,
            start_date=start_date,
            end_date=end_date,
            is_open=1,
        )
