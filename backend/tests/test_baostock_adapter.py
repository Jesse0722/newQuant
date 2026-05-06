from __future__ import annotations

import pandas as pd

from app.services import tushare_adapter as adapter_module
from app.services.tushare_adapter import BaoStockAdapter


class _Result:
    def __init__(self, df: pd.DataFrame, error_code: str = "0", error_msg: str = ""):
        self._df = df
        self.error_code = error_code
        self.error_msg = error_msg

    def get_data(self) -> pd.DataFrame:
        return self._df.copy()


class _FakeBaoStock:
    def login(self):
        return _Result(pd.DataFrame())

    def query_history_k_data_plus(self, code, fields, start_date="", end_date="", frequency="d", adjustflag="3"):
        if fields == "date,turn":
            return _Result(pd.DataFrame([
                {"date": "2024-01-02", "turn": "1.23"},
                {"date": "2024-01-03", "turn": "2.34"},
            ]))
        return _Result(pd.DataFrame([
            {
                "date": "2024-01-02",
                "code": code,
                "open": "10.0",
                "high": "11.0",
                "low": "9.5",
                "close": "10.8",
                "preclose": "9.9",
                "volume": "123456",
                "amount": "987654321",
                "pctChg": "9.09",
            },
            {
                "date": "2024-01-03",
                "code": code,
                "open": "10.8",
                "high": "11.2",
                "low": "10.2",
                "close": "10.4",
                "preclose": "10.8",
                "volume": "654321",
                "amount": "123456789",
                "pctChg": "-3.70",
            },
        ]))

    def query_trade_dates(self, start_date="", end_date=""):
        return _Result(pd.DataFrame([
            {"calendar_date": "2024-01-01", "is_trading_day": "0"},
            {"calendar_date": "2024-01-02", "is_trading_day": "1"},
            {"calendar_date": "2024-01-03", "is_trading_day": "1"},
        ]))

    def query_stock_basic(self, code=""):
        return _Result(pd.DataFrame([
            {"code": code, "code_name": "平安银行", "ipoDate": "1991-04-03", "status": "1"},
        ]))

    def query_stock_industry(self):
        return _Result(pd.DataFrame([
            {"code": "sz.000001", "industry": "银行"},
        ]))

    def query_all_stock(self, day=""):
        return _Result(pd.DataFrame([
            {"code": "sz.000001", "code_name": "平安银行"},
            {"code": "sh.600000", "code_name": "浦发银行"},
        ]))


def test_baostock_daily_and_basic(monkeypatch):
    monkeypatch.setattr(adapter_module, "bs", _FakeBaoStock())
    ad = BaoStockAdapter()

    daily = ad.get_daily("000001.SZ", start_date="20240101", end_date="20240110")
    basic = ad.get_daily_basic("000001.SZ", start_date="20240101", end_date="20240110")

    assert list(daily["trade_date"]) == ["20240103", "20240102"]
    assert float(daily.iloc[0]["close"]) == 10.4
    assert list(basic["trade_date"]) == ["20240103", "20240102"]
    assert float(basic.iloc[0]["turnover_rate"]) == 2.34


def test_baostock_stock_basic_and_calendar(monkeypatch):
    monkeypatch.setattr(adapter_module, "bs", _FakeBaoStock())
    ad = BaoStockAdapter()

    one = ad.get_stock_basic("000001.SZ")
    all_df = ad.get_stock_basic()
    dates = ad.get_sse_open_dates("20240103", lookback_calendar_days=10)

    assert one.iloc[0]["industry"] == "银行"
    assert one.iloc[0]["list_date"] == "19910403"
    assert "000001.SZ" in all_df["ts_code"].tolist()
    assert dates == ["20240102", "20240103"]
