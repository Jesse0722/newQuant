from __future__ import annotations

from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from app.models.sector import SectorBasic, SectorDailyQuote, StockSectorMap
from app.models.pool import WatchStock
from app.models.stock import DailyQuote, StockBasic
from app.services.indicator import calc_ma, calc_vol_ma
from app.services.sector_data_service import SOURCE as SECTOR_SOURCE, fetch_stock_concept_sectors

MAIN_WAVE_THEME_KEYWORDS = (
    "AI",
    "算力",
    "服务器",
    "CPO",
    "光模块",
    "存储",
    "HBM",
    "DRAM",
    "机器人",
    "人形机器人",
    "商业航天",
    "卫星",
    "半导体",
    "芯片",
    "PCB",
    "液冷",
    "电力",
    "数据中心",
)


def _quote_df(db: Session, ts_code: str, limit: int = 180) -> pd.DataFrame:
    rows = (
        db.query(DailyQuote)
        .filter(DailyQuote.ts_code == ts_code)
        .order_by(DailyQuote.trade_date.desc())
        .limit(limit)
        .all()
    )
    if not rows:
        return pd.DataFrame()
    rows = list(reversed(rows))
    return pd.DataFrame(
        [
            {
                "trade_date": r.trade_date,
                "open": r.open,
                "high": r.high,
                "low": r.low,
                "close": r.close,
                "pct_chg": r.pct_chg,
                "vol": r.vol,
                "amount": r.amount,
                "turnover_rate": r.turnover_rate,
            }
            for r in rows
        ]
    )


def _sector_quote_df(db: Session, sector_code: str, limit: int = 80) -> pd.DataFrame:
    rows = (
        db.query(SectorDailyQuote)
        .filter(SectorDailyQuote.sector_code == sector_code)
        .order_by(SectorDailyQuote.trade_date.desc())
        .limit(limit)
        .all()
    )
    if not rows:
        return pd.DataFrame()
    rows = list(reversed(rows))
    return pd.DataFrame(
        [
            {
                "trade_date": r.trade_date,
                "close": r.close,
                "pct_chg": r.pct_chg,
            }
            for r in rows
            if r.close is not None
        ]
    )


def _theme_keyword_score(name: str) -> int:
    text = str(name or "")
    return sum(1 for keyword in MAIN_WAVE_THEME_KEYWORDS if keyword.lower() in text.lower())


def _sector_recent_quote_count(db: Session, sector_code: str | None) -> int:
    if not sector_code:
        return 0
    return (
        db.query(SectorDailyQuote)
        .filter(SectorDailyQuote.sector_code == sector_code)
        .count()
    )


