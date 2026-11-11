from __future__ import annotations

import json
from dataclasses import FrozenInstanceError

import pytest

from app.services import market_data_capabilities as capability_module
from app.services.market_data_capabilities import (
    ProviderCapabilities,
    capability_report,
    configured_providers,
    provider_capabilities,
)
from app.services.tushare_adapter import (
    AkshareAdapter,
    BaoStockAdapter,
    CompositeAdapter,
    ProviderRouter,
    TencentAdapter,
    TushareAdapter,
)


def test_known_provider_capability_declarations(monkeypatch):
    monkeypatch.setattr(capability_module, "TUSHARE_TOKEN", "configured-token")

    tushare = provider_capabilities(TushareAdapter())
    assert tushare == ProviderCapabilities(
        name="tushare",
        history_by_date=True,
        history_by_symbol=True,
        snapshot_by_date=False,
        markets=("SH", "SZ", "BJ"),
        volume_unit="lot",
        amount_unit="thousand_cny",
        requires_credentials=True,
        enabled=True,
        reliable_pre_close=True,
    )

    baostock = provider_capabilities(BaoStockAdapter())
    assert baostock.markets == ("SH", "SZ")
    assert baostock.history_by_symbol and not baostock.history_by_date
    assert (baostock.volume_unit, baostock.amount_unit) == ("share", "cny")
    assert baostock.reliable_pre_close

    tencent = provider_capabilities(TencentAdapter())
    assert tencent.history_by_symbol and not tencent.history_by_date
    assert tencent.amount_unit is None
    assert not tencent.reliable_pre_close

    akshare = provider_capabilities(AkshareAdapter())
    assert akshare.snapshot_by_date and not akshare.history_by_date
    assert (akshare.volume_unit, akshare.amount_unit) == ("lot", "cny")


def test_tushare_is_disabled_without_configured_credentials(monkeypatch):
    monkeypatch.setattr(capability_module, "TUSHARE_TOKEN", "")
    capabilities = provider_capabilities(TushareAdapter())
    assert capabilities.requires_credentials
    assert not capabilities.enabled


def test_configured_providers_expands_composite_and_snapshots_sources():
    first = TencentAdapter()
    second = BaoStockAdapter()
    composite = CompositeAdapter([first, second])
    router = ProviderRouter("tencent")
    router.provider = composite

    snapshot = configured_providers(router)
    assert snapshot == (first, second)

    # Switching the mutable router after task start must not mutate the snapshot.
    router.provider = AkshareAdapter()
    assert snapshot == (first, second)
    assert configured_providers(router)[0].__class__ is AkshareAdapter


def test_configured_providers_accepts_a_leaf():
    provider = BaoStockAdapter()
    assert configured_providers(provider) == (provider,)


def test_unknown_provider_requires_explicit_capabilities():
    class UnknownProvider:
        pass

    with pytest.raises(ValueError, match="未声明 capabilities"):
        provider_capabilities(UnknownProvider())


def test_unknown_provider_can_supply_typed_or_mapping_capabilities():
    declared = ProviderCapabilities(
        name="future",
        history_by_date=False,
        history_by_symbol=True,
        snapshot_by_date=False,
        markets=("SH",),
        volume_unit="unknown",
        amount_unit="unknown",
        requires_credentials=False,
        enabled=True,
        reliable_pre_close=False,
    )

    class TypedProvider:
        capabilities = declared

    class MappingProvider:
        capabilities = {**declared.__dict__, "name": "mapping", "markets": ["SZ"]}

    assert provider_capabilities(TypedProvider()) is declared
    mapped = provider_capabilities(MappingProvider())
    assert mapped.name == "mapping"
    assert mapped.markets == ("SZ",)


def test_capability_report_is_ordered_and_json_serializable(monkeypatch):
    monkeypatch.setattr(capability_module, "TUSHARE_TOKEN", "")
    composite = CompositeAdapter([TencentAdapter(), TushareAdapter()])

    report = capability_report(composite)

    assert [item["name"] for item in report] == ["tencent", "tushare"]
    assert report[0]["markets"] == ["SH", "SZ", "BJ"]
    assert report[1]["enabled"] is False
    json.dumps(report, allow_nan=False)


def test_provider_capabilities_is_frozen():
    capabilities = provider_capabilities(BaoStockAdapter())
    with pytest.raises(FrozenInstanceError):
        capabilities.enabled = False
