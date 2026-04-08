"""CompositeAdapter：异常或空结果时换源。"""

import pandas as pd
import pytest

from app.services.tushare_adapter import CompositeAdapter


class _EmptyDaily:
    def get_daily(self, ts_code: str, start_date: str | None = None, end_date: str | None = None):
        return pd.DataFrame()

    def get_stock_basic(self, ts_code: str | None = None):
        return pd.DataFrame()

    def get_daily_basic(self, ts_code: str, start_date: str | None = None, end_date: str | None = None):
        return pd.DataFrame()

    def get_daily_by_date(self, trade_date: str):
        return pd.DataFrame()

    def get_rt_k(self, ts_code: str):
        return pd.DataFrame()

    def get_sse_open_dates(self, end_date: str, lookback_calendar_days: int = 400):
        return []

    def get_limit_cpt_list(self, trade_date: str):
        return pd.DataFrame()

    def get_limit_step(self, trade_date: str):
        return pd.DataFrame()


class _Boom:
    def get_daily(self, ts_code: str, start_date: str | None = None, end_date: str | None = None):
        raise ConnectionError("upstream down")


class _OkDaily:
    def get_daily(self, ts_code: str, start_date: str | None = None, end_date: str | None = None):
        return pd.DataFrame([{"ts_code": ts_code, "trade_date": "20240102", "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0}])


def test_composite_empty_then_ok():
    ad = CompositeAdapter([_EmptyDaily(), _OkDaily()])
    df = ad.get_daily("000001.SZ", start_date="20240101", end_date="20240105")
    assert not df.empty
    assert df.iloc[0]["ts_code"] == "000001.SZ"


def test_composite_boom_then_empty_clears_error():
    """第一个源抛错、第二个源返回空：不应再抛出第一个源的异常。"""
    ad = CompositeAdapter([_Boom(), _EmptyDaily()])
    df = ad.get_daily("000001.SZ")
    assert df.empty


def test_composite_boom_then_ok():
    ad = CompositeAdapter([_Boom(), _OkDaily()])
    df = ad.get_daily("000001.SZ")
    assert not df.empty


def test_composite_all_boom_raises_last():
    ad = CompositeAdapter([_Boom(), _Boom()])
    with pytest.raises(ConnectionError):
        ad.get_daily("000001.SZ")


def test_composite_sse_open_dates_empty_fallback():
    class CalA:
        def get_sse_open_dates(self, end_date: str, lookback_calendar_days: int = 400):
            return []

    class CalB:
        def get_sse_open_dates(self, end_date: str, lookback_calendar_days: int = 400):
            return ["20240101", "20240102"]

    ad = CompositeAdapter([CalA(), CalB()])
    assert ad.get_sse_open_dates("20240201", 10) == ["20240101", "20240102"]
