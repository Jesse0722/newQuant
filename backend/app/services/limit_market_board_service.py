"""涨停情绪仪表盘：limit_cpt_list + limit_step 聚合与短 TTL 缓存。"""
from __future__ import annotations

import json
import math
import threading
import time as time_module
from collections import defaultdict
from pathlib import Path
from typing import Any

import pandas as pd

from app.config import DATA_DIR
from app.services.trade_date_resolver import resolve_dashboard_trade_date
from app.services.tushare_adapter import TushareAdapter, tushare_adapter

DASHBOARD_LIMIT_BOARD_CACHE_TTL_SEC = 60
# 同花顺：ths_index 拉概念指数列表，ths_member(ts_code=板块指数) 拉成分；反向映射文件缓存
THS_STOCK_CONCEPT_FILE_TTL_SEC = 86400
THS_MEMBER_MIN_INTERVAL_SEC = 0.31  # 约 200 次/分钟上限内节流

_cache_lock = threading.Lock()
# trade_date -> (expires_at_epoch, (sectors, ladder))
_cache: dict[str, tuple[float, tuple[list[dict], list[dict]]]] = {}

_ths_map_refresh_lock = threading.Lock()
_ths_map_refresh_thread: threading.Thread | None = None
# 内存镜像：避免每请求读盘；与文件同步更新
_ths_stock_concept_map_mem: dict[str, list[str]] | None = None
_ths_stock_concept_map_mtime: float = 0.0


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


def _ths_concept_cache_path() -> Path:
    return DATA_DIR / "ths_stock_concepts.json"


def _load_ths_stock_concept_map_from_disk() -> dict[str, list[str]]:
    """读取本地缓存：股票 ts_code -> 同花顺概念名称列表。"""
    path = _ths_concept_cache_path()
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        m = raw.get("map")
        if not isinstance(m, dict):
            return {}
        out: dict[str, list[str]] = {}
        for k, v in m.items():
            if isinstance(v, list):
                out[str(k)] = [str(x) for x in v if x is not None]
        return out
    except Exception:
        return {}


def _get_ths_stock_concept_map_resolved() -> dict[str, list[str]]:
    """带内存缓存的读盘。"""
    global _ths_stock_concept_map_mem, _ths_stock_concept_map_mtime
    path = _ths_concept_cache_path()
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = 0.0
    if _ths_stock_concept_map_mem is not None and mtime == _ths_stock_concept_map_mtime:
        return _ths_stock_concept_map_mem
    _ths_stock_concept_map_mem = _load_ths_stock_concept_map_from_disk()
    _ths_stock_concept_map_mtime = mtime
    return _ths_stock_concept_map_mem


def _save_ths_stock_concept_map(m: dict[str, list[str]]) -> None:
    global _ths_stock_concept_map_mem, _ths_stock_concept_map_mtime
    path = _ths_concept_cache_path()
    payload = {
        "version": 1,
        "updated_at": int(time_module.time()),
        "map": m,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=0), encoding="utf-8")
    _ths_stock_concept_map_mem = m
    _ths_stock_concept_map_mtime = path.stat().st_mtime


def build_ths_stock_concept_map(ad: TushareAdapter) -> dict[str, list[str]]:
    """
    按官方用法：ths_index(type=N) 取概念指数，再对每个指数 ths_member(ts_code=指数代码) 取成分，
    合并为「股票 -> 所属概念名称」反向表（不调用 con_code=个股）。
    """
    stock_to_names: dict[str, set[str]] = defaultdict(set)
    try:
        df_idx = ad.get_ths_index(type="N")
    except Exception:
        return {}
    if df_idx is None or df_idx.empty:
        return {}
    n = 0
    for _, row in df_idx.iterrows():
        idx_ts = row.get("ts_code")
        cname = row.get("name")
        if idx_ts is None or pd.isna(idx_ts) or cname is None or (isinstance(cname, float) and pd.isna(cname)):
            continue
        idx_s = str(idx_ts).strip()
        label = str(cname).strip()
        if n > 0:
            time_module.sleep(THS_MEMBER_MIN_INTERVAL_SEC)
        n += 1
        try:
            df_m = ad.get_ths_member(ts_code=idx_s)
        except Exception:
            continue
        if df_m is None or df_m.empty:
            continue
        for _, mr in df_m.iterrows():
            cc = mr.get("con_code")
            if cc is None or pd.isna(cc):
                continue
            stock_to_names[str(cc).strip()].add(label)
    out: dict[str, list[str]] = {}
    for k, vset in stock_to_names.items():
        names = sorted(vset)
        out[k] = names[:20]
    return out


def _maybe_schedule_ths_map_refresh(ad: TushareAdapter) -> None:
    """文件不存在或过期时，后台线程重建反向表（首次可能需数分钟）。"""
    global _ths_map_refresh_thread
    path = _ths_concept_cache_path()
    if path.is_file():
        age = time_module.time() - path.stat().st_mtime
        if age < THS_STOCK_CONCEPT_FILE_TTL_SEC:
            return
    with _ths_map_refresh_lock:
        if _ths_map_refresh_thread and _ths_map_refresh_thread.is_alive():
            return

        def _job():
            try:
                m = build_ths_stock_concept_map(ad)
                if m:
                    _save_ths_stock_concept_map(m)
            except Exception:
                pass

        _ths_map_refresh_thread = threading.Thread(target=_job, daemon=True, name="ths-concept-map-refresh")
        _ths_map_refresh_thread.start()


def _enrich_ladder_ths_concepts(ladder: list[dict], ad: TushareAdapter) -> None:
    """为连板天梯每行补充 ths_concepts（来自本地反向映射缓存）。"""
    if not ladder:
        return
    _maybe_schedule_ths_map_refresh(ad)
    cmap = _get_ths_stock_concept_map_resolved()
    for row in ladder:
        code = row.get("ts_code")
        if not code:
            row["ths_concepts"] = []
            continue
        try:
            names = cmap.get(str(code), [])
            row["ths_concepts"] = names[:12]
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
