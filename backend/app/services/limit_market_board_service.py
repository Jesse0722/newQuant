"""涨停情绪仪表盘：limit_cpt_list + limit_step 聚合与短 TTL 缓存。"""
from __future__ import annotations

import math
import threading
import time as time_module
from typing import Any

import pandas as pd

from app.services.trade_date_resolver import resolve_dashboard_trade_date
from app.services.tushare_adapter import MarketDataProvider, TushareAdapter, tushare_adapter
from app.utils import normalize_ts_code

DASHBOARD_LIMIT_BOARD_CACHE_TTL_SEC = 60

_cache_lock = threading.Lock()
# trade_date -> (expires_at_epoch, (sectors, ladder))
_cache: dict[str, tuple[float, tuple[list[dict], list[dict], list[dict], list[dict], dict[str, Any]]]] = {}


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


def _fetch_limit_list_d(trade_date: str, limit_type: str) -> pd.DataFrame:
    """
    直接走 Tushare 的 limit_list_d，补齐每日跌停分析所需字段。
    当前多源适配器未统一暴露该接口，故在仪表盘服务内单独调用。
    """
    try:
        pro = TushareAdapter().pro
        df = pro.limit_list_d(
            trade_date=trade_date,
            limit_type=limit_type,
            fields="trade_date,ts_code,industry,name,pct_chg,limit_times",
        )
        if df is not None and not df.empty:
            return df
    except Exception:
        pass
    return pd.DataFrame()


def _fetch_limit_down_from_akshare(trade_date: str) -> pd.DataFrame:
    """
    AkShare 跌停股池兜底。
    兼容多个函数名与字段命名，统一输出：
    trade_date, ts_code, industry, name, pct_chg, limit_times
    """
    try:
        import akshare as ak  # type: ignore
    except Exception:
        return pd.DataFrame()

    raw: pd.DataFrame | None = None
    callers = []
    if hasattr(ak, "stock_zt_pool_dtgc_em"):
        callers.append(lambda: ak.stock_zt_pool_dtgc_em(date=trade_date))
    if hasattr(ak, "stock_em_zt_pool_dtgc"):
        callers.append(lambda: ak.stock_em_zt_pool_dtgc(date=trade_date))
    if hasattr(ak, "stock_dt_pool_em"):
        callers.append(lambda: ak.stock_dt_pool_em(date=trade_date))

    for fn in callers:
        try:
            df = fn()
            if df is not None and not df.empty:
                raw = df
                break
        except Exception:
            continue

    if raw is None or raw.empty:
        return pd.DataFrame()

    df = raw.copy()

    def _pick(*names: str) -> str | None:
        for n in names:
            if n in df.columns:
                return n
        return None

    code_col = _pick("代码", "code", "证券代码")
    name_col = _pick("名称", "name", "证券简称")
    ind_col = _pick("所属行业", "industry", "行业")
    pct_col = _pick("涨跌幅", "pct_chg")
    times_col = _pick("连板数", "连续跌停天数", "limit_times")

    if code_col is None:
        return pd.DataFrame()

    rows: list[dict[str, Any]] = []
    for _, r in df.iterrows():
        code_raw = str(r.get(code_col) or "").strip()
        if not code_raw:
            continue
        try:
            ts_code = normalize_ts_code(code_raw)
        except Exception:
            continue
        pct_val = pd.to_numeric(r.get(pct_col) if pct_col else None, errors="coerce")
        lt_val = pd.to_numeric(r.get(times_col) if times_col else None, errors="coerce")
        rows.append({
            "trade_date": trade_date,
            "ts_code": ts_code,
            "industry": (r.get(ind_col) if ind_col else None) or "其他",
            "name": (r.get(name_col) if name_col else None) or ts_code,
            "pct_chg": None if pd.isna(pct_val) else float(pct_val),
            "limit_times": 1 if pd.isna(lt_val) else int(lt_val),
        })

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


def _get_limit_down_threshold(market: str | None) -> float:
    if not market:
        return -9.9
    m = str(market)
    if "北交所" in m:
        return -29.9
    if "创业板" in m or "科创板" in m:
        return -19.9
    return -9.9


def _derive_limit_down_from_daily(ad: MarketDataProvider, trade_date: str) -> pd.DataFrame:
    """
    兜底数据源：当 Tushare limit_list_d 不可用时，改用日线 + 股票基础信息推断跌停股。
    说明：无法准确还原 limit_times，统一置为 1。
    """
    try:
        daily = ad.get_daily_by_date(trade_date)
    except Exception:
        return pd.DataFrame()
    if daily is None or daily.empty or "ts_code" not in daily.columns:
        return pd.DataFrame()

    try:
        basic = ad.get_stock_basic()
    except Exception:
        basic = pd.DataFrame()

    if basic is None or basic.empty:
        bmap: dict[str, dict[str, Any]] = {}
    else:
        basic = basic.copy()
        basic["ts_code"] = basic["ts_code"].astype(str)
        bmap = {
            str(r.get("ts_code")): {
                "industry": r.get("industry"),
                "name": r.get("name"),
                "market": r.get("market"),
            }
            for _, r in basic.iterrows()
        }

    out_rows: list[dict[str, Any]] = []
    for _, r in daily.iterrows():
        ts_code = str(r.get("ts_code") or "")
        if not ts_code:
            continue
        pct = pd.to_numeric(r.get("pct_chg"), errors="coerce")
        if pd.isna(pct):
            continue
        meta = bmap.get(ts_code, {})
        threshold = _get_limit_down_threshold(meta.get("market"))
        if float(pct) <= threshold:
            out_rows.append({
                "trade_date": trade_date,
                "ts_code": ts_code,
                "industry": meta.get("industry") or "其他",
                "name": meta.get("name") or ts_code,
                "pct_chg": float(pct),
                "limit_times": 1,
            })
    if not out_rows:
        return pd.DataFrame()
    return pd.DataFrame(out_rows)


