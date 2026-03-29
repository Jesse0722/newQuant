import unittest
from unittest.mock import MagicMock

import pandas as pd

from app.services import limit_market_board_service as lmb
from app.services.limit_market_board_service import get_limit_market_board_payload


class TestLimitMarketBoardService(unittest.TestCase):
    def setUp(self):
        lmb._cache.clear()

    def test_sort_sectors_and_ladder(self):
        adapter = MagicMock()
        adapter.get_sse_open_dates.return_value = ["20250327", "20250328"]
        adapter.get_limit_cpt_list.return_value = pd.DataFrame(
            [
                {"ts_code": "881001.TI", "name": "A", "trade_date": "20250328", "rank": "2", "up_nums": 5, "pct_chg": 1.0},
                {"ts_code": "881002.TI", "name": "B", "trade_date": "20250328", "rank": "1", "up_nums": 10, "pct_chg": 2.0},
                {"ts_code": "881003.TI", "name": "C", "trade_date": "20250328", "rank": "x", "up_nums": 20, "pct_chg": 3.0},
            ]
        )
        adapter.get_limit_step.return_value = pd.DataFrame(
            [
                {"ts_code": "000001.SZ", "name": "P", "trade_date": "20250328", "nums": "2"},
                {"ts_code": "000002.SZ", "name": "Q", "trade_date": "20250328", "nums": "11"},
                {"ts_code": "000003.SZ", "name": "R", "trade_date": "20250328", "nums": "11"},
            ]
        )

        with unittest.mock.patch.object(lmb, "resolve_dashboard_trade_date", return_value="20250328"):
            out = get_limit_market_board_payload(trade_date=None, adapter=adapter)

        ranks = [r["rank"] for r in out["sectors"]]
        self.assertEqual(ranks, ["1", "2", "x"])
        ladder_nums = [r["nums"] for r in out["ladder"]]
        self.assertEqual(ladder_nums, ["11", "11", "2"])

    def test_cache_same_trade_date(self):
        adapter = MagicMock()
        adapter.get_sse_open_dates.return_value = ["20250327", "20250328"]
        adapter.get_limit_cpt_list.return_value = pd.DataFrame(
            [{"ts_code": "881001.TI", "name": "A", "trade_date": "20250328", "rank": "1", "up_nums": 1, "pct_chg": 1.0}]
        )
        adapter.get_limit_step.return_value = pd.DataFrame()

        lmb._cache.clear()
        out1 = get_limit_market_board_payload(trade_date="20250328", adapter=adapter)
        self.assertEqual(out1["resolved_by"], "query")
        out2 = get_limit_market_board_payload(trade_date="20250328", adapter=adapter)
        self.assertEqual(adapter.get_limit_cpt_list.call_count, 1)
        self.assertEqual(out2["resolved_by"], "query")


if __name__ == "__main__":
    unittest.main()
