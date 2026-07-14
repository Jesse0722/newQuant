"""策略选股服务：指标组合选股、涨停回调买点选股"""

from __future__ import annotations
import types
from datetime import datetime, timedelta
import time
import pandas as pd
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.sector import SectorBasic, SectorDailyQuote, StockSectorMap
from app.models.stock import StockBasic, DailyQuote
from app.models.pool import WatchPool, WatchStock
from app.services.indicator import calc_ma, calc_macd, calc_rsi, calc_vol_ma, calc_n_day_high
from app.services.main_wave_service import analyze_main_wave_stock, _market_group, _market_group_filter
from app.services.sector_data_service import fetch_sector_constituents, fetch_stock_concept_sectors, upsert_stock_sector_map
from app.services.tushare_adapter import tushare_adapter
from app.services.limit_up_service import fetch_limit_up_stocks_in_range
from app.services.monitor_engine import _get_df, evaluate_template, TEMPLATE_INFO
from app.services.sync_service import sync_stock_info, sync_daily, _sync_stock_basic_full
from app.tasks.background import task_registry

# 涨停回调买点选股可用模板（需 limit_up_date 的用虚拟 watch_stock 传入）
LIMIT_UP_BUY_POINT_TEMPLATES = {
    k: {"name": v["name"], "default_params": v["default_params"]}
    for k, v in TEMPLATE_INFO.items()
    if k in ("ma_support", "limit_up_price_support", "days_since_limit_up", "fibonacci_retrace",
             "volume_shrink", "price_threshold", "rsi_oversold", "macd_golden", "breakout_high")
}

SCREEN_TEMPLATES = {
    "ma_cross": {"name": "MA 金叉", "params": {"n1": 5, "n2": 10}},
    "ma_above": {"name": "MA 上方", "params": {"n": 20}},
    "ma_below": {"name": "MA 下方", "params": {"n": 20}},
    "macd_golden": {"name": "MACD 金叉", "params": {}},
    "macd_dead": {"name": "MACD 死叉", "params": {}},
    "rsi_range": {"name": "RSI 区间", "params": {"period": 14, "min": 30, "max": 70}},
    "rsi_oversold": {"name": "RSI 超卖", "params": {"period": 14, "threshold": 30}},
    "volume_surge": {"name": "放量", "params": {"n": 5, "ratio": 1.5}},
    "breakout_high": {"name": "突破新高", "params": {"n": 60}},
    "price_vs_ma": {"name": "价格 vs 均线", "params": {"n": 20, "op": ">"}},
}

MAIN_WAVE_DEFAULT_STATUSES = [
    "main_wave_confirmed",
    "breakout_tracking",
    "watching",
]
MAIN_WAVE_SCAN_PRELOAD_LOOKBACK_DAYS = 760
MAIN_WAVE_SCAN_SECTOR_PRELOAD_LOOKBACK_DAYS = 140
MAIN_WAVE_SCAN_MARKET_PRELOAD_LOOKBACK_DAYS = 130
MAIN_WAVE_SCAN_PRELOAD_MAX_CODES = 8000
MAIN_WAVE_SCAN_PRELOAD_CHUNK_SIZE = 500
MAIN_WAVE_SCAN_PRELOAD_MAX_SECTORS = 800


def _chunked(values: list[str], size: int) -> list[list[str]]:
    return [values[i:i + size] for i in range(0, len(values), size)]


def _get_df_from_db(db: Session, ts_code: str, limit: int = 250) -> pd.DataFrame:
    rows = db.query(DailyQuote).filter(
        DailyQuote.ts_code == ts_code
    ).order_by(DailyQuote.trade_date.asc()).limit(limit).all()
    if not rows:
        return pd.DataFrame()
    data = [{"trade_date": r.trade_date, "open": r.open, "high": r.high, "low": r.low,
             "close": r.close, "pre_close": r.pre_close, "vol": r.vol, "amount": r.amount} for r in rows]
    return pd.DataFrame(data)


