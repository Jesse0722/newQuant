from __future__ import annotations

from app.routers import stocks


class _FakeQuery:
    def __init__(self, scalar_values):
        self._scalar_values = list(scalar_values)

    def filter(self, *args, **kwargs):
        return self

    def scalar(self):
        if self._scalar_values:
            return self._scalar_values.pop(0)
        return None


class _FakeDb:
    def __init__(self, scalar_values):
        self._query = _FakeQuery(scalar_values)

    def query(self, *args, **kwargs):
        return self._query


def test_ensure_latest_kline_marks_sync_failed_when_still_stale(monkeypatch):
    fake_db = _FakeDb(["20260415", "20260415"])

    monkeypatch.setattr(stocks, "latest_daily_k_trade_date_str", lambda: "20260428")
    monkeypatch.setattr(stocks, "_sync_stock_kline_job", lambda ts_code: (0, None))

    result = stocks._ensure_latest_kline(fake_db, "000062.SZ")

    assert result["auto_sync_attempted"] is True
    assert result["status"] == "sync_failed"
    assert result["latest_trade_date"] == "20260415"
    assert result["target_trade_date"] == "20260428"
    assert result["added_count"] == 0
