from __future__ import annotations

import pandas as pd
import pytest

from app.services import tushare_adapter as adapters
from app.services.source_identity import IDENTITY_ATTR, frame_identities
from app.services.quote_repair_source_service import fetch_repair_snapshot
from app.services.market_data_capabilities import provider_capabilities


def test_baostock_wrong_raw_code_is_rejected_before_request_code_assignment(monkeypatch):
    provider = adapters.BaoStockAdapter()
    monkeypatch.setattr(provider, "_require_client", lambda: object())
    monkeypatch.setattr(provider, "_query_df", lambda *args: pd.DataFrame([{
        "date": "2026-11-10", "code": "sz.000002", "close": 10,
    }]))
    with pytest.raises(ValueError, match="原始证券"):
        provider.get_daily("000001.SZ")


def test_repair_rejects_adapter_filled_code_without_raw_identity(monkeypatch):
    provider = adapters.BaoStockAdapter()
    monkeypatch.setattr(provider, "get_daily", lambda **kwargs: pd.DataFrame([{
        "ts_code": kwargs["ts_code"], "trade_date": "20261110", "open": 10, "high": 10,
        "low": 10, "close": 10, "pre_close": 10, "pct_chg": 0, "vol": 100, "amount": 1000,
    }]))
    result = fetch_repair_snapshot(provider, provider_capabilities(provider), ["20261110"], ["000001.SZ"], {}, request_interval=0)
    assert result["outcome"] == "failed" and result["rows"] == []


def eastmoney_response(code="000001", market=0):
    return {"data": {"code": code, "market": market, "name": "fixture",
                     "klines": ["2026-11-10,10,10,11,9,100,100000,20,0,0,2"]}}


def test_akshare_repair_uses_raw_echo_instead_of_sdk_synthetic_code(monkeypatch):
    calls = []
    class Response:
        def raise_for_status(self):
            pass
        def json(self):
            return eastmoney_response()
    monkeypatch.setattr(adapters.requests, "get", lambda *a, **kw: (calls.append(kw), Response())[1])
    provider = adapters.AkshareAdapter()
    frame = provider.get_daily_for_repair("000001.SZ", "20261110", "20261110")
    assert frame_identities(frame, "akshare", "000001.SZ")["20261110"]["raw_code"] == "000001"
    assert calls[0]["params"]["fqt"] == "0" and calls[0]["timeout"] > 0
    result = fetch_repair_snapshot(provider, provider_capabilities(provider), ["20261110"], ["000001.SZ"], {}, request_interval=0)
    assert result["outcome"] == "success"
    assert result["rows"][0]["source_identity"]["raw_market"] == "0"


@pytest.mark.parametrize("code,market", [("000002", 0), ("000001", 1), ("600000", 0)])
def test_akshare_wrong_raw_identity_fails_closed(monkeypatch, code, market):
    class Response:
        def raise_for_status(self):
            pass
        def json(self):
            return eastmoney_response(code, market)
    monkeypatch.setattr(adapters.requests, "get", lambda *a, **kw: Response())
    with pytest.raises(ValueError):
        adapters.AkshareAdapter().get_daily_for_repair("000001.SZ")


def test_tushare_raw_identity_is_preserved_and_mismatch_rejected(monkeypatch):
    class Pro:
        def daily(self, **kwargs):
            return pd.DataFrame([{"ts_code": "000001.SZ", "trade_date": "20261110", "close": 10}])
    provider = adapters.TushareAdapter()
    provider._pro = Pro()
    frame = provider.get_daily("000001.SZ")
    assert frame.attrs[IDENTITY_ATTR]["provider"] == "tushare"
    assert frame_identities(frame, "tushare", "000001.SZ")
    with pytest.raises(ValueError):
        provider.get_daily("000002.SZ")