def _eval_condition(df: pd.DataFrame, template_id: str, params: dict) -> bool:
    if len(df) < 70:
        return False
    try:
        if template_id == "ma_cross":
            n1, n2 = params.get("n1", 5), params.get("n2", 10)
            ma1, ma2 = calc_ma(df, n1), calc_ma(df, n2)
            if pd.isna(ma1.iloc[-1]) or pd.isna(ma2.iloc[-1]) or pd.isna(ma1.iloc[-2]) or pd.isna(ma2.iloc[-2]):
                return False
            return ma1.iloc[-2] <= ma2.iloc[-2] and ma1.iloc[-1] > ma2.iloc[-1]

        elif template_id == "ma_above":
            n = params.get("n", 20)
            ma = calc_ma(df, n)
            if pd.isna(ma.iloc[-1]):
                return False
            return df["close"].iloc[-1] > ma.iloc[-1]

        elif template_id == "ma_below":
            n = params.get("n", 20)
            ma = calc_ma(df, n)
            if pd.isna(ma.iloc[-1]):
                return False
            return df["close"].iloc[-1] < ma.iloc[-1]

        elif template_id == "macd_golden":
            dif, dea, _ = calc_macd(df)
            if len(dif) < 2 or pd.isna(dif.iloc[-1]) or pd.isna(dif.iloc[-2]):
                return False
            return dif.iloc[-2] < dea.iloc[-2] and dif.iloc[-1] >= dea.iloc[-1]

        elif template_id == "macd_dead":
            dif, dea, _ = calc_macd(df)
            if len(dif) < 2 or pd.isna(dif.iloc[-1]) or pd.isna(dif.iloc[-2]):
                return False
            return dif.iloc[-2] > dea.iloc[-2] and dif.iloc[-1] <= dea.iloc[-1]

        elif template_id == "rsi_range":
            period = params.get("period", 14)
            min_val = params.get("min", 30)
            max_val = params.get("max", 70)
            r = calc_rsi(df, period)
            if pd.isna(r.iloc[-1]):
                return False
            return min_val <= r.iloc[-1] <= max_val

        elif template_id == "rsi_oversold":
            period = params.get("period", 14)
            threshold = params.get("threshold", 30)
            r = calc_rsi(df, period)
            if pd.isna(r.iloc[-1]):
                return False
            return r.iloc[-1] < threshold

        elif template_id == "volume_surge":
            n = params.get("n", 5)
            ratio = params.get("ratio", 1.5)
            vol_ma = calc_vol_ma(df, n)
            if pd.isna(vol_ma.iloc[-1]) or vol_ma.iloc[-1] == 0:
                return False
            return df["vol"].iloc[-1] > vol_ma.iloc[-1] * ratio

        elif template_id == "breakout_high":
            n = params.get("n", 60)
            n_high = calc_n_day_high(df, n)
            if pd.isna(n_high.iloc[-2]):
                return False
            return df["close"].iloc[-1] >= n_high.iloc[-2]

        elif template_id == "price_vs_ma":
            n = params.get("n", 20)
            op = params.get("op", ">")
            ma = calc_ma(df, n)
            if pd.isna(ma.iloc[-1]):
                return False
            close, ma_val = df["close"].iloc[-1], ma.iloc[-1]
            if op == ">":
                return close > ma_val
            if op == "<":
                return close < ma_val
            if op == ">=":
                return close >= ma_val
            if op == "<=":
                return close <= ma_val
            return False
    except Exception:
        return False
    return False


def _get_trade_dates(days: int = 60) -> list[str]:
    """获取最近 N 个交易日日期（YYYYMMDD）"""
    dates = []
    d = datetime.now()
    while len(dates) < days:
        s = d.strftime("%Y%m%d")
        if d.weekday() < 5:
            dates.append(s)
        d -= timedelta(days=1)
    return dates


def _fetch_full_market_daily(days: int = 60) -> dict[str, pd.DataFrame]:
    """从 Tushare 按日拉取全市场日线，返回 ts_code -> DataFrame"""
    dates = _get_trade_dates(days)
    all_data: list[pd.DataFrame] = []
    for i, trade_date in enumerate(dates):
        try:
            df = tushare_adapter.get_daily_by_date(trade_date)
            if not df.empty:
                all_data.append(df)
            time.sleep(0.15)
        except Exception:
            pass
    if not all_data:
        return {}
    merged = pd.concat(all_data, ignore_index=True)
    result = {}
    for ts_code, g in merged.groupby("ts_code"):
        g = g.sort_values("trade_date").reset_index(drop=True)
        result[ts_code] = g
    return result


def _latest_quote(db: Session, ts_code: str) -> DailyQuote | None:
    return (
        db.query(DailyQuote)
        .filter(DailyQuote.ts_code == ts_code)
        .order_by(DailyQuote.trade_date.desc())
        .first()
    )


def _quote_count(db: Session, ts_code: str) -> int:
    return db.query(DailyQuote).filter(DailyQuote.ts_code == ts_code).count()


def _avg_amount_20d_yi(db: Session, ts_code: str) -> float | None:
    rows = (
        db.query(DailyQuote.amount)
        .filter(DailyQuote.ts_code == ts_code, DailyQuote.amount.isnot(None))
        .order_by(DailyQuote.trade_date.desc())
        .limit(20)
        .all()
    )
    vals = [float(r[0]) for r in rows if r[0] is not None]
    if not vals:
        return None
    return round((sum(vals) / len(vals)) / 100000.0, 2)


def _float_market_cap_yi(basic: StockBasic | None, latest: DailyQuote | None) -> float | None:
    if not latest or latest.close is None:
        return None
    float_share = latest.float_share if latest.float_share is not None else (basic.float_share if basic else None)
    if float_share is None:
        return None
    return round(float(latest.close) * float(float_share) / 10000.0, 2)


def _main_wave_preload_start_date(end_date: str | None) -> str | None:
    if not end_date:
        return None
    try:
        return (datetime.strptime(end_date, "%Y%m%d") - timedelta(days=MAIN_WAVE_SCAN_PRELOAD_LOOKBACK_DAYS)).strftime("%Y%m%d")
    except ValueError:
        return None


def _main_wave_preload_start_date_with_lookback(end_date: str | None, lookback_days: int) -> str | None:
    if not end_date:
        return None
    try:
        return (datetime.strptime(end_date, "%Y%m%d") - timedelta(days=lookback_days)).strftime("%Y%m%d")
    except ValueError:
        return None


def _latest_trade_date_for_codes(db: Session, codes: list[str]) -> str | None:
    latest: str | None = None
    for chunk in _chunked(codes, MAIN_WAVE_SCAN_PRELOAD_CHUNK_SIZE):
        row = (
            db.query(func.max(DailyQuote.trade_date))
            .filter(DailyQuote.ts_code.in_(chunk))
            .first()
        )
        if row and row[0] and (latest is None or str(row[0]) > latest):
            latest = str(row[0])
    return latest


