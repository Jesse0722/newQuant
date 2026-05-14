from __future__ import annotations

import pandas as pd

from app.models.stock import DailyQuote
from app.services import sync_service


class _FakeQuery:
    def __init__(self, scalar_value=None, first_value=None):
        self._scalar_value = scalar_value
        self._first_value = first_value

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def first(self):
        return self._first_value

    def scalar(self):
        return self._scalar_value


class _FakeDb:
    def __init__(self):
        self.added: list[DailyQuote] = []
        self.query_calls = 0

    def query(self, *args, **kwargs):
        self.query_calls += 1
        if self.query_calls == 1:
            return _FakeQuery(scalar_value=100)
        if self.query_calls == 2:
            return _FakeQuery(first_value=("20260415",))
        return _FakeQuery(first_value=None)

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        return None

    def rollback(self):
        return None


def test_sync_daily_filters_invalid_ts_code_rows(monkeypatch):
    fake_db = _FakeDb()

    monkeypatch.setattr(sync_service, "_commit_with_retry", lambda db: None)
    monkeypatch.setattr(sync_service, "_backfill_turnover_rate", lambda *args, **kwargs: None)
    monkeypatch.setattr(sync_service, "latest_daily_k_trade_date_str", lambda: "20260428")

    class _Adapter:
        def get_daily(self, ts_code, start_date=None, end_date=None):
            return pd.DataFrame([
                {"ts_code": "", "trade_date": "20260416", "open": 1, "high": 1, "low": 1, "close": 1},
                {"ts_code": "000062.SZ", "trade_date": "20260416", "open": 2, "high": 2, "low": 2, "close": 2},
                {"ts_code": "000062.SZ", "trade_date": "bad-date", "open": 3, "high": 3, "low": 3, "close": 3},
            ])

    monkeypatch.setattr(sync_service, "tushare_adapter", _Adapter())

    added = sync_service.sync_daily(fake_db, "000062.SZ", 250)

    assert added == 1
    assert len(fake_db.added) == 1
    assert fake_db.added[0].ts_code == "000062.SZ"
    assert fake_db.added[0].trade_date == "20260416"
