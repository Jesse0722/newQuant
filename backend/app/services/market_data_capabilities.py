"""Static market-data provider capabilities.

This module is intentionally side-effect free: it does not call providers, switch the
global router, or inspect credentials beyond whether the configured Tushare token is
present.  Sync jobs can use ``configured_providers`` once at task start to retain a
stable snapshot even if the process-wide provider router is switched later.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any

from app.config import TUSHARE_TOKEN


@dataclass(frozen=True)
class ProviderCapabilities:
    """Capabilities and raw units exposed by one concrete provider."""

    name: str
    history_by_date: bool
    history_by_symbol: bool
    snapshot_by_date: bool
    markets: tuple[str, ...]
    volume_unit: str | None
    amount_unit: str | None
    requires_credentials: bool
    enabled: bool
    reliable_pre_close: bool


_KNOWN_CAPABILITIES: dict[str, dict[str, Any]] = {
    "TushareAdapter": {
        "name": "tushare",
        "history_by_date": True,
        "history_by_symbol": True,
        "snapshot_by_date": False,
        "markets": ("SH", "SZ", "BJ"),
        "volume_unit": "lot",
        "amount_unit": "thousand_cny",
        "requires_credentials": True,
        "reliable_pre_close": True,
    },
    "BaoStockAdapter": {
        "name": "baostock",
        "history_by_date": False,
        "history_by_symbol": True,
        "snapshot_by_date": False,
        # BaoStock's A-share coverage is conservatively declared as SH/SZ.
        "markets": ("SH", "SZ"),
        "volume_unit": "share",
        "amount_unit": "cny",
        "requires_credentials": False,
        "reliable_pre_close": True,
    },
    "TencentAdapter": {
        "name": "tencent",
        "history_by_date": False,
        "history_by_symbol": True,
        "snapshot_by_date": False,
        "markets": ("SH", "SZ", "BJ"),
        "volume_unit": "lot",
        "amount_unit": None,
        "requires_credentials": False,
        # Tencent derives pre_close from the prior returned row, so the first row
        # in a requested window has no reliable pre_close.
        "reliable_pre_close": False,
    },
    "AkshareAdapter": {
        "name": "akshare",
        "history_by_date": False,
        "history_by_symbol": True,
        # get_daily_by_date is a same-day spot snapshot, not historical bulk data.
        "snapshot_by_date": True,
        "markets": ("SH", "SZ", "BJ"),
        "volume_unit": "lot",
        "amount_unit": "cny",
        "requires_credentials": False,
        "reliable_pre_close": True,
    },
}


def _explicit_capabilities(provider: object) -> ProviderCapabilities:
    """Read an explicit capability declaration from an otherwise unknown provider."""

    if not hasattr(provider, "capabilities"):
        raise ValueError(f"未知行情数据源且未声明 capabilities: {type(provider).__name__}")
    value = getattr(provider, "capabilities")
    if callable(value):
        value = value()
    if isinstance(value, ProviderCapabilities):
        return value
    if isinstance(value, Mapping):
        data = dict(value)
        if "markets" in data:
            data["markets"] = tuple(data["markets"])
        try:
            return ProviderCapabilities(**data)
        except (TypeError, ValueError) as exc:
            raise ValueError("显式 capabilities 字段不完整或格式错误") from exc
    raise ValueError("显式 capabilities 必须是 ProviderCapabilities 或映射")


def provider_capabilities(provider: object) -> ProviderCapabilities:
    """Return the declared capabilities of one leaf provider without probing it."""

    class_name = type(provider).__name__
    declaration = _KNOWN_CAPABILITIES.get(class_name)
    if declaration is None:
        return _explicit_capabilities(provider)
    data = dict(declaration)
    data["enabled"] = bool(TUSHARE_TOKEN) if class_name == "TushareAdapter" else True
    return ProviderCapabilities(**data)


def configured_providers(provider_or_router: object) -> tuple[object, ...]:
    """Expand a router/composite into a stable tuple of concrete provider instances."""

    class_name = type(provider_or_router).__name__
    if class_name == "ProviderRouter":
        return configured_providers(getattr(provider_or_router, "provider"))
    if class_name == "CompositeAdapter":
        snapshot = tuple(getattr(provider_or_router, "providers"))
        leaves: list[object] = []
        for provider in snapshot:
            leaves.extend(configured_providers(provider))
        return tuple(leaves)
    return (provider_or_router,)


def capability_report(provider_or_router: object) -> list[dict[str, Any]]:
    """Return a JSON-serializable report for the currently configured provider leaves."""

    report: list[dict[str, Any]] = []
    for provider in configured_providers(provider_or_router):
        item = asdict(provider_capabilities(provider))
        item["markets"] = list(item["markets"])
        report.append(item)
    return report
