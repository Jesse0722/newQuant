from __future__ import annotations

import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.services.trade_date_resolver import (
    TradeDateResolutionError,
    last_n_resolved_trade_dates,
    resolve_dashboard_trade_date_with_calendar,
)


class TestTradeDateResolver(unittest.TestCase):
    def setUp(self):
        self.sh = ZoneInfo("Asia/Shanghai")
        # 20260330 周一、20260327 周五为假设连续交易日
        self.open_days = ["20260325", "20260326", "20260327", "20260330", "20260331"]

    def test_during_session_uses_previous_day(self):
        now = datetime(2026, 3, 30, 10, 0, 0, tzinfo=self.sh)
        td = resolve_dashboard_trade_date_with_calendar(now, self.open_days)
        self.assertEqual(td, "20260327")

    def test_after_close_same_day(self):
        now = datetime(2026, 3, 30, 16, 0, 0, tzinfo=self.sh)
        td = resolve_dashboard_trade_date_with_calendar(now, self.open_days)
        self.assertEqual(td, "20260330")

    def test_before_open_uses_previous(self):
        now = datetime(2026, 3, 30, 9, 0, 0, tzinfo=self.sh)
        td = resolve_dashboard_trade_date_with_calendar(now, self.open_days)
        self.assertEqual(td, "20260327")

    def test_saturday_uses_friday(self):
        now = datetime(2026, 3, 28, 12, 0, 0, tzinfo=self.sh)
        td = resolve_dashboard_trade_date_with_calendar(now, self.open_days)
        self.assertEqual(td, "20260327")

    def test_no_prior_open_raises(self):
        now = datetime(2026, 3, 25, 10, 0, 0, tzinfo=self.sh)
        with self.assertRaises(TradeDateResolutionError):
            resolve_dashboard_trade_date_with_calendar(now, ["20260325"])


class TestLastNResolvedTradeDates(unittest.TestCase):
    def test_returns_last_n_sorted(self):
        ad = MagicMock()
        ad.get_sse_open_dates.return_value = ["20260326", "20260327", "20260328", "20260329", "20260330"]
        with patch(
            "app.services.trade_date_resolver.resolve_dashboard_trade_date",
            return_value="20260330",
        ):
            out = last_n_resolved_trade_dates(3, adapter=ad)
        self.assertEqual(out, ["20260328", "20260329", "20260330"])


if __name__ == "__main__":
    unittest.main()
