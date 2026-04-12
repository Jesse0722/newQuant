from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.dashboard import router
from app.services.trade_date_resolver import TradeDateResolutionError


class TestDashboardLimitBoardApi(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(router)
        self.client = TestClient(app)

    def test_success(self):
        body = {
            "trade_date": "20250328",
            "resolved_by": "default",
            "sectors": [],
            "ladder": [],
        }
        with patch("app.routers.dashboard.get_limit_market_board_payload", return_value=body):
            r = self.client.get("/api/dashboard")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), body)

    def test_trade_date_resolution_failed(self):
        with patch(
            "app.routers.dashboard.get_limit_market_board_payload",
            side_effect=TradeDateResolutionError("no calendar"),
        ):
            r = self.client.get("/api/dashboard")
        self.assertEqual(r.status_code, 503)
        d = r.json()["detail"]
        self.assertEqual(d["code"], "TRADE_DATE_RESOLUTION_FAILED")

    def test_invalid_trade_date_query(self):
        r = self.client.get("/api/dashboard?trade_date=abcdefgh")
        self.assertEqual(r.status_code, 422)

    def test_tushare_error_502(self):
        with patch(
            "app.routers.dashboard.get_limit_market_board_payload",
            side_effect=ValueError("您的积分不足"),
        ):
            r = self.client.get("/api/dashboard")
        self.assertEqual(r.status_code, 502)
        self.assertEqual(r.json()["detail"]["code"], "TUSHARE_ERROR")


if __name__ == "__main__":
    unittest.main()
