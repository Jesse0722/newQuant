from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

from app.services import limit_market_board_service as lmb
from app.services.limit_market_board_service import get_limit_market_board_payload


class TestLimitMarketBoardService(unittest.TestCase):
    def setUp(self):
        lmb._cache.clear()

    @patch.object(lmb, "_enrich_ladder_industry", lambda ladder: None)
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
                {"ts_code": "000001.SZ", "name": "P", "trade_date": "20250328", "nums": "2", "industry": "A"},
                {"ts_code": "000002.SZ", "name": "Q", "trade_date": "20250328", "nums": "11", "industry": "B"},
                {"ts_code": "000003.SZ", "name": "R", "trade_date": "20250328", "nums": "11", "industry": "B"},
            ]
        )

        with unittest.mock.patch.object(lmb, "resolve_dashboard_trade_date", return_value="20250328"):
            out = get_limit_market_board_payload(trade_date=None, adapter=adapter)

        ranks = [r["rank"] for r in out["sectors"]]
        self.assertEqual(ranks, ["1", "2", "x"])
        ladder_nums = [r["nums"] for r in out["ladder"]]
        self.assertEqual(ladder_nums, ["11", "11", "2"])
        b_sector = next(r for r in out["sectors"] if r["name"] == "B")
        self.assertEqual([s["name"] for s in b_sector["stocks"]], ["Q", "R"])

    @patch.object(lmb, "_enrich_ladder_industry", lambda ladder: None)
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

    def test_akshare_limit_down_reads_consecutive_limit_field(self):
        fake_ak = types.SimpleNamespace(
            stock_zt_pool_dtgc_em=lambda date: pd.DataFrame(
                [
                    {"代码": "600208", "名称": "衢州发展", "所属行业": "房地产开发", "涨跌幅": -10.0, "连续跌停": 4},
                    {"代码": "603121", "名称": "华培动力", "所属行业": "汽车零部", "涨跌幅": -10.0, "连续跌停": 2},
                ]
            )
        )

        with patch.dict(sys.modules, {"akshare": fake_ak}):
            df = lmb._fetch_limit_down_from_akshare("20260521")

        ladder = lmb._build_outflow_ladder(df, "20260521")
        self.assertEqual([x["nums"] for x in ladder], ["4", "2"])
        sectors = lmb._build_outflow_sectors(df)
        self.assertEqual(sectors[0]["stocks"][0]["name"], "衢州发展")

    def test_ths_hot_payload_parses_stock_and_sector_rankings(self):
        def fake_json(path, params):
            if path == "stock":
                return {
                    "data": {
                        "stock_list": [
                            {
                                "order": 1,
                                "code": "000001",
                                "market": 33,
                                "name": "平安银行",
                                "rate": "12345",
                                "rise_and_fall": 1.23,
                                "hot_rank_chg": 2,
                                "tag": {"concept_tag": ["银行"], "popularity_tag": "持续上榜"},
                            }
                        ]
                    }
                }
            if path == "plate" and params.get("type") == "concept":
                return {"data": {"plate_list": [{"order": 1, "code": "885001", "name": "机器人", "rate": "200", "rise_and_fall": 2.0}]}}
            return {"data": {"plate_list": [{"order": 1, "code": "881001", "name": "半导体", "rate": "300", "rise_and_fall": -1.0}]}}

        with patch.object(lmb, "_fetch_ths_json", side_effect=fake_json):
            payload = lmb._fetch_ths_hot_payload()

        self.assertEqual(payload["stocks"][0]["ts_code"], "000001.SZ")
        self.assertEqual(payload["stocks"][0]["concept_tags"], ["银行"])
        self.assertEqual(payload["sectors"][0]["name"], "半导体")
        self.assertEqual(payload["sectors"][0]["type_label"], "行业")


if __name__ == "__main__":
    unittest.main()