def _rank_sector_candidates(db: Session, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    dedup: dict[str, dict[str, Any]] = {}
    for item in candidates:
        name = str(item.get("sector_name") or "").strip()
        if not name:
            continue
        key = f"{item.get('sector_type') or 'concept'}|{name}"
        if key not in dedup:
            dedup[key] = item
    rows = list(dedup.values())

    def sort_key(item: dict[str, Any]) -> tuple:
        sector_type = item.get("sector_type") or "concept"
        sector_code = item.get("sector_code")
        hot = item.get("latest_hot")
        pct = item.get("latest_pct_chg")
        return (
            0 if sector_type == "concept" else 1,
            -_theme_keyword_score(str(item.get("sector_name") or "")),
            -_sector_recent_quote_count(db, str(sector_code) if sector_code else None),
            -(float(hot) if hot is not None else 0.0),
            -(float(pct) if pct is not None else 0.0),
            str(item.get("sector_name") or ""),
        )

    return sorted(rows, key=sort_key)


def get_relevant_concept_candidates(db: Session, ts_code: str, limit: int = 8) -> list[dict[str, Any]]:
    """返回个股最相关概念候选，概念板块优先，行业仅作兜底。"""
    code = ts_code.upper()
    basic = db.query(StockBasic).filter(StockBasic.ts_code == code).first()
    rows: list[dict[str, Any]] = []
    try:
        rows.extend(fetch_stock_concept_sectors(code))
    except Exception:
        pass
    names = [str(row.get("sector_name")) for row in rows if row.get("sector_name")]
    if basic and basic.industry and basic.industry not in names:
        names.append(basic.industry)

    candidates: list[dict[str, Any]] = []
    for row in rows[:24]:
        sector_code = row.get("sector_code")
        name = str(row.get("sector_name") or "").strip()
        if not name:
            continue
        sector = None
        if sector_code:
            sector = db.query(SectorBasic).filter(SectorBasic.sector_code == str(sector_code)).first()
        if sector is None:
            sector = (
                db.query(SectorBasic)
                .filter(SectorBasic.sector_name == name)
                .order_by((SectorBasic.source != SECTOR_SOURCE).asc(), SectorBasic.sector_type.asc())
                .first()
            )
        candidates.append(
            {
                "sector_code": sector.sector_code if sector else sector_code,
                "sector_name": name,
                "sector_type": sector.sector_type if sector else "concept",
                "latest_hot": sector.latest_hot if sector else row.get("latest_hot"),
                "latest_pct_chg": sector.latest_pct_chg if sector else row.get("latest_pct_chg"),
            }
        )

    for name in names[len(rows):24]:
        sector = (
            db.query(SectorBasic)
            .filter(SectorBasic.sector_name == name)
            .order_by((SectorBasic.source != SECTOR_SOURCE).asc(), SectorBasic.sector_type.asc())
            .first()
        )
        candidates.append(
            {
                "sector_code": sector.sector_code if sector else None,
                "sector_name": name,
                "sector_type": sector.sector_type if sector else "concept",
                "latest_hot": sector.latest_hot if sector else None,
                "latest_pct_chg": sector.latest_pct_chg if sector else None,
            }
        )
    return _rank_sector_candidates(db, candidates)[:limit]


def _pct_return(df: pd.DataFrame, days: int) -> float | None:
    if len(df) <= days:
        return None
    base = float(df.iloc[-days - 1]["close"])
    latest = float(df.iloc[-1]["close"])
    if base <= 0:
        return None
    return round((latest - base) / base * 100, 2)


def _max_drawdown_pct(close: pd.Series) -> float:
    if close.empty:
        return 0.0
    peak = close.cummax()
    dd = (close - peak) / peak.replace(0, pd.NA) * 100
    return round(abs(float(dd.min() or 0.0)), 2)


def _ma20_state(df: pd.DataFrame) -> dict[str, Any]:
    latest = df.iloc[-1]
    ma20 = latest.get("ma20")
    if ma20 is None or pd.isna(ma20) or ma20 <= 0:
        return {"state": "unknown", "break_days": 0, "distance_pct": None}

    below = df["close"] < df["ma20"]
    break_days = 0
    for ok in reversed(below.tail(10).tolist()):
        if ok:
            break_days += 1
        else:
            break

    distance_pct = round((float(latest["close"]) - float(ma20)) / float(ma20) * 100, 2)
    if distance_pct >= 0:
        recent_below = below.tail(4).iloc[:-1].any() if len(below) >= 4 else below.any()
        return {
            "state": "repaired" if recent_below else "above",
            "break_days": 0,
            "distance_pct": distance_pct,
        }
    if break_days >= 3 or distance_pct <= -5:
        state = "effective_break"
    else:
        state = "break_warning"
    return {"state": state, "break_days": break_days, "distance_pct": distance_pct}


def _trend_score(df: pd.DataFrame) -> tuple[int, list[str]]:
    latest = df.iloc[-1]
    score = 0
    reasons: list[str] = []
    if latest["close"] > latest.get("ma20", float("inf")):
        score += 8
        reasons.append("收盘价在MA20上方")
    if latest.get("ma5") > latest.get("ma10") > latest.get("ma20"):
        score += 10
        reasons.append("MA5>MA10>MA20")
    if len(df) >= 11 and df.iloc[-1]["ma20"] > df.iloc[-11]["ma20"]:
        score += 8
        reasons.append("MA20近10日上行")
    if len(df) >= 21 and latest["close"] >= df["close"].tail(20).max():
        score += 8
        reasons.append("近20日收盘新高")
    ret60 = _pct_return(df, 60)
    if ret60 is not None and ret60 >= 20:
        score += 6
        reasons.append("近60日涨幅达到20%以上")
    return min(score, 40), reasons


def _structure_score(df: pd.DataFrame) -> tuple[int, list[str], dict[str, Any]]:
    score = 0
    reasons: list[str] = []
    metrics: dict[str, Any] = {}
    if len(df) < 80:
        return score, reasons, metrics

    prev_high = df["close"].shift(1).rolling(60).max()
    recent = df.tail(20).copy()
    breakout_rows = recent[recent["close"] >= prev_high.loc[recent.index]]
    if not breakout_rows.empty:
        breakout_idx = breakout_rows.index[-1]
        breakout = df.loc[breakout_idx]
        metrics["breakout_date"] = str(breakout["trade_date"])
        metrics["breakout_price"] = round(float(breakout["close"]), 2)
        score += 8
        reasons.append("近20日突破60日新高")
        vol_ma20 = breakout.get("vol_ma20")
        if vol_ma20 is not None and not pd.isna(vol_ma20) and float(vol_ma20) > 0:
            if float(breakout["vol"]) >= float(vol_ma20) * 1.5:
                score += 6
                reasons.append("突破日放量达到20日均量1.5倍")
        post = df.loc[breakout_idx:]
        if not post.empty and post["close"].min() >= float(breakout["close"]) * 0.97:
            score += 5
            reasons.append("突破后未有效跌回突破价")

    recent10 = df.tail(10)
    above_short_ma = ((recent10["close"] >= recent10["ma5"]) | (recent10["close"] >= recent10["ma10"])).sum()
    metrics["above_short_ma_days_10"] = int(above_short_ma)
    if above_short_ma >= 6:
        score += 6
        reasons.append("近10日至少6日站在MA5/MA10上方")
    return min(score, 25), reasons, metrics


def _pullback_score(df: pd.DataFrame, ma20: dict[str, Any]) -> tuple[int, list[str], dict[str, Any]]:
    score = 0
    reasons: list[str] = []
    recent10 = df.tail(10)
    drawdown = _max_drawdown_pct(recent10["close"])
    if drawdown <= 12:
        score += 5
        reasons.append("近10日最大回撤不超过12%")
    latest = df.iloc[-1]
    if latest["close"] >= latest.get("ma10", float("inf")):
        score += 5
        reasons.append("当前未有效跌破MA10")

    recent20 = df.tail(20)
    up = recent20[recent20["pct_chg"] > 0]["vol"].mean()
    down = recent20[recent20["pct_chg"] < 0]["vol"].mean()
    if pd.notna(up) and pd.notna(down) and down < up:
        score += 5
        reasons.append("回调日均量低于上涨日均量")
    if len(df) >= 2 and latest["close"] >= latest["ma5"] and df.iloc[-2]["close"] < df.iloc[-2]["ma5"]:
        score += 5
        reasons.append("重新收复MA5")
    elif ma20["state"] == "repaired":
        score += 5
        reasons.append("跌破MA20后快速修复")
    return min(score, 20), reasons, {"max_drawdown_10d": drawdown}


def _sector_resonance_score(db: Session, ts_code: str, df: pd.DataFrame) -> tuple[int, list[str], dict[str, Any]]:
    maps_q = (
        db.query(StockSectorMap)
        .filter(StockSectorMap.ts_code == ts_code)
    )
    source_maps = maps_q.filter(StockSectorMap.source == SECTOR_SOURCE).all()
    maps = source_maps or (
        maps_q.order_by(StockSectorMap.sector_type.asc(), StockSectorMap.sector_name.asc()).limit(12).all()
    )
    candidates = [
        {
            "sector_code": m.sector_code,
            "sector_name": m.sector_name,
            "sector_type": m.sector_type,
            "latest_hot": None,
            "latest_pct_chg": None,
        }
        for m in maps
    ]
    if not candidates:
        candidates = get_relevant_concept_candidates(db, ts_code, limit=8)
    candidates = _rank_sector_candidates(db, candidates)
    stock_ret20 = _pct_return(df, 20)
    stock_dd20 = _max_drawdown_pct(df.tail(20)["close"])
    best: dict[str, Any] | None = None
    best_score = 0
    best_reasons: list[str] = []

    for m in candidates:
        if best is None:
            best = {
                "sector_code": m.get("sector_code"),
                "sector_name": m.get("sector_name"),
                "sector_type": m.get("sector_type"),
                "sector_return_20d": None,
                "stock_return_20d": stock_ret20,
                "relative_strength_20d": None,
                "sync_ratio_20d": None,
                "stock_drawdown_20d": stock_dd20,
                "sector_drawdown_20d": None,
            }
        if not m.get("sector_code"):
            continue
        sdf = _sector_quote_df(db, str(m["sector_code"]), limit=40)
        if len(sdf) < 21 or stock_ret20 is None:
            continue
        sector_ret20 = _pct_return(sdf, 20)
        if sector_ret20 is None:
            continue
        score = 0
        reasons: list[str] = []
        if sector_ret20 >= 8:
            score += 4
            reasons.append("所属板块20日涨幅较强")
        relative = round(stock_ret20 - sector_ret20, 2)
        if relative > 0:
            score += 5
            reasons.append("个股20日涨幅强于板块")
        merged = df[["trade_date", "pct_chg"]].tail(20).merge(
            sdf[["trade_date", "pct_chg"]].tail(20),
            on="trade_date",
            suffixes=("_stock", "_sector"),
        )
        sync_ratio = None
        if not merged.empty:
            sync_ratio = round(float(((merged["pct_chg_stock"] > 0) & (merged["pct_chg_sector"] > 0)).sum()) / len(merged), 3)
            if sync_ratio >= 0.45:
                score += 3
                reasons.append("个股与板块同涨同步率较高")
        sector_dd20 = _max_drawdown_pct(sdf.tail(20)["close"])
        if stock_dd20 < sector_dd20:
            score += 3
            reasons.append("板块回撤时个股更抗跌")
        if score > best_score:
            best_score = score
            best_reasons = reasons
            best = {
                "sector_code": m.get("sector_code"),
                "sector_name": m.get("sector_name"),
                "sector_type": m.get("sector_type"),
                "sector_return_20d": sector_ret20,
                "stock_return_20d": stock_ret20,
                "relative_strength_20d": relative,
                "sync_ratio_20d": sync_ratio,
                "stock_drawdown_20d": stock_dd20,
                "sector_drawdown_20d": sector_dd20,
            }

    return min(best_score, 15), best_reasons, {"best_sector": best, "sector_count": len(candidates)}


def _status(total_score: int, ma20_state: str) -> str:
    if ma20_state == "effective_break":
        return "exit_signal"
    if total_score >= 80:
        return "main_wave_confirmed"
    if total_score >= 70:
        return "breakout_tracking"
    if total_score >= 60:
        return "watching"
    if ma20_state == "break_warning":
        return "divergence_warning"
    return "invalidated"


def analyze_main_wave_stock(db: Session, ts_code: str) -> dict[str, Any]:
    code = ts_code.upper()
    df = _quote_df(db, code)
    basic = db.query(StockBasic).filter(StockBasic.ts_code == code).first()
    if df.empty or len(df) < 60:
        return {
            "ts_code": code,
            "name": basic.name if basic else code,
            "status": "insufficient_data",
            "total_score": 0,
            "message": "日线数据不足，至少需要60个交易日",
        }

    df = df.copy()
    df["ma5"] = calc_ma(df, 5)
    df["ma10"] = calc_ma(df, 10)
    df["ma20"] = calc_ma(df, 20)
    df["vol_ma20"] = calc_vol_ma(df, 20)
    if "pct_chg" not in df.columns or df["pct_chg"].isna().all():
        df["pct_chg"] = df["close"].pct_change() * 100

    ma20 = _ma20_state(df)
    trend_score, trend_reasons = _trend_score(df)
    structure_score, structure_reasons, structure_metrics = _structure_score(df)
    pullback_score, pullback_reasons, pullback_metrics = _pullback_score(df, ma20)
    sector_score, sector_reasons, sector_metrics = _sector_resonance_score(db, code, df)
    total = trend_score + structure_score + pullback_score + sector_score

    latest = df.iloc[-1]
    return {
        "ts_code": code,
        "name": basic.name if basic else code,
        "industry": basic.industry if basic else None,
        "trade_date": str(latest["trade_date"]),
        "status": _status(total, ma20["state"]),
        "total_score": int(total),
        "scores": {
            "trend": trend_score,
            "structure": structure_score,
            "pullback_repair": pullback_score,
            "sector_resonance": sector_score,
        },
        "ma20_state": ma20,
        "metrics": {
            "latest_close": round(float(latest["close"]), 2),
            "return_20d": _pct_return(df, 20),
            "return_60d": _pct_return(df, 60),
            **structure_metrics,
            **pullback_metrics,
            **sector_metrics,
        },
        "reasons": {
            "trend": trend_reasons,
            "structure": structure_reasons,
            "pullback_repair": pullback_reasons,
            "sector_resonance": sector_reasons,
        },
    }


def scan_main_wave_pool(
    db: Session,
    *,
    pool_id: str | None = None,
    min_score: int | None = None,
    statuses: list[str] | None = None,
) -> dict[str, Any]:
    q = db.query(WatchStock)
    if pool_id:
        q = q.filter(WatchStock.pool_id == pool_id)
    stocks = q.order_by(WatchStock.pinned.desc(), WatchStock.created_at.desc()).all()
    status_set = set(statuses or [])
    rows: list[dict[str, Any]] = []
    for stock in stocks:
        item = analyze_main_wave_stock(db, stock.ts_code)
        if min_score is not None and int(item.get("total_score") or 0) < min_score:
            continue
        if status_set and item.get("status") not in status_set:
            continue
        item["watch_stock_id"] = stock.id
        item["pool_id"] = stock.pool_id
        item["pinned"] = bool(stock.pinned)
        item["note"] = stock.note
        rows.append(item)
    rows.sort(key=lambda x: (not x.get("pinned"), -(int(x.get("total_score") or 0)), str(x.get("ts_code") or "")))
    return {
        "total": len(rows),
        "items": rows,
        "summary": {
            "main_wave_confirmed": sum(1 for x in rows if x.get("status") == "main_wave_confirmed"),
            "breakout_tracking": sum(1 for x in rows if x.get("status") == "breakout_tracking"),
            "watching": sum(1 for x in rows if x.get("status") == "watching"),
            "divergence_warning": sum(1 for x in rows if x.get("status") == "divergence_warning"),
            "exit_signal": sum(1 for x in rows if x.get("status") == "exit_signal"),
            "ma20_repaired": sum(1 for x in rows if (x.get("ma20_state") or {}).get("state") == "repaired"),
        },
    }
