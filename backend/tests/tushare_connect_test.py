from __future__ import annotations

import os

import pytest
import tushare as ts


@pytest.mark.integration
def test_tushare_connectivity() -> None:
    token = (os.getenv("TUSHARE_TOKEN") or "").strip()
    api_url = (os.getenv("TUSHARE_API_URL") or "").strip()

    if not token:
        pytest.skip("TUSHARE_TOKEN not configured")

    pro = ts.pro_api(token)
    pro._DataApi__token = token
    if api_url:
        pro._DataApi__http_url = api_url

    df = pro.daily(ts_code="000001.SZ", start_date="20240101", end_date="20240131")

    assert df is not None
