"""Normalize provider daily bars at normal business-write boundaries.

Leaf adapters intentionally remain raw because the repair/audit workflow needs to
retain source units.  Frames marked by this module are safe to pass through again.
"""

from __future__ import annotations

import pandas as pd

from app.services.market_data_capabilities import provider_capabilities


CANONICAL_DAILY_VERSION = "daily_quote-lot-thousand_cny-v1"
CANONICAL_VERSION_ATTR = "newquant_daily_quote_canonical_version"
SOURCE_PROVIDER_ATTR = "newquant_daily_quote_source_provider"
SOURCE_UNITS_ATTR = "newquant_daily_quote_source_units"
UNAVAILABLE_FIELDS_ATTR = "newquant_daily_quote_unavailable_fields"


def _provider_units(provider: object) -> tuple[str, str | None, str | None]:
    try:
        capabilities = provider_capabilities(provider)
        return capabilities.name, capabilities.volume_unit, capabilities.amount_unit
    except ValueError:
        # A caller can still safely pass an unknown provider: ambiguous units are
        # made unavailable instead of being copied into canonical columns.
        return type(provider).__name__.lower(), None, None


def _normalize_unit_column(
    frame: pd.DataFrame,
    field: str,
    source_unit: str | None,
    divisors: dict[str, float],
    unavailable: list[str],
) -> None:
    if field not in frame.columns:
        return
    divisor = divisors.get(source_unit or "")
    if divisor is None:
        frame[field] = None
        unavailable.append(field)
        return
    values = pd.to_numeric(frame[field], errors="coerce")
    normalized = values / divisor
    # Object dtype keeps database nulls as None instead of silently converting
    # them to IEEE NaN during the unit conversion.
    frame[field] = normalized.astype(object).where(normalized.notna(), None)


def normalize_provider_daily(frame: pd.DataFrame | None, provider: object) -> pd.DataFrame:
    """Return daily bars in DailyQuote units (lot, thousand CNY), once only."""

    if frame is None:
        frame = pd.DataFrame()
    if frame.attrs.get(CANONICAL_VERSION_ATTR) == CANONICAL_DAILY_VERSION:
        return frame

    out = frame.copy()
    source_name, volume_unit, amount_unit = _provider_units(provider)
    unavailable: list[str] = []
    _normalize_unit_column(out, "vol", volume_unit, {"share": 100.0, "lot": 1.0}, unavailable)
    _normalize_unit_column(
        out,
        "amount",
        amount_unit,
        {"cny": 1000.0, "thousand_cny": 1.0},
        unavailable,
    )
    out.attrs.update(
        {
            CANONICAL_VERSION_ATTR: CANONICAL_DAILY_VERSION,
            SOURCE_PROVIDER_ATTR: source_name,
            SOURCE_UNITS_ATTR: {"vol": volume_unit, "amount": amount_unit},
            UNAVAILABLE_FIELDS_ATTR: tuple(unavailable),
            "newquant_daily_quote_units": {"vol": "lot", "amount": "thousand_cny"},
        }
    )
    return out