def _build_outflow_sectors(df_down: pd.DataFrame) -> list[dict]:
    if df_down is None or df_down.empty:
        return []
    df = df_down.copy()
    df["industry"] = df["industry"].fillna("其他")
    df["pct_chg"] = pd.to_numeric(df.get("pct_chg"), errors="coerce")
    df["limit_times"] = pd.to_numeric(df.get("limit_times"), errors="coerce")
    g = (
        df.groupby("industry", dropna=False)
        .agg(
            down_nums=("ts_code", "count"),
            pct_chg=("pct_chg", "mean"),
            max_limit_times=("limit_times", "max"),
        )
        .reset_index()
    )
    g = g.sort_values(["down_nums", "pct_chg"], ascending=[False, True]).reset_index(drop=True)
    out: list[dict] = []
    for i, r in g.iterrows():
        out.append({
            "rank": str(i + 1),
            "name": r.get("industry") or "其他",
            "down_nums": int(r.get("down_nums") or 0),
            "pct_chg": float(r.get("pct_chg") or 0.0),
            "max_limit_times": int(r.get("max_limit_times") or 0),
            "trade_date": None,
        })
    return out


def _build_outflow_ladder(df_down: pd.DataFrame, trade_date: str) -> list[dict]:
    if df_down is None or df_down.empty:
        return []
    df = df_down.copy()
    df["limit_times"] = pd.to_numeric(df.get("limit_times"), errors="coerce").fillna(1).astype(int)
    df = df.sort_values(["limit_times", "ts_code"], ascending=[False, True]).reset_index(drop=True)
    out: list[dict] = []
    for _, r in df.iterrows():
        out.append({
            "ts_code": r.get("ts_code"),
            "name": r.get("name"),
            "trade_date": r.get("trade_date") or trade_date,
            "nums": str(int(r.get("limit_times") or 1)),
        })
    return out


def _build_summary(
    inflow_sectors: list[dict],
    inflow_ladder: list[dict],
    outflow_sectors: list[dict],
    outflow_ladder: list[dict],
    outflow_source: str = "unknown",
) -> dict[str, Any]:
    inflow_sector_count = len(inflow_sectors)
    outflow_sector_count = len(outflow_sectors)
    inflow_limit_count = sum(int(x.get("up_nums") or 0) for x in inflow_sectors)
    outflow_limit_count = sum(int(x.get("down_nums") or 0) for x in outflow_sectors)
    max_up_streak = max((int(str(x.get("nums") or "0")) for x in inflow_ladder), default=0)
    max_down_streak = max((int(str(x.get("nums") or "0")) for x in outflow_ladder), default=0)
    return {
        "inflow_sector_count": inflow_sector_count,
        "outflow_sector_count": outflow_sector_count,
        "inflow_limit_count": inflow_limit_count,
        "outflow_limit_count": outflow_limit_count,
        "net_limit_count": inflow_limit_count - outflow_limit_count,
        "flow_ratio": round((inflow_limit_count / outflow_limit_count), 2) if outflow_limit_count > 0 else None,
        "max_up_streak": max_up_streak,
        "max_down_streak": max_down_streak,
        "outflow_source": outflow_source,
    }


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
            sectors, ladder, outflow_sectors, outflow_ladder, summary = hit[1]
            return {
                "trade_date": td,
                "resolved_by": resolved_by,
                "sectors": sectors,
                "ladder": ladder,
                "inflow_sectors": sectors,
                "inflow_ladder": ladder,
                "outflow_sectors": outflow_sectors,
                "outflow_ladder": outflow_ladder,
                "summary": summary,
            }

    df_s = ad.get_limit_cpt_list(td)
    df_l = ad.get_limit_step(td)
    sectors = _sort_sectors(_df_to_records(df_s))
    ladder = _sort_ladder(_df_to_records(df_l))
    outflow_source = "none"
    df_down = _fetch_limit_list_d(td, "D")
    if df_down is not None and not df_down.empty:
        outflow_source = "tushare.limit_list_d"
    if df_down is None or df_down.empty:
        # 二级兜底：AkShare 跌停池
        df_down = _fetch_limit_down_from_akshare(td)
        if df_down is not None and not df_down.empty:
            outflow_source = "akshare.pool"
    if df_down is None or df_down.empty:
        # 三级兜底：日线推断跌停
        df_down = _derive_limit_down_from_daily(ad, td)
        if df_down is not None and not df_down.empty:
            outflow_source = "derived.daily"
    outflow_sectors = _build_outflow_sectors(df_down)
    outflow_ladder = _sort_ladder(_build_outflow_ladder(df_down, td))
    summary = _build_summary(sectors, ladder, outflow_sectors, outflow_ladder, outflow_source=outflow_source)
    payload_body = (sectors, ladder, outflow_sectors, outflow_ladder, summary)

    with _cache_lock:
        _cache[td] = (now + DASHBOARD_LIMIT_BOARD_CACHE_TTL_SEC, payload_body)

    return {
        "trade_date": td,
        "resolved_by": resolved_by,
        "sectors": sectors,
        "ladder": ladder,
        "inflow_sectors": sectors,
        "inflow_ladder": ladder,
        "outflow_sectors": outflow_sectors,
        "outflow_ladder": outflow_ladder,
        "summary": summary,
    }
