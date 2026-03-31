import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from app.services.buy_signal_service import (
    _merge_rt_k_into_df,
    _apply_intraday_reliability_state,
    INTRADAY_PROVISIONAL,
    INTRADAY_CONFIRMED,
)
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


class TestIntradayReliability(unittest.TestCase):
    def test_intraday_turns_provisional_then_confirmed(self):
        signals = [{"ts_code": "000001.SZ", "signal_status": "triggered", "signal_score": 80}]
        p1, c1 = _apply_intraday_reliability_state(
            signals, "two_phase", "pool-a", "20260331", True, 2
        )
        self.assertEqual((p1, c1), (1, 0))
        self.assertEqual(signals[0]["signal_status"], INTRADAY_PROVISIONAL)

        signals2 = [{"ts_code": "000001.SZ", "signal_status": "triggered", "signal_score": 80}]
        p2, c2 = _apply_intraday_reliability_state(
            signals2, "two_phase", "pool-a", "20260331", True, 2
        )
        self.assertEqual((p2, c2), (0, 1))
        self.assertEqual(signals2[0]["signal_status"], INTRADAY_CONFIRMED)

    def test_post_close_directly_confirmed(self):
        signals = [{"ts_code": "000001.SZ", "signal_status": "triggered", "signal_score": 80}]
        p, c = _apply_intraday_reliability_state(
            signals, "two_phase", "pool-a", "20260331", False, 2
        )
        self.assertEqual((p, c), (0, 1))
        self.assertEqual(signals[0]["signal_status"], INTRADAY_CONFIRMED)


if __name__ == "__main__":
    unittest.main()
