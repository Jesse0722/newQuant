from __future__ import annotations

import unittest

import pandas as pd

import app.services.limit_market_board_service as lb


class FakeThsAdapter:
    def get_limit_cpt_list(self, trade_date: str) -> pd.DataFrame:
        return pd.DataFrame()

    def get_limit_step(self, trade_date: str) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "ts_code": "000001.SZ",
                    "name": "平安银行",
                    "trade_date": trade_date,
                    "nums": "1",
                }
            ]
        )

    def get_ths_index(self, **kwargs) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {"ts_code": "885001.TI", "name": "测试概念A"},
                {"ts_code": "885002.TI", "name": "测试概念B"},
            ]
        )

    def get_ths_member(self, ts_code=None, con_code=None) -> pd.DataFrame:
        assert con_code == "000001.SZ"
        return pd.DataFrame(
            [
                {"ts_code": "885002.TI", "con_code": "000001.SZ", "con_name": "平安银行"},
                {"ts_code": "885001.TI", "con_code": "000001.SZ", "con_name": "平安银行"},
            ]
        )


class TestLimitMarketBoardThsConcepts(unittest.TestCase):
    def setUp(self):
        lb._ths_index_map_cache = None
        lb._stock_concept_cache.clear()
        lb._cache.clear()

    def test_payload_enriches_ladder_with_ths_concepts(self):
        payload = lb.get_limit_market_board_payload(trade_date="20250328", adapter=FakeThsAdapter())
        self.assertEqual(len(payload["ladder"]), 1)
        concepts = payload["ladder"][0].get("ths_concepts")
        self.assertIsInstance(concepts, list)
        self.assertEqual(concepts, ["测试概念A", "测试概念B"])


if __name__ == "__main__":
    unittest.main()
