from __future__ import annotations

import unittest
from unittest.mock import patch

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


class TestLimitMarketBoardThsConcepts(unittest.TestCase):
    def setUp(self):
        lb._cache.clear()
        lb._ths_stock_concept_map_mem = None
        lb._ths_stock_concept_map_mtime = 0.0

    @patch.object(lb, "_maybe_schedule_ths_map_refresh")
    @patch.object(
        lb,
        "_get_ths_stock_concept_map_resolved",
        return_value={"000001.SZ": ["测试概念A", "测试概念B"]},
    )
    def test_payload_enriches_ladder_with_ths_concepts(self, _mock_map, _mock_sched):
        payload = lb.get_limit_market_board_payload(trade_date="20250328", adapter=FakeThsAdapter())
        self.assertEqual(len(payload["ladder"]), 1)
        concepts = payload["ladder"][0].get("ths_concepts")
        self.assertIsInstance(concepts, list)
        self.assertEqual(concepts, ["测试概念A", "测试概念B"])


class FakeBuildAdapter:
    """验证 build 走 ths_member(ts_code=板块指数)，不传 con_code。"""

    def get_ths_index(self, **kwargs) -> pd.DataFrame:
        return pd.DataFrame([{"ts_code": "885001.TI", "name": "概念甲"}])

    def get_ths_member(self, ts_code=None, con_code=None) -> pd.DataFrame:
        assert con_code is None
        assert ts_code == "885001.TI"
        return pd.DataFrame([{"ts_code": "885001.TI", "con_code": "000001.SZ", "con_name": "x"}])


class TestBuildThsConceptMap(unittest.TestCase):
    def test_build_uses_member_by_index_ts_code(self):
        m = lb.build_ths_stock_concept_map(FakeBuildAdapter())
        self.assertEqual(m.get("000001.SZ"), ["概念甲"])


if __name__ == "__main__":
    unittest.main()
