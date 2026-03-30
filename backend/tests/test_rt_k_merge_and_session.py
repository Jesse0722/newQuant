import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from app.routers.pools import _rt_close_and_pct_chg
from app.services.buy_signal_service import _merge_rt_k_into_df
from app.services.trading_session import is_a_share_trading_session, shanghai_trade_date_str


class TestMergeRtK(unittest.TestCase):
    def test_merge_appends_converts_vol(self):
        hist = pd.DataFrame(
            [
                {
                    "trade_date": "20250327",
                    "open": 10.0,
                    "high": 10.5,
                    "low": 9.9,
                    "close": 10.2,
                    "pre_close": 10.0,
                    "pct_chg": 2.0,
                    "vol": 10000.0,
                    "amount": 5000.0,
                    "turnover_rate": 1.0,
                }
            ]
        )
        rt = {
            "ts_code": "000001.SZ",
            "pre_close": 10.2,
            "open": 10.2,
            "high": 10.4,
            "low": 10.1,
            "close": 10.35,
            "vol": 500000,
            "amount": 5_000_000,
        }
        out = _merge_rt_k_into_df(hist, rt, "20250328")
        self.assertEqual(len(out), 2)
        last = out.iloc[-1]
        self.assertEqual(str(last["trade_date"]), "20250328")
        self.assertAlmostEqual(float(last["vol"]), 5000.0, places=3)
        self.assertAlmostEqual(float(last["close"]), 10.35, places=4)

    def test_merge_overwrites_same_day(self):
        hist = pd.DataFrame(
            [
                {
                    "trade_date": "20250328",
                    "open": 10.0,
                    "high": 10.0,
                    "low": 10.0,
                    "close": 10.0,
                    "pre_close": 9.9,
                    "pct_chg": 1.0,
                    "vol": 1000.0,
                    "amount": 100.0,
                    "turnover_rate": None,
                }
            ]
        )
        rt = {"open": 10.1, "high": 10.2, "low": 9.9, "close": 10.15, "pre_close": 10.0, "vol": 200000, "amount": 2_000_000}
        out = _merge_rt_k_into_df(hist, rt, "20250328")
        self.assertEqual(len(out), 1)
        self.assertAlmostEqual(float(out.iloc[0]["vol"]), 2000.0)


class TestRtListQuote(unittest.TestCase):
    def test_close_from_pre_close(self):
        cl, pct = _rt_close_and_pct_chg({"close": 10.35, "pre_close": 10.2})
        self.assertAlmostEqual(cl, 10.35)
        self.assertAlmostEqual(pct, (10.35 / 10.2 - 1.0) * 100.0, places=4)

    def test_falls_back_to_pct_chg_field(self):
        cl, pct = _rt_close_and_pct_chg({"close": 10.0, "pct_chg": -1.5})
        self.assertAlmostEqual(cl, 10.0)
        self.assertAlmostEqual(pct, -1.5)

    def test_no_close(self):
        self.assertEqual(_rt_close_and_pct_chg({"pre_close": 10.0}), (None, None))


class TestTradingSession(unittest.TestCase):
    def test_saturday_off(self):
        sh = ZoneInfo("Asia/Shanghai")
        sat = datetime(2026, 3, 28, 10, 0, tzinfo=sh)
        self.assertFalse(is_a_share_trading_session(sat))

    def test_monday_morning_on(self):
        sh = ZoneInfo("Asia/Shanghai")
        d = datetime(2026, 3, 30, 10, 0, 0, tzinfo=sh)
        self.assertTrue(is_a_share_trading_session(d))

    def test_trade_date_str(self):
        sh = ZoneInfo("Asia/Shanghai")
        d = datetime(2026, 3, 30, 10, 0, 0, tzinfo=sh)
        self.assertEqual(shanghai_trade_date_str(d), "20260330")


if __name__ == "__main__":
    unittest.main()
