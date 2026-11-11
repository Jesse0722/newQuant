from __future__ import annotations

from dataclasses import replace

import pandas as pd
import pytest

from app.services import tushare_adapter as adapter_module
from app.services.market_data_capabilities import ProviderCapabilities
from app.services.provider_daily_normalization import (
    CANONICAL_DAILY_VERSION,
    CANONICAL_VERSION_ATTR,
    SOURCE_PROVIDER_ATTR,
    UNAVAILABLE_FIELDS_ATTR,
    normalize_provider_daily,
)
from app.services.tushare_adapter import (
    AkshareAdapter,
    BaoStockAdapter,
    CompositeAdapter,
    ProviderRouter,
    TencentAdapter,
    TushareAdapter,
)


@pytest.mark.parametrize(
    "provider,vol,amount,expected_vol,expected_amount",
    [
        (BaoStockAdapter(), 1000, 20000, 10, 20),
        (AkshareAdapter(), 10, 20000, 10, 20),
        (TushareAdapter(), 10, 20, 10, 20),
        (TencentAdapter(), 10, 999, 10, None),
    ],
)
def test_all_known_sources_use_daily_quote_units(
    provider,
    vol,
    amount,
    expected_vol,
    expected_amount,
):
    raw = pd.DataFrame([{"vol": vol, "amount": amount}])

    result = normalize_provider_daily(raw, provider)

    assert result.iloc[0]["vol"] == expected_vol
    if expected_amount is None:
        assert result.iloc[0]["amount"] is None
        assert "amount" in result.attrs[UNAVAILABLE_FIELDS_ATTR]
    else:
        assert result.iloc[0]["amount"] == expected_amount
    assert result.attrs[CANONICAL_VERSION_ATTR] == CANONICAL_DAILY_VERSION


def test_normalization_is_idempotent_and_preserves_nulls():
    raw = pd.DataFrame([{"vol": 1000, "amount": 20000}, {"vol": None, "amount": None}])
    once = normalize_provider_daily(raw, BaoStockAdapter())

    twice = normalize_provider_daily(once, BaoStockAdapter())

    assert twice is once
    assert twice.iloc[0]["vol"] == 10
    assert twice.iloc[0]["amount"] == 20
    assert pd.isna(twice.iloc[1]["vol"])
    assert pd.isna(twice.iloc[1]["amount"])


def test_composite_normalizes_selected_leaf_and_router_does_not_rescale(monkeypatch):
    first = BaoStockAdapter()
    second = AkshareAdapter()
    monkeypatch.setattr(first, "get_daily", lambda **kwargs: pd.DataFrame())
    monkeypatch.setattr(
        second,
        "get_daily",
        lambda **kwargs: pd.DataFrame([{"ts_code": kwargs["ts_code"], "vol": 10, "amount": 20000}]),
    )
    composite = CompositeAdapter([first, second])
    router = ProviderRouter("akshare")
    router.provider = composite

    result = router.get_daily("000001.SZ")

    assert result.iloc[0]["vol"] == 10
    assert result.iloc[0]["amount"] == 20
    assert result.attrs[SOURCE_PROVIDER_ATTR] == "akshare"


def test_router_normalizes_a_raw_leaf(monkeypatch):
    provider = BaoStockAdapter()
    monkeypatch.setattr(
        provider,
        "get_daily",
        lambda **kwargs: pd.DataFrame([{"vol": 1000, "amount": 20000}]),
    )
    router = ProviderRouter("baostock")
    router.provider = provider

    result = router.get_daily("000001.SZ")

    assert result.iloc[0]["vol"] == 10
    assert result.iloc[0]["amount"] == 20
    assert result.attrs[SOURCE_PROVIDER_ATTR] == "baostock"


def test_unknown_units_are_unavailable_not_copied():
    caps = ProviderCapabilities(
        name="future",
        history_by_date=False,
        history_by_symbol=True,
        snapshot_by_date=False,
        markets=("SH",),
        volume_unit="unknown",
        amount_unit="unknown",
        requires_credentials=False,
        enabled=True,
        reliable_pre_close=True,
    )

    class FutureProvider:
        capabilities = replace(caps)

    result = normalize_provider_daily(pd.DataFrame([{"vol": 1, "amount": 2}]), FutureProvider())

    assert result.iloc[0]["vol"] is None
    assert result.iloc[0]["amount"] is None
    assert result.attrs[UNAVAILABLE_FIELDS_ATTR] == ("vol", "amount")


def test_empty_composite_result_is_marked_canonical(monkeypatch):
    provider = BaoStockAdapter()
    monkeypatch.setattr(provider, "get_daily", lambda **kwargs: pd.DataFrame())

    result = CompositeAdapter([provider]).get_daily("000001.SZ")

    assert result.empty
    assert result.attrs[CANONICAL_VERSION_ATTR] == CANONICAL_DAILY_VERSION


def test_akshare_daily_basic_preserves_symbol_identity(monkeypatch):
    frame = pd.DataFrame([{"日期": "2026-10-08", "换手率": 1.23}])
    monkeypatch.setattr(adapter_module, "_call_with_retry", lambda *args, **kwargs: frame)

    result = AkshareAdapter().get_daily_basic("000001.SZ")

    assert result["ts_code"].tolist() == ["000001.SZ"]
    assert result["turnover_rate"].tolist() == [1.23]