def _prime_main_wave_basics(db: Session, codes: list[str], cache: dict) -> dict:
    started = time.perf_counter()
    bucket = cache.setdefault("basics", {})
    for chunk in _chunked(codes, MAIN_WAVE_SCAN_PRELOAD_CHUNK_SIZE):
        rows = db.query(StockBasic).filter(StockBasic.ts_code.in_(chunk)).all()
        for row in rows:
            bucket[row.ts_code] = row
    return {
        "loaded_codes": len(bucket),
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
    }


def _prime_main_wave_quote_history(db: Session, codes: list[str], end_date: str | None, cache: dict) -> dict:
    started = time.perf_counter()
    preload = {
        "enabled": False,
        "loaded_codes": 0,
        "row_count": 0,
        "start_date": _main_wave_preload_start_date(end_date),
        "end_date": end_date,
        "skipped_reason": None,
        "elapsed_ms": 0.0,
    }
    if not codes:
        preload["skipped_reason"] = "empty_scope"
        return preload
    if not end_date or not preload["start_date"]:
        preload["skipped_reason"] = "missing_trade_date"
        return preload
    if len(codes) > MAIN_WAVE_SCAN_PRELOAD_MAX_CODES:
        preload["skipped_reason"] = "scope_too_large"
        return preload

    bucket = cache.setdefault("quote_history", {})
    columns = ["trade_date", "open", "high", "low", "close", "pct_chg", "vol", "amount", "turnover_rate", "float_share"]
    for chunk in _chunked(codes, MAIN_WAVE_SCAN_PRELOAD_CHUNK_SIZE):
        rows = (
            db.query(
                DailyQuote.ts_code,
                DailyQuote.trade_date,
                DailyQuote.open,
                DailyQuote.high,
                DailyQuote.low,
                DailyQuote.close,
                DailyQuote.pct_chg,
                DailyQuote.vol,
                DailyQuote.amount,
                DailyQuote.turnover_rate,
                DailyQuote.float_share,
            )
            .filter(
                DailyQuote.ts_code.in_(chunk),
                DailyQuote.trade_date >= preload["start_date"],
                DailyQuote.trade_date <= end_date,
            )
            .order_by(DailyQuote.ts_code.asc(), DailyQuote.trade_date.asc())
            .all()
        )
        if not rows:
            continue
        raw = pd.DataFrame(
            [
                {
                    "ts_code": row.ts_code,
                    "trade_date": row.trade_date,
                    "open": row.open,
                    "high": row.high,
                    "low": row.low,
                    "close": row.close,
                    "pct_chg": row.pct_chg,
                    "vol": row.vol,
                    "amount": row.amount,
                    "turnover_rate": row.turnover_rate,
                    "float_share": row.float_share,
                }
                for row in rows
            ]
        )
        for ts_code, group in raw.groupby("ts_code"):
            bucket[str(ts_code)] = group[columns].sort_values("trade_date").reset_index(drop=True)

    preload["enabled"] = True
    preload["loaded_codes"] = len(bucket)
    preload["row_count"] = int(sum(len(df) for df in bucket.values()))
    preload["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 1)
    return preload


def _prime_main_wave_sector_maps(db: Session, codes: list[str], cache: dict) -> dict:
    started = time.perf_counter()
    preload = {"enabled": False, "loaded_codes": 0, "row_count": 0, "sector_count": 0, "elapsed_ms": 0.0}
    if not codes:
        return preload
    bucket = cache.setdefault("stock_sector_maps", {})
    sector_codes: set[str] = set()
    row_count = 0
    for chunk in _chunked(codes, MAIN_WAVE_SCAN_PRELOAD_CHUNK_SIZE):
        rows = (
            db.query(StockSectorMap)
            .filter(StockSectorMap.ts_code.in_(chunk))
            .order_by(StockSectorMap.ts_code.asc(), StockSectorMap.sector_type.asc(), StockSectorMap.sector_name.asc())
            .all()
        )
        grouped: dict[str, list[StockSectorMap]] = {}
        for row in rows:
            grouped.setdefault(row.ts_code, []).append(row)
            if row.sector_code:
                sector_codes.add(str(row.sector_code))
            row_count += 1
        for code in chunk:
            bucket[code] = grouped.get(code, [])
    preload.update({
        "enabled": True,
        "loaded_codes": len(bucket),
        "row_count": row_count,
        "sector_count": len(sector_codes),
        "sector_codes": sorted(sector_codes),
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
    })
    return preload


def _prime_main_wave_sector_quote_history(db: Session, sector_codes: list[str], end_date: str | None, cache: dict) -> dict:
    started = time.perf_counter()
    preload = {
        "enabled": False,
        "loaded_sectors": 0,
        "row_count": 0,
        "start_date": _main_wave_preload_start_date_with_lookback(end_date, MAIN_WAVE_SCAN_SECTOR_PRELOAD_LOOKBACK_DAYS),
        "end_date": end_date,
        "skipped_reason": None,
        "elapsed_ms": 0.0,
    }
    if not sector_codes:
        preload["skipped_reason"] = "empty_scope"
        return preload
    if len(sector_codes) > MAIN_WAVE_SCAN_PRELOAD_MAX_SECTORS:
        preload["skipped_reason"] = "sector_scope_too_large"
        return preload
    if not end_date or not preload["start_date"]:
        preload["skipped_reason"] = "missing_trade_date"
        return preload

    bucket = cache.setdefault("sector_quote_history", {})
    columns = ["trade_date", "close", "pct_chg"]
    for chunk in _chunked(sector_codes, MAIN_WAVE_SCAN_PRELOAD_CHUNK_SIZE):
        rows = (
            db.query(SectorDailyQuote.sector_code, SectorDailyQuote.trade_date, SectorDailyQuote.close, SectorDailyQuote.pct_chg)
            .filter(
                SectorDailyQuote.sector_code.in_(chunk),
                SectorDailyQuote.trade_date >= preload["start_date"],
                SectorDailyQuote.trade_date <= end_date,
                SectorDailyQuote.close.isnot(None),
            )
            .order_by(SectorDailyQuote.sector_code.asc(), SectorDailyQuote.trade_date.asc())
            .all()
        )
        if not rows:
            continue
        raw = pd.DataFrame(
            [
                {
                    "sector_code": row.sector_code,
                    "trade_date": row.trade_date,
                    "close": row.close,
                    "pct_chg": row.pct_chg,
                }
                for row in rows
            ]
        )
        for sector_code, group in raw.groupby("sector_code"):
            bucket[str(sector_code)] = group[columns].sort_values("trade_date").reset_index(drop=True)

    preload["enabled"] = True
    preload["loaded_sectors"] = len(bucket)
    preload["row_count"] = int(sum(len(df) for df in bucket.values()))
    preload["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 1)
    return preload


def _prime_main_wave_market_proxy_history(db: Session, codes: list[str], end_date: str | None, cache: dict) -> dict:
    started = time.perf_counter()
    preload = {
        "enabled": False,
        "groups": [],
        "row_count": 0,
        "start_date": _main_wave_preload_start_date_with_lookback(end_date, MAIN_WAVE_SCAN_MARKET_PRELOAD_LOOKBACK_DAYS),
        "end_date": end_date,
        "skipped_reason": None,
        "elapsed_ms": 0.0,
    }
    if not codes:
        preload["skipped_reason"] = "empty_scope"
        return preload
    if not end_date or not preload["start_date"]:
        preload["skipped_reason"] = "missing_trade_date"
        return preload
    groups = sorted({_market_group(code) for code in codes})
    bucket = cache.setdefault("market_proxy_history", {})
    for group in groups:
        condition = _market_group_filter(group)
        rows = (
            db.query(DailyQuote.trade_date, DailyQuote.ts_code, DailyQuote.close, DailyQuote.pct_chg)
            .filter(
                condition,
                DailyQuote.trade_date >= preload["start_date"],
                DailyQuote.trade_date <= end_date,
                DailyQuote.close.isnot(None),
            )
            .order_by(DailyQuote.ts_code.asc(), DailyQuote.trade_date.asc())
            .all()
        )
        if not rows:
            continue
        raw = pd.DataFrame(
            [
                {
                    "trade_date": row.trade_date,
                    "ts_code": row.ts_code,
                    "close": row.close,
                    "pct_chg": row.pct_chg,
                }
                for row in rows
            ]
        )
        raw["close"] = pd.to_numeric(raw["close"], errors="coerce")
        raw["pct_chg"] = pd.to_numeric(raw["pct_chg"], errors="coerce")
        raw["pct_chg"] = raw["pct_chg"].fillna(raw.groupby("ts_code")["close"].pct_change() * 100)
        raw = raw.dropna(subset=["pct_chg"])
        if raw.empty:
            continue
        grouped = (
            raw.groupby("trade_date", as_index=False)
            .agg(pct_chg=("pct_chg", "mean"), member_count=("ts_code", "nunique"))
            .sort_values("trade_date")
        )
        close = 1000.0
        closes = []
        for pct_chg in grouped["pct_chg"].tolist():
            close *= 1 + float(pct_chg) / 100
            closes.append(round(close, 4))
        grouped["close"] = closes
        grouped["pct_chg"] = grouped["pct_chg"].round(4)
        bucket[group] = grouped.reset_index(drop=True)

    preload["enabled"] = True
    preload["groups"] = sorted(bucket.keys())
    preload["row_count"] = int(sum(len(df) for df in bucket.values()))
    preload["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 1)
    return preload


def _prime_main_wave_scan_cache(db: Session, codes: list[str], cache: dict) -> dict:
    started = time.perf_counter()
    latest_trade_date = _latest_trade_date_for_codes(db, codes)
    basics = _prime_main_wave_basics(db, codes, cache)
    quotes = _prime_main_wave_quote_history(db, codes, latest_trade_date, cache)
    maps = _prime_main_wave_sector_maps(db, codes, cache)
    sector_quote_codes = maps.get("sector_codes") or []
    sectors = _prime_main_wave_sector_quote_history(db, sector_quote_codes, latest_trade_date, cache)
    markets = _prime_main_wave_market_proxy_history(db, codes, latest_trade_date, cache)
    maps.pop("sector_codes", None)
    return {
        "latest_trade_date": latest_trade_date,
        "basics": basics,
        "quotes": quotes,
        "sector_maps": maps,
        "sector_quotes": sectors,
        "market_proxy": markets,
        "total_elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
    }


def _watch_pool_codes(db: Session, scope: str) -> list[str]:
    pool = db.query(WatchPool).filter(WatchPool.id == scope).first()
    if not pool:
        raise ValueError("观察池不存在")
    rows = db.query(WatchStock.ts_code).filter(WatchStock.pool_id == scope).all()
    return [r[0] for r in rows]


def _ensure_sector_constituents(db: Session, sector_codes: list[str]) -> None:
    """指定概念选股时，若本地成分为空，按现有板块服务补一次成分映射。"""
    for code in sector_codes:
        has_rows = (
            db.query(StockSectorMap.id)
            .filter(
                StockSectorMap.sector_type == "concept",
                StockSectorMap.sector_code == code,
            )
            .first()
        )
        if has_rows:
            continue
        sector = db.query(SectorBasic).filter(SectorBasic.sector_code == code).first()
        if not sector:
            continue
        try:
            rows = fetch_sector_constituents(sector)
            if rows:
                upsert_stock_sector_map(db, rows)
        except Exception:
            continue


def _sector_scope_codes(db: Session, sector_codes: list[str], sector_logic: str) -> list[str]:
    rows = (
        db.query(StockSectorMap.ts_code, func.count(func.distinct(StockSectorMap.sector_code)).label("hit_count"))
        .filter(
            StockSectorMap.sector_type == "concept",
            StockSectorMap.sector_code.in_(sector_codes),
        )
        .group_by(StockSectorMap.ts_code)
        .all()
    )
    required = len(set(sector_codes))
    if sector_logic == "all":
        return [r.ts_code for r in rows if int(r.hit_count or 0) >= required]
    return [r.ts_code for r in rows]


def _sector_search_terms(db: Session, sector_codes: list[str]) -> list[str]:
    generic = {"概念", "板块", "指数", "主题", "产业", "绿色", "相关", "精选"}
    terms: list[str] = []
    sectors = db.query(SectorBasic).filter(SectorBasic.sector_code.in_(sector_codes)).all()
    for sector in sectors:
        name = str(sector.sector_name or "")
        cleaned = name
        for word in generic:
            cleaned = cleaned.replace(word, "")
        candidates = {cleaned.strip()}
        if "电力" in cleaned:
            candidates.update({"电力", "能源", "发电", "风电", "水电", "光伏", "太阳能", "新能源"})
        if len(cleaned) >= 2:
            candidates.add(cleaned[-2:])
        if len(cleaned) >= 3:
            candidates.add(cleaned[-3:])
        for candidate in candidates:
            if len(candidate) >= 2 and candidate not in generic:
                terms.append(candidate)
    return list(dict.fromkeys(terms))


def _pool_codes_for_sector_f10_fallback(db: Session, sector_codes: list[str], pool_codes: list[str]) -> list[str]:
    if len(pool_codes) <= 300:
        return pool_codes
    terms = _sector_search_terms(db, sector_codes)
    if not terms:
        return []
    rows = db.query(StockBasic).filter(StockBasic.ts_code.in_(pool_codes)).all()
    matched: list[str] = []
    for stock in rows:
        text = f"{stock.name or ''} {stock.industry or ''}"
        if any(term in text for term in terms):
            matched.append(stock.ts_code)
    return matched


def _ensure_pool_stock_sector_memberships(db: Session, sector_codes: list[str], pool_codes: list[str]) -> None:
    """板块全量成分不可用时，用池内股票 F10 概念反查补齐局部映射。"""
    wanted = set(sector_codes)
    rows: list[dict] = []
    candidates = _pool_codes_for_sector_f10_fallback(db, sector_codes, pool_codes)
    for ts_code in candidates:
        existing_codes = {
            r[0]
            for r in db.query(StockSectorMap.sector_code)
            .filter(
                StockSectorMap.ts_code == ts_code,
                StockSectorMap.sector_type == "concept",
                StockSectorMap.sector_code.in_(wanted),
            )
            .all()
        }
        if existing_codes >= wanted:
            continue
        try:
            sectors = fetch_stock_concept_sectors(ts_code)
        except Exception:
            continue
        for sector in sectors:
            if sector.get("sector_code") in wanted:
                rows.append({**sector, "ts_code": ts_code, "weight": 1.0})
    if rows:
        upsert_stock_sector_map(db, rows)


def _main_wave_scope_codes(db: Session, scope: str, sector_codes: list[str], sector_logic: str) -> list[str]:
    if sector_codes:
        pool_codes: list[str] | None = None
        if scope and scope != "full":
            pool_codes = _watch_pool_codes(db, scope)
        codes = _sector_scope_codes(db, sector_codes, sector_logic)
        if pool_codes is not None:
            pool_code_set = set(pool_codes)
            codes = [code for code in codes if code in pool_code_set]
            if not codes:
                _ensure_pool_stock_sector_memberships(db, sector_codes, pool_codes)
                codes = [code for code in _sector_scope_codes(db, sector_codes, sector_logic) if code in pool_code_set]
            if not codes:
                _ensure_sector_constituents(db, sector_codes)
                codes = [code for code in _sector_scope_codes(db, sector_codes, sector_logic) if code in pool_code_set]
        else:
            _ensure_sector_constituents(db, sector_codes)
            codes = _sector_scope_codes(db, sector_codes, sector_logic)
        return codes

    if scope == "full":
        rows = (
            db.query(StockBasic.ts_code)
            .filter(or_(StockBasic.list_status == "L", StockBasic.list_status.is_(None)))
            .all()
        )
        return [r[0] for r in rows]

    return _watch_pool_codes(db, scope)


def _passes_main_wave_hard_filters(
    db: Session,
    ts_code: str,
    params: dict,
    cache: dict | None = None,
) -> tuple[bool, dict]:
    basic_bucket = (cache or {}).get("basics") or {}
    quote_history = (cache or {}).get("quote_history") or {}
    basic = basic_bucket.get(ts_code)
    if basic is None and ts_code not in basic_bucket:
        basic = db.query(StockBasic).filter(StockBasic.ts_code == ts_code).first()

    history = quote_history.get(ts_code)
    latest = None
    latest_close = None
    latest_float_share = None
    avg_amount_yi = None
    quote_count = None
    if history is not None and not history.empty:
        quote_count = len(history)
        latest_row = history.iloc[-1]
        latest_close = latest_row.get("close")
        latest_float_share = latest_row.get("float_share")
        amount_series = history.tail(20)["amount"] if "amount" in history.columns else pd.Series(dtype=float)
        amount_vals = pd.to_numeric(amount_series, errors="coerce").dropna()
        if not amount_vals.empty:
            avg_amount_yi = round(float(amount_vals.mean()) / 100000.0, 2)
    else:
        latest = _latest_quote(db, ts_code)
        latest_close = latest.close if latest else None

    if latest_close is None or pd.isna(latest_close):
        return False, {"skip_reason": "缺少最新行情"}

    name = basic.name if basic else ""
    if params.get("exclude_st", True) and ("ST" in name.upper() or "退" in name):
        return False, {"skip_reason": "ST或退市风险"}

    min_days = int(params.get("min_data_days") or 120)
    if quote_count is None:
        quote_count = _quote_count(db, ts_code)
    if quote_count < min_days:
        return False, {"skip_reason": f"K线不足{min_days}日"}

    close = float(latest_close)
    min_price = params.get("min_price")
    max_price = params.get("max_price")
    if min_price is not None and close < float(min_price):
        return False, {"skip_reason": "价格低于下限"}
    if max_price is not None and close > float(max_price):
        return False, {"skip_reason": "价格高于上限"}

    if latest is not None:
        cap_yi = _float_market_cap_yi(basic, latest)
    else:
        float_share = latest_float_share if latest_float_share is not None and not pd.isna(latest_float_share) else (basic.float_share if basic else None)
        cap_yi = round(close * float(float_share) / 10000.0, 2) if float_share is not None else None
    min_cap = params.get("min_float_market_cap_yi")
    if min_cap is not None and (cap_yi is None or cap_yi < float(min_cap)):
        return False, {"skip_reason": "流通市值低于下限", "float_market_cap_yi": cap_yi}

    if avg_amount_yi is None:
        avg_amount_yi = _avg_amount_20d_yi(db, ts_code)
    min_amount = params.get("min_avg_amount_20d_yi")
    if min_amount is not None and (avg_amount_yi is None or avg_amount_yi < float(min_amount)):
        return False, {"skip_reason": "20日成交额低于下限", "avg_amount_20d_yi": avg_amount_yi}

    return True, {
        "float_market_cap_yi": cap_yi,
        "avg_amount_20d_yi": avg_amount_yi,
    }


def _passes_main_wave_score_filters(item: dict, params: dict) -> bool:
    if item.get("status") == "insufficient_data":
        return False
    if params.get("exclude_effective_break", True) and item.get("status") == "exit_signal":
        return False
    min_score = int(params.get("min_score") or 70)
    if int(item.get("total_score") or 0) < min_score:
        return False
    statuses = params.get("statuses") or MAIN_WAVE_DEFAULT_STATUSES
    if statuses and item.get("status") not in set(statuses):
        return False

    metrics = item.get("metrics") or {}
    ma20 = item.get("ma20_state") or {}
    max_return_60d = params.get("max_return_60d")
    if max_return_60d is not None and metrics.get("return_60d") is not None:
        if float(metrics["return_60d"]) > float(max_return_60d):
            return False
    max_ma20_distance = params.get("max_ma20_distance_pct")
    if max_ma20_distance is not None and ma20.get("distance_pct") is not None:
        if float(ma20["distance_pct"]) > float(max_ma20_distance):
            return False

    best_sector = metrics.get("best_sector") or {}
    sector_status = metrics.get("sector_data_status")
    sector_is_stale_or_missing = sector_status in {"stale", "missing"}
    if (
        params.get("require_sector_resonance", False)
        and not sector_is_stale_or_missing
        and int((item.get("scores") or {}).get("sector_resonance") or 0) <= 0
    ):
        return False
    min_sector_return = params.get("min_sector_return_20d")
    if min_sector_return is not None and not sector_is_stale_or_missing:
        sector_return = best_sector.get("sector_return_20d")
        if sector_return is None or float(sector_return) < float(min_sector_return):
            return False
    min_relative = params.get("min_relative_strength_20d")
    if min_relative is not None and not sector_is_stale_or_missing:
        relative = best_sector.get("relative_strength_20d")
        if relative is None or float(relative) < float(min_relative):
            return False
    entry = item.get("entry") or {}
    entry_stages = set(params.get("entry_stages") or [])
    if entry_stages and entry.get("stage") not in entry_stages:
        return False
    min_entry_score = params.get("min_entry_score")
    if min_entry_score is not None and int(entry.get("score") or 0) < int(min_entry_score):
        return False
    if params.get("exclude_overheat", True) and entry.get("stage") == "avoid_chase":
        return False
    return True


def _main_wave_result_item(item: dict) -> dict:
    scores = item.get("scores") or {}
    metrics = item.get("metrics") or {}
    best_sector = metrics.get("best_sector") or {}
    entry = item.get("entry") or {}
    return {
        "ts_code": item.get("ts_code"),
        "stock_name": item.get("name") or "",
        "total_score": item.get("total_score") or 0,
        "status": item.get("status"),
        "trend_score": scores.get("trend") or 0,
        "structure_score": scores.get("structure") or 0,
        "pullback_repair_score": scores.get("pullback_repair") or 0,
        "sector_resonance_score": scores.get("sector_resonance") or 0,
        "market_relative_score": scores.get("market_relative") or 0,
        "best_sector": best_sector,
        "market_proxy": metrics.get("market_proxy"),
        "return_20d": metrics.get("return_20d"),
        "return_60d": metrics.get("return_60d"),
        "relative_strength_20d": best_sector.get("relative_strength_20d"),
        "ma20_state": item.get("ma20_state"),
        "entry_score": entry.get("score"),
        "entry_stage": entry.get("stage"),
        "entry_label": entry.get("label"),
        "entry_reasons": entry.get("reasons") or [],
        "entry_risks": entry.get("risks") or [],
        "sector_data_status": metrics.get("sector_data_status"),
        "sector_data_warning": metrics.get("sector_data_warning"),
        "overheat_reasons": (metrics.get("overheat") or {}).get("reasons") or [],
        "data_quality": metrics.get("data_quality"),
        "float_market_cap_yi": metrics.get("float_market_cap_yi"),
        "avg_amount_20d_yi": metrics.get("avg_amount_20d_yi"),
    }


def run_main_wave_screen(task_id: str, scope: str, params: dict):
    """主升浪趋势策略选股：支持全市场、观察池、指定概念板块。"""
    task = task_registry.get(task_id)
    if not task:
        return
    db = SessionLocal()
    try:
        scan_started = time.perf_counter()
        sector_codes = [str(x) for x in (params.get("sector_codes") or []) if x]
        sector_logic = str(params.get("sector_logic") or "any")
        task.message = "正在准备主升浪扫描范围..."
        task.progress = 0.01
        scope_started = time.perf_counter()
        codes = _main_wave_scope_codes(db, scope or "full", sector_codes, sector_logic)
        scope_elapsed_ms = round((time.perf_counter() - scope_started) * 1000, 1)
        total = len(codes)
        matched: list[dict] = []
        main_wave_cache: dict = {}
        hard_filter_elapsed = 0.0
        analyze_elapsed = 0.0
        score_filter_elapsed = 0.0
        hard_filtered = 0
        score_filtered = 0

        task.progress = 0.03
        task.message = f"正在预载主升浪扫描数据：{total} 只"
        preload = _prime_main_wave_scan_cache(db, codes, main_wave_cache)
        as_of_date = preload.get("latest_trade_date")

        for i, ts_code in enumerate(codes):
            task.progress = 0.08 + ((i + 1) / total) * 0.86 if total else 0.94
            if i == 0 or (i + 1) % 25 == 0 or i + 1 == total:
                elapsed = time.perf_counter() - scan_started
                task.message = f"主升浪评分 {i + 1}/{total}，已命中 {len(matched)}，耗时 {elapsed:.1f}s"
            hard_started = time.perf_counter()
            ok, extra_metrics = _passes_main_wave_hard_filters(db, ts_code, params, cache=main_wave_cache)
            hard_filter_elapsed += time.perf_counter() - hard_started
            if not ok:
                hard_filtered += 1
                continue
            analyze_started = time.perf_counter()
            item = analyze_main_wave_stock(
                db,
                ts_code,
                preferred_sector_codes=sector_codes or None,
                allow_external_sector_fetch=False,
                cache=main_wave_cache,
                as_of_date=as_of_date,
            )
            analyze_elapsed += time.perf_counter() - analyze_started
            item.setdefault("metrics", {}).update(extra_metrics)
            score_started = time.perf_counter()
            if not _passes_main_wave_score_filters(item, params):
                score_filter_elapsed += time.perf_counter() - score_started
                score_filtered += 1
                continue
            score_filter_elapsed += time.perf_counter() - score_started
            matched.append(_main_wave_result_item(item))

        sort_started = time.perf_counter()
        matched.sort(key=lambda x: (-(int(x.get("total_score") or 0)), str(x.get("ts_code") or "")))
        sort_elapsed_ms = round((time.perf_counter() - sort_started) * 1000, 1)
        elapsed_total = time.perf_counter() - scan_started
        task.result = {
            "ts_codes": [x["ts_code"] for x in matched if x.get("ts_code")],
            "stock_names": {x["ts_code"]: x.get("stock_name", "") for x in matched if x.get("ts_code")},
            "items": matched,
            "total": len(matched),
            "performance": {
                "scope_elapsed_ms": scope_elapsed_ms,
                "preload": preload,
                "hard_filter_elapsed_ms": round(hard_filter_elapsed * 1000, 1),
                "analyze_elapsed_ms": round(analyze_elapsed * 1000, 1),
                "score_filter_elapsed_ms": round(score_filter_elapsed * 1000, 1),
                "sort_elapsed_ms": sort_elapsed_ms,
                "total_elapsed_ms": round(elapsed_total * 1000, 1),
                "total_codes": total,
                "hard_filtered": hard_filtered,
                "score_filtered": score_filtered,
                "matched": len(matched),
            },
        }
        task.status = "completed"
        task.progress = 1.0
        task.message = f"主升浪筛选完成，共 {len(matched)} 只，耗时 {elapsed_total:.1f}s"
    except Exception as e:
        task.status = "failed"
        task.message = str(e)
    finally:
        db.close()


def run_indicator_screen(task_id: str, scope: str, conditions: list[dict], logic: str):
    """
    执行指标组合选股。
    scope: "full" 全市场，或 pool_id 池内
    conditions: [{"template_id": "ma_cross", "params": {...}}, ...]，最多 10 个
    logic: "and" | "or"
    """
    task = task_registry.get(task_id)
    if not task:
        return
    db = SessionLocal()
    try:
        stock_dfs: dict[str, pd.DataFrame] = {}
        name_map: dict[str, str] = {}

        if scope == "full":
            task.message = "正在拉取全市场日线数据..."
            stock_dfs = _fetch_full_market_daily(60)
            basic_df = tushare_adapter.get_stock_basic()
            if not basic_df.empty:
                for _, row in basic_df.iterrows():
                    name_map[row["ts_code"]] = row.get("name", "")
        else:
            pool = db.query(WatchPool).filter(WatchPool.id == scope).first()
            if not pool:
                task.status = "failed"
                task.message = "观察池不存在"
                return
            stocks = db.query(WatchStock).filter(WatchStock.pool_id == scope).all()
            for ws in stocks:
                df = _get_df_from_db(db, ws.ts_code)
                if not df.empty:
                    stock_dfs[ws.ts_code] = df
                basic = db.query(StockBasic).filter(StockBasic.ts_code == ws.ts_code).first()
                name_map[ws.ts_code] = basic.name if basic else ""

        conditions = conditions[:10]
        logic = logic or "and"
        matched = []
        total = len(stock_dfs)
        for i, (ts_code, df) in enumerate(stock_dfs.items()):
            task.progress = (i + 1) / total if total else 1.0
            task.message = f"已筛选 {i+1}/{total}"
            results = []
            for cond in conditions:
                tid = cond.get("template_id")
                params = cond.get("params", {})
                if tid and tid in SCREEN_TEMPLATES:
                    results.append(_eval_condition(df, tid, params))
            if not results:
                continue
            if logic == "and":
                if all(results):
                    matched.append(ts_code)
            else:
                if any(results):
                    matched.append(ts_code)

        task.result = {
            "ts_codes": matched,
            "stock_names": {c: name_map.get(c, "") for c in matched},
            "total": len(matched),
        }
        task.status = "completed"
        task.progress = 1.0
        task.message = f"筛选完成，共 {len(matched)} 只"
    except Exception as e:
        task.status = "failed"
        task.message = str(e)
    finally:
        db.close()


def run_limit_up_buy_point_screen(
    task_id: str,
    trade_date_from: str,
    trade_date_to: str,
    conditions: list[dict],
    logic: str,
):
    """
    涨停回调买点选股：按日期范围拉取涨停股 → 同步 K 线 → 评估买点规则 → 返回结果。
    不写入涨停池。
    """
    task = task_registry.get(task_id)
    if not task:
        return
    db = SessionLocal()
    try:
        task.message = "正在同步股票基础信息..."
        try:
            _sync_stock_basic_full(db)
        except Exception:
            pass

        task.message = "正在拉取日期范围内的涨停股..."
        limit_up_map = fetch_limit_up_stocks_in_range(db, trade_date_from, trade_date_to)
        if not limit_up_map:
            task.result = {"ts_codes": [], "stock_names": {}, "total": 0}
            task.status = "completed"
            task.progress = 1.0
            task.message = "日期范围内无涨停股"
            return

        stocks = list(limit_up_map.items())
        total_stocks = len(stocks)
        conditions = conditions[:10]
        logic = logic or "and"
        matched: list[str] = []
        name_map: dict[str, str] = {}

        for i, (ts_code, limit_up_date) in enumerate(stocks):
            task.progress = (i + 1) / total_stocks
            task.message = f"处理 {i+1}/{total_stocks}：{ts_code}"

            df = _get_df(db, ts_code)
            if df.empty or len(df) < 5:
                try:
                    sync_stock_info(db, ts_code)
                except Exception:
                    pass
                sync_daily(db, ts_code, 60)
                df = _get_df(db, ts_code)
            if df.empty or len(df) < 5:
                continue

            basic = db.query(StockBasic).filter(StockBasic.ts_code == ts_code).first()
            name_map[ts_code] = basic.name if basic else ""

            watch_stock = types.SimpleNamespace(limit_up_date=limit_up_date)
            results = []
            for cond in conditions:
                tid = cond.get("template_id")
                params = cond.get("params", {})
                if tid and tid in LIMIT_UP_BUY_POINT_TEMPLATES:
                    results.append(evaluate_template(df, tid, params, watch_stock))
            if not results:
                continue
            if logic == "and":
                if all(results):
                    matched.append(ts_code)
            else:
                if any(results):
                    matched.append(ts_code)

        task.result = {
            "ts_codes": matched,
            "stock_names": {c: name_map.get(c, "") for c in matched},
            "total": len(matched),
        }
        task.status = "completed"
        task.progress = 1.0
        task.message = f"筛选完成，共 {len(matched)} 只"
    except Exception as e:
        task.status = "failed"
        task.message = str(e)
    finally:
        db.close()
