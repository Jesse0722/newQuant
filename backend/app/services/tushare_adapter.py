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


tushare_adapter = TushareAdapter()
