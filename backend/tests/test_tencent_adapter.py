from __future__ import annotations

import json
import subprocess

from app.services.tushare_adapter import TencentAdapter


class _Completed:
    def __init__(self, payload: dict):
        self.stdout = json.dumps(payload, ensure_ascii=False)
        self.stderr = ""
        self.returncode = 0


def test_tencent_adapter_daily_and_basic(monkeypatch):
    payload = {
        "code": 0,
        "data": {
            "sz000062": {
                "day": [
                    ["2026-04-16", "28.00", "28.62", "29.00", "27.51", "463583.000"],
                    ["2026-04-17", "29.50", "29.76", "31.48", "29.48", "852582.000"],
                ],
                "qt": {
                    "sz000062": ["51", "深圳华强"] + [""] * 70 + ["1044900077", "1045909322"],
                },
            }
        },
    }

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: _Completed(payload),
    )

    ad = TencentAdapter()
    daily = ad.get_daily("000062.SZ", start_date="20260416", end_date="20260417")
    basic = ad.get_daily_basic("000062.SZ", start_date="20260416", end_date="20260417")
    stock_basic = ad.get_stock_basic("000062.SZ")

    assert list(daily["trade_date"]) == ["20260417", "20260416"]
    assert round(float(daily.iloc[0]["pct_chg"]), 4) == round((29.76 - 28.62) / 28.62 * 100.0, 4)
    assert round(float(basic.iloc[0]["turnover_rate"]), 4) == round(852582.0 / 104490.0077, 4)
    assert round(float(stock_basic.iloc[0]["float_share"]), 4) == round(1044900077 / 10000.0, 4)
    assert stock_basic.iloc[0]["name"] == "深圳华强"
