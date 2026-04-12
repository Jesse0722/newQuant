from __future__ import annotations

from datetime import datetime, timedelta

import tushare as ts
import pandas as pd
from app.config import TUSHARE_TOKEN, TUSHARE_API_URL


class TushareAdapter:
    def __init__(self):
        self._pro = None

    @property
    def pro(self):
        if self._pro is None:
            self._pro = ts.pro_api(TUSHARE_TOKEN)
            if TUSHARE_API_URL:
                self._pro._DataApi__token = TUSHARE_TOKEN
                self._pro._DataApi__http_url = TUSHARE_API_URL
        return self._pro

    def get_stock_basic(self, ts_code: str = None) -> pd.DataFrame:
        params = {"exchange": "", "list_status": "L",
                  "fields": "ts_code,symbol,name,area,industry,market,list_date,list_status,float_share"}
        if ts_code:
            params["ts_code"] = ts_code
        return self.pro.stock_basic(**params)

    def get_daily(self, ts_code: str, start_date: str = None, end_date: str = None) -> pd.DataFrame:
        params = {"ts_code": ts_code}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        return self.pro.daily(**params)

    def get_daily_basic(self, ts_code: str, start_date: str = None, end_date: str = None) -> pd.DataFrame:
        params = {"ts_code": ts_code, "fields": "ts_code,trade_date,turnover_rate,float_share"}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        return self.pro.daily_basic(**params)

    def get_daily_by_date(self, trade_date: str) -> pd.DataFrame:
        """按交易日期获取全市场日线行情。trade_date 格式 YYYYMMDD"""
        return self.pro.daily(trade_date=trade_date)

    def get_rt_k(self, ts_code: str) -> pd.DataFrame:
        """实时日 K；ts_code 支持逗号分隔多码，单次建议不超过 5000 支。"""
        return self.pro.rt_k(ts_code=ts_code)

    def get_sse_open_dates(self, end_date: str, lookback_calendar_days: int = 400) -> list[str]:
        """SSE 交易日历中 is_open=1 的日期，YYYYMMDD，升序。end_date 含当日。"""
        ed = datetime.strptime(end_date, "%Y%m%d").date()
        sd = ed - timedelta(days=lookback_calendar_days)
        start_date = sd.strftime("%Y%m%d")
        df = self.pro.trade_cal(
            exchange="SSE",
            start_date=start_date,
            end_date=end_date,
            fields="cal_date,is_open",
        )
        if df is None or df.empty:
            return []
        # is_open 可能为字符串；必须与 1 等价比较
        open_mask = pd.to_numeric(df["is_open"], errors="coerce").eq(1)
        df = df.loc[open_mask]
        if df.empty:
            return []
        # cal_date 常为 datetime/Timestamp，勿用 astype(str)（会得到 "YYYY-MM-DD 00:00:00" 使 YYYYMMDD 比对与上游入参错误）
        norm = pd.to_datetime(df["cal_date"], errors="coerce").dt.strftime("%Y%m%d")
        out = [x for x in norm.dropna().tolist() if x and len(x) == 8]
        return sorted(set(out))

    def get_limit_cpt_list(self, trade_date: str) -> pd.DataFrame:
        return self.pro.limit_cpt_list(trade_date=trade_date)

    def get_limit_step(self, trade_date: str) -> pd.DataFrame:
        return self.pro.limit_step(trade_date=trade_date)

    def get_ths_index(self, **kwargs) -> pd.DataFrame:
        """同花顺板块指数；常用 type='N' 表示概念指数。详见 ths_index 文档。"""
        return self.pro.ths_index(**kwargs)

    def get_ths_member(self, ts_code: str | None = None, con_code: str | None = None) -> pd.DataFrame:
        """同花顺概念板块成分。常规用法：ths_member(ts_code='885xxx.TI') 按板块指数查成分股。"""
        p: dict = {}
        if ts_code:
            p["ts_code"] = ts_code
        if con_code:
            p["con_code"] = con_code
        return self.pro.ths_member(**p)


tushare_adapter = TushareAdapter()
