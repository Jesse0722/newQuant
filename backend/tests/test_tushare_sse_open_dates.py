from __future__ import annotations

import unittest
from unittest.mock import MagicMock

import pandas as pd

from app.services.tushare_adapter import TushareAdapter


class TestSseOpenDatesNormalization(unittest.TestCase):
    def test_cal_date_datetime_and_is_open_string(self):
        ad = TushareAdapter()
        ad._pro = MagicMock()
        ad._pro.trade_cal.return_value = pd.DataFrame(
            {
                "cal_date": pd.to_datetime(["2026-03-27", "2026-03-28", "2026-03-29"]),
                "is_open": ["1", "0", "1"],
            }
        )
        out = ad.get_sse_open_dates("20260329")
        self.assertEqual(out, ["20260327", "20260329"])


if __name__ == "__main__":
    unittest.main()
