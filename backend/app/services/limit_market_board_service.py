"""涨停情绪仪表盘：limit_cpt_list + limit_step 聚合与短 TTL 缓存。"""
from __future__ import annotations

import math
import threading
import time as time_module
from typing import Any

import pandas as pd

from app.services.trade_date_resolver import resolve_dashboard_trade_date
from app.services.tushare_adapter import MarketDataProvider, tushare_adapter

DASHBOARD_LIMIT_BOARD_CACHE_TTL_SEC = 60

_cache_lock = threading.Lock()
# trade_date -> (expires_at_epoch, (sectors, ladder))
_cache: dict[str, tuple[float, tuple[list[dict], list[dict]]]] = {}


def _parse_rank(s: Any) -> tuple[int, int]:
    """(tier, rank_int)：tier 0 表示可参与升序，1 表示无有效 rank 排后。"""
    if s is None or (isinstance(s, float) and math.isnan(s)):
        return (1, 999999)
    try:
        return (0, int(str(s).strip()))
    except (ValueError, TypeError):
        return (1, 999999)


def _sector_sort_key(row: dict) -> tuple:
    tier, rnk = _parse_rank(row.get("rank"))
    up = row.get("up_nums")
    pct = row.get("pct_chg")
    try:
        up_n = -float(up) if up is not None and pd.notna(up) else 0.0
    except (TypeError, ValueError):
        up_n = 0.0
    try:
        pct_n = -float(pct) if pct is not None and pd.notna(pct) else 0.0
    except (TypeError, ValueError):
        pct_n = 0.0
    return (tier, rnk, up_n, pct_n)


def _df_to_records(df: pd.DataFrame) -> list[dict]:
    if df is None or df.empty:
        return []
    records: list[dict] = []
    for _, row in df.iterrows():
        rec: dict[str, Any] = {}
        for c in df.columns:
            v = row[c]
            if pd.isna(v):
                rec[c] = None
            elif hasattr(v, "item"):
                try:
                    rec[c] = v.item()
                except (ValueError, AttributeError):
                    rec[c] = v
            else:
                rec[c] = v
        records.append(rec)
    return records


def _sort_sectors(records: list[dict]) -> list[dict]:
    return sorted(records, key=_sector_sort_key)


def _ladder_sort_key(row: dict) -> tuple:
    nums = row.get("nums")
    try:
        n = int(str(nums).strip())
    except (ValueError, TypeError):
        n = -1
    ts = str(row.get("ts_code") or "")
    return (-n, ts)


def _sort_ladder(records: list[dict]) -> list[dict]:
    return sorted(records, key=_ladder_sort_key)


def get_limit_market_board_payload(
    trade_date: str | None = None,
    adapter: MarketDataProvider | None = None,
) -> dict:
    ad = adapter or tushare_adapter
    if trade_date:
        resolved_by = "query"
        td = trade_date
    else:
        resolved_by = "default"
        td = resolve_dashboard_trade_date(adapter=ad)

    now = time_module.time()
    with _cache_lock:
        hit = _cache.get(td)
        if hit and hit[0] > now:
            sectors, ladder = hit[1]
            return {
                "trade_date": td,
                "resolved_by": resolved_by,
                "sectors": sectors,
                "ladder": ladder,
            }

    df_s = ad.get_limit_cpt_list(td)
    df_l = ad.get_limit_step(td)
    sectors = _sort_sectors(_df_to_records(df_s))
    ladder = _sort_ladder(_df_to_records(df_l))
    payload_body = (sectors, ladder)

    with _cache_lock:
        _cache[td] = (now + DASHBOARD_LIMIT_BOARD_CACHE_TTL_SEC, payload_body)

    return {
        "trade_date": td,
        "resolved_by": resolved_by,
        "sectors": sectors,
        "ladder": ladder,
    }
