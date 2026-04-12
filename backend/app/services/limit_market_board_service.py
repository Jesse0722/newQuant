"""涨停情绪仪表盘：limit_cpt_list + limit_step 聚合与短 TTL 缓存。"""
from __future__ import annotations

import math
import threading
import time as time_module
from typing import Any

import pandas as pd

from app.services.trade_date_resolver import resolve_dashboard_trade_date
from app.services.tushare_adapter import TushareAdapter, tushare_adapter

DASHBOARD_LIMIT_BOARD_CACHE_TTL_SEC = 60
THS_INDEX_MAP_TTL_SEC = 3600
STOCK_THS_CONCEPT_TTL_SEC = 1800

_cache_lock = threading.Lock()
# trade_date -> (expires_at_epoch, (sectors, ladder))
_cache: dict[str, tuple[float, tuple[list[dict], list[dict]]]] = {}

_ths_index_map_lock = threading.Lock()
# (expires_at, index_ts_code -> 概念名称)
_ths_index_map_cache: tuple[float, dict[str, str]] | None = None

_stock_concept_lock = threading.Lock()
# con_code -> (expires_at, 概念名称列表)
_stock_concept_cache: dict[str, tuple[float, list[str]]] = {}


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


def _get_ths_concept_index_name_map(ad: TushareAdapter) -> dict[str, str]:
    """同花顺概念指数列表（ths_index type=N），带缓存。"""
    global _ths_index_map_cache
    now = time_module.time()
    with _ths_index_map_lock:
        if _ths_index_map_cache and _ths_index_map_cache[0] > now:
            return _ths_index_map_cache[1]
    try:
        df = ad.get_ths_index(type="N")
    except Exception:
        with _ths_index_map_lock:
            _ths_index_map_cache = (now + 120.0, {})
        return {}
    m: dict[str, str] = {}
    if df is not None and not df.empty:
        for _, row in df.iterrows():
            code = row.get("ts_code")
            name = row.get("name")
            if code is None or pd.isna(code):
                continue
            if name is None or (isinstance(name, float) and pd.isna(name)):
                continue
            m[str(code).strip()] = str(name).strip()
    ttl = 60.0 if not m else float(THS_INDEX_MAP_TTL_SEC)
    with _ths_index_map_lock:
        _ths_index_map_cache = (now + ttl, m)
    return m


def _concepts_for_stock(
    ad: TushareAdapter,
    con_code: str,
    index_name_map: dict[str, str],
) -> list[str]:
    """单股所属同花顺概念（ths_member con_code=），名称由 ths_index 映射，带单股缓存。"""
    now = time_module.time()
    with _stock_concept_lock:
        hit = _stock_concept_cache.get(con_code)
        if hit and hit[0] > now:
            return hit[1]
    try:
        df = ad.get_ths_member(con_code=con_code)
    except Exception:
        with _stock_concept_lock:
            _stock_concept_cache[con_code] = (now + STOCK_THS_CONCEPT_TTL_SEC, [])
        return []
    if df is None or df.empty:
        with _stock_concept_lock:
            _stock_concept_cache[con_code] = (now + STOCK_THS_CONCEPT_TTL_SEC, [])
        return []
    seen: set[str] = set()
    out: list[str] = []
    for _, row in df.iterrows():
        idx = row.get("ts_code")
        if idx is None or pd.isna(idx):
            continue
        idx_s = str(idx).strip()
        label = index_name_map.get(idx_s) if index_name_map else None
        if not label:
            label = idx_s
        if label not in seen:
            seen.add(label)
            out.append(label)
    out.sort()
    out = out[:12]
    with _stock_concept_lock:
        _stock_concept_cache[con_code] = (now + STOCK_THS_CONCEPT_TTL_SEC, out)
    return out


def _enrich_ladder_ths_concepts(ladder: list[dict], ad: TushareAdapter) -> None:
    """为连板天梯每行补充 ths_concepts（同花顺概念板块名称列表）。"""
    if not ladder:
        return
    index_name_map = _get_ths_concept_index_name_map(ad)
    for row in ladder:
        code = row.get("ts_code")
        if not code:
            row["ths_concepts"] = []
            continue
        try:
            row["ths_concepts"] = _concepts_for_stock(ad, str(code), index_name_map)
        except Exception:
            row["ths_concepts"] = []


def get_limit_market_board_payload(
    trade_date: str | None = None,
    adapter: TushareAdapter | None = None,
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
    try:
        _enrich_ladder_ths_concepts(ladder, ad)
    except Exception:
        for row in ladder:
            row.setdefault("ths_concepts", [])

    payload_body = (sectors, ladder)

    with _cache_lock:
        _cache[td] = (now + DASHBOARD_LIMIT_BOARD_CACHE_TTL_SEC, payload_body)

    return {
        "trade_date": td,
        "resolved_by": resolved_by,
        "sectors": sectors,
        "ladder": ladder,
    }
