from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Callable

import pandas as pd
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.pool import WatchStock
from app.models.sector import StockSectorMap
from app.models.stock import DailyQuote
from app.services.main_wave_service import analyze_main_wave_stock, _market_group, _market_group_filter
from app.tasks.background import task_registry

DEFAULT_ENTRY_STAGES = ["pullback_entry_watch", "breakout_wait_pullback", "trend_hold"]
DEFAULT_HOLDING_DAYS = [1, 3, 5, 10]
QUOTE_PRELOAD_LOOKBACK_DAYS = 420
QUOTE_PRELOAD_MAX_CODES = 1200
QUOTE_PRELOAD_CHUNK_SIZE = 400


def _chunked(values: list[str], size: int) -> list[list[str]]:
    return [values[i:i + size] for i in range(0, len(values), size)]


def _trade_dates(db: Session, start_date: str, end_date: str) -> list[str]:
    rows = (
        db.query(DailyQuote.trade_date)
        .filter(DailyQuote.trade_date >= start_date, DailyQuote.trade_date <= end_date)
        .group_by(DailyQuote.trade_date)
        .order_by(DailyQuote.trade_date.asc())
        .all()
    )
    return [str(r[0]) for r in rows if r[0]]


def _scope_codes(db: Session, scope: str, sector_codes: list[str], sector_logic: str) -> list[str]:
    if scope and scope != "full":
        codes = [
            row[0]
            for row in (
                db.query(WatchStock.ts_code)
                .filter(WatchStock.pool_id == scope)
                .order_by(WatchStock.pinned.desc(), WatchStock.created_at.desc())
                .all()
            )
            if row[0]
        ]
    elif sector_codes:
        q = (
            db.query(StockSectorMap.ts_code, func.count(func.distinct(StockSectorMap.sector_code)).label("hit_count"))
            .filter(StockSectorMap.sector_code.in_(sector_codes))
            .group_by(StockSectorMap.ts_code)
        )
        if sector_logic == "all":
            q = q.having(func.count(func.distinct(StockSectorMap.sector_code)) >= len(set(sector_codes)))
        codes = [row[0] for row in q.all() if row[0]]
    else:
        codes = [
            row[0]
            for row in (
                db.query(DailyQuote.ts_code)
                .filter(DailyQuote.ts_code.like("%.S%"))
                .group_by(DailyQuote.ts_code)
                .all()
            )
            if row[0]
        ]

    if sector_codes and scope and scope != "full":
        scoped = set(codes)
        sector_q = (
            db.query(StockSectorMap.ts_code, func.count(func.distinct(StockSectorMap.sector_code)).label("hit_count"))
            .filter(StockSectorMap.sector_code.in_(sector_codes), StockSectorMap.ts_code.in_(scoped))
            .group_by(StockSectorMap.ts_code)
        )
        if sector_logic == "all":
            sector_q = sector_q.having(func.count(func.distinct(StockSectorMap.sector_code)) >= len(set(sector_codes)))
        codes = [row[0] for row in sector_q.all() if row[0]]

    return sorted(set(codes))


def _preload_start_date(trade_date_from: str) -> str:
    try:
        start = datetime.strptime(trade_date_from, "%Y%m%d") - timedelta(days=QUOTE_PRELOAD_LOOKBACK_DAYS)
        return start.strftime("%Y%m%d")
    except ValueError:
        return trade_date_from


def _prime_quote_history(
    db: Session,
    *,
    codes: list[str],
    trade_date_from: str,
    trade_date_to: str,
    cache: dict[str, dict[Any, Any]],
) -> dict[str, Any]:
    preload = {
        "enabled": False,
        "loaded_codes": 0,
        "row_count": 0,
        "start_date": _preload_start_date(trade_date_from),
        "end_date": trade_date_to,
        "skipped_reason": None,
    }
    if not codes:
        preload["skipped_reason"] = "empty_scope"
        return preload
    if len(codes) > QUOTE_PRELOAD_MAX_CODES:
        preload["skipped_reason"] = "scope_too_large"
        return preload

    history_bucket = cache.setdefault("quote_history", {})
    columns = ["trade_date", "open", "high", "low", "close", "pct_chg", "vol", "amount", "turnover_rate"]
    for chunk in _chunked(codes, QUOTE_PRELOAD_CHUNK_SIZE):
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
            )
            .filter(
                DailyQuote.ts_code.in_(chunk),
                DailyQuote.trade_date >= preload["start_date"],
                DailyQuote.trade_date <= trade_date_to,
            )
            .order_by(DailyQuote.ts_code.asc(), DailyQuote.trade_date.asc())
            .all()
        )
        if not rows:
            continue
        raw = pd.DataFrame(
            [
                {
                    "ts_code": r.ts_code,
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
        for ts_code, group in raw.groupby("ts_code"):
            history_bucket[str(ts_code)] = group[columns].sort_values("trade_date").reset_index(drop=True)

    preload["enabled"] = True
    preload["loaded_codes"] = len(history_bucket)
    preload["row_count"] = int(sum(len(df) for df in history_bucket.values()))
    return preload


def _prime_market_proxy_history(
    db: Session,
    *,
    codes: list[str],
    trade_date_from: str,
    trade_date_to: str,
    cache: dict[str, dict[Any, Any]],
) -> dict[str, Any]:
    preload = {
        "enabled": False,
        "groups": [],
        "row_count": 0,
        "start_date": _preload_start_date(trade_date_from),
        "end_date": trade_date_to,
        "skipped_reason": None,
    }
    if not codes:
        preload["skipped_reason"] = "empty_scope"
        return preload
    if len(codes) > QUOTE_PRELOAD_MAX_CODES:
        preload["skipped_reason"] = "scope_too_large"
        return preload

    groups = sorted({_market_group(code) for code in codes})
    history_bucket = cache.setdefault("market_proxy_history", {})
    for group in groups:
        condition = _market_group_filter(group)
        rows = (
            db.query(DailyQuote.trade_date, DailyQuote.ts_code, DailyQuote.close, DailyQuote.pct_chg)
            .filter(
                condition,
                DailyQuote.trade_date >= preload["start_date"],
                DailyQuote.trade_date <= trade_date_to,
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
                    "trade_date": r.trade_date,
                    "ts_code": r.ts_code,
                    "close": r.close,
                    "pct_chg": r.pct_chg,
                }
                for r in rows
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
            .agg(
                pct_chg=("pct_chg", "mean"),
                member_count=("ts_code", "nunique"),
            )
            .sort_values("trade_date")
        )
        if grouped.empty:
            continue
        close = 1000.0
        closes = []
        for pct_chg in grouped["pct_chg"].tolist():
            close *= 1 + float(pct_chg) / 100
            closes.append(round(close, 4))
        grouped["close"] = closes
        grouped["pct_chg"] = grouped["pct_chg"].round(4)
        history_bucket[group] = grouped.reset_index(drop=True)

    preload["enabled"] = True
    preload["groups"] = sorted(history_bucket.keys())
    preload["row_count"] = int(sum(len(df) for df in history_bucket.values()))
    return preload


def _passes_filters(item: dict[str, Any], params: dict[str, Any]) -> bool:
    if item.get("status") == "insufficient_data":
        return False
    if params.get("exclude_effective_break", True) and item.get("status") == "exit_signal":
        return False
    statuses = set(params.get("statuses") or [])
    if statuses and item.get("status") not in statuses:
        return False
    min_score = params.get("min_score")
    if min_score is not None and int(item.get("total_score") or 0) < int(min_score):
        return False

    entry = item.get("entry") or {}
    entry_stages = set(params.get("entry_stages") or DEFAULT_ENTRY_STAGES)
    if entry_stages and entry.get("stage") not in entry_stages:
        return False
    min_entry_score = params.get("min_entry_score")
    if min_entry_score is not None and int(entry.get("score") or 0) < int(min_entry_score):
        return False
    if params.get("exclude_overheat", True) and entry.get("stage") == "avoid_chase":
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

    if params.get("require_sector_resonance", False) and int((item.get("scores") or {}).get("sector_resonance") or 0) <= 0:
        return False
    return True


def _future_returns(db: Session, ts_code: str, trade_date: str, entry_price: float, holding_days: list[int]) -> dict[str, float | None]:
    rows = (
        db.query(DailyQuote.trade_date, DailyQuote.close)
        .filter(DailyQuote.ts_code == ts_code, DailyQuote.trade_date > trade_date, DailyQuote.close.isnot(None))
        .order_by(DailyQuote.trade_date.asc())
        .limit(max(holding_days or [1]))
        .all()
    )
    returns: dict[str, float | None] = {}
    for day in holding_days:
        value = None
        if len(rows) >= day and entry_price > 0:
            value = round((float(rows[day - 1].close) - entry_price) / entry_price * 100, 2)
        returns[f"return_{day}d"] = value
    return returns


def _avg(values: list[float]) -> float:
    return round(sum(values) / len(values), 2) if values else 0.0


def _win_rate(values: list[float]) -> float:
    return round(sum(1 for v in values if v > 0) / len(values) * 100, 1) if values else 0.0


def _summary(signals: list[dict[str, Any]], holding_days: list[int]) -> dict[str, Any]:
    out: dict[str, Any] = {"total_signals": len(signals)}
    for day in holding_days:
        key = f"return_{day}d"
        vals = [float(s[key]) for s in signals if s.get(key) is not None]
        out[f"covered_{day}d"] = len(vals)
        out[f"avg_return_{day}d"] = _avg(vals)
        out[f"win_rate_{day}d"] = _win_rate(vals)
    return out


def _group_summary(signals: list[dict[str, Any]], group_key: str, holding_days: list[int]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for signal in signals:
        groups[str(signal.get(group_key) or "unknown")].append(signal)
    return [
        {"group": key, **_summary(rows, holding_days)}
        for key, rows in sorted(groups.items(), key=lambda item: (-len(item[1]), item[0]))
    ]


def _primary_holding_day(holding_days: list[int]) -> int:
    if 5 in holding_days:
        return 5
    return holding_days[min(len(holding_days) - 1, 1)] if holding_days else 1


def _numeric_bucket_start(group: str) -> int:
    if group == "100":
        return 100
    try:
        return int(str(group).split("-")[0])
    except (TypeError, ValueError):
        return 0


def _backtest_quality_notes(summary: dict[str, Any], date_count: int, holding_days: list[int]) -> list[str]:
    notes: list[str] = []
    total = int(summary.get("total_signals") or 0)
    if total < 30:
        notes.append("样本少于30个信号，当前结果更适合做规则排雷，不适合直接定参数。")
    if date_count < 10:
        notes.append("回测交易日少于10天，容易受单一行情阶段影响。")
    for day in holding_days:
        covered = int(summary.get(f"covered_{day}d") or 0)
        if covered < total:
            notes.append(f"{day}日收益覆盖 {covered}/{total}，靠近最新日期的信号未来K线不足。")
    return notes


def _backtest_recommendations(
    *,
    stage_summary: list[dict[str, Any]],
    status_summary: list[dict[str, Any]],
    score_summary: list[dict[str, Any]],
    holding_days: list[int],
) -> list[dict[str, Any]]:
    day = _primary_holding_day(holding_days)
    avg_key = f"avg_return_{day}d"
    win_key = f"win_rate_{day}d"

    def enough(row: dict[str, Any]) -> bool:
        return int(row.get("total_signals") or 0) >= 5

    recommendations: list[dict[str, Any]] = []
    usable_stages = [row for row in stage_summary if enough(row)]
    if usable_stages:
        best = max(usable_stages, key=lambda row: float(row.get(avg_key) or 0))
        recommendations.append(
            {
                "type": "entry_stage_focus",
                "level": "observe",
                "message": f"{best['group']} 在{day}日维度表现相对占优，可作为下一轮优先观察的买点阶段。",
                "evidence": f"样本 {best.get('total_signals')}，均值 {best.get(avg_key, 0)}%，胜率 {best.get(win_key, 0)}%。",
            }
        )
        weak = [
            row for row in usable_stages
            if float(row.get(avg_key) or 0) < 0 and float(row.get(win_key) or 0) < 50
        ]
        for row in weak[:2]:
            recommendations.append(
                {
                    "type": "entry_stage_tighten",
                    "level": "risk",
                    "message": f"{row['group']} 当前回测偏弱，建议先收窄或提高买点分阈值再验证。",
                    "evidence": f"样本 {row.get('total_signals')}，{day}日均值 {row.get(avg_key, 0)}%，胜率 {row.get(win_key, 0)}%。",
                }
            )

    usable_statuses = [row for row in status_summary if enough(row)]
    weak_statuses = [
        row for row in usable_statuses
        if str(row.get("group")) in {"divergence_warning", "exit_signal"} or float(row.get(avg_key) or 0) < 0
    ]
    for row in weak_statuses[:2]:
        recommendations.append(
            {
                "type": "status_filter",
                "level": "risk",
                "message": f"{row['group']} 不宜进入默认候选，可继续保持过滤或单独观察。",
                "evidence": f"样本 {row.get('total_signals')}，{day}日均值 {row.get(avg_key, 0)}%，胜率 {row.get(win_key, 0)}%。",
            }
        )

    usable_scores = sorted([row for row in score_summary if enough(row)], key=lambda row: _numeric_bucket_start(str(row.get("group"))))
    if len(usable_scores) >= 2:
        low = usable_scores[0]
        high = usable_scores[-1]
        if float(high.get(avg_key) or 0) <= float(low.get(avg_key) or 0):
            recommendations.append(
                {
                    "type": "score_calibration",
                    "level": "observe",
                    "message": "高总分组未明显跑赢低总分组，总分权重需要继续用更长样本校准。",
                    "evidence": f"低分组 {low['group']} 均值 {low.get(avg_key, 0)}%，高分组 {high['group']} 均值 {high.get(avg_key, 0)}%。",
                }
            )

    return recommendations[:6]


def run_main_wave_backtest(
    db: Session,
    *,
    trade_date_from: str,
    trade_date_to: str,
    params: dict[str, Any],
    max_signals_per_day: int = 20,
    cooldown_days: int = 5,
    progress_callback: Callable[[float, str], None] | None = None,
) -> dict[str, Any]:
    holding_days = sorted({int(x) for x in (params.get("holding_days") or DEFAULT_HOLDING_DAYS) if int(x) > 0})[:4]
    entry_stages = params.get("entry_stages") or DEFAULT_ENTRY_STAGES
    scope = str(params.get("scope") or "full")
    sector_codes = [str(x) for x in (params.get("sector_codes") or []) if x]
    sector_logic = str(params.get("sector_logic") or "any")
    codes = _scope_codes(db, scope, sector_codes, sector_logic)
    dates = _trade_dates(db, trade_date_from, trade_date_to)
    cache: dict = {}
    preload = _prime_quote_history(
        db,
        codes=codes,
        trade_date_from=trade_date_from,
        trade_date_to=trade_date_to,
        cache=cache,
    )
    market_preload = _prime_market_proxy_history(
        db,
        codes=codes,
        trade_date_from=trade_date_from,
        trade_date_to=trade_date_to,
        cache=cache,
    )
    signals: list[dict[str, Any]] = []
    last_signal_idx: dict[str, int] = {}

    total_dates = len(dates)
    for date_idx, trade_date in enumerate(dates):
        if progress_callback:
            progress_callback(
                0.05 + (date_idx / max(total_dates, 1)) * 0.9,
                f"主升浪回测 {date_idx + 1}/{total_dates}：{trade_date}",
            )
        daily_candidates: list[dict[str, Any]] = []
        for ts_code in codes:
            if ts_code in last_signal_idx and date_idx - last_signal_idx[ts_code] <= cooldown_days:
                continue
            item = analyze_main_wave_stock(
                db,
                ts_code,
                preferred_sector_codes=sector_codes or None,
                allow_external_sector_fetch=False,
                cache=cache,
                as_of_date=trade_date,
            )
            if item.get("trade_date") != trade_date:
                continue
            if not _passes_filters(item, {**params, "entry_stages": entry_stages}):
                continue
            daily_candidates.append(item)

        daily_candidates.sort(
            key=lambda x: (
                -(int(x.get("total_score") or 0)),
                -(int((x.get("entry") or {}).get("score") or 0)),
                str(x.get("ts_code") or ""),
            )
        )
        for item in daily_candidates[:max_signals_per_day]:
            latest_close = float((item.get("metrics") or {}).get("latest_close") or 0)
            if latest_close <= 0:
                continue
            returns = _future_returns(db, item["ts_code"], trade_date, latest_close, holding_days)
            signal = {
                "ts_code": item["ts_code"],
                "stock_name": item.get("name") or "",
                "trigger_date": trade_date,
                "entry_price": latest_close,
                "total_score": int(item.get("total_score") or 0),
                "status": item.get("status"),
                "entry_stage": (item.get("entry") or {}).get("stage"),
                "entry_score": (item.get("entry") or {}).get("score"),
                "sector_score": (item.get("scores") or {}).get("sector_resonance") or 0,
                "market_relative_score": (item.get("scores") or {}).get("market_relative") or 0,
                **returns,
            }
            signals.append(signal)
            last_signal_idx[item["ts_code"]] = date_idx

    summary = _summary(signals, holding_days)
    score_buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for signal in signals:
        score = int(signal.get("total_score") or 0)
        bucket = f"{score // 10 * 10}-{score // 10 * 10 + 9}"
        if score >= 100:
            bucket = "100"
        score_buckets[bucket].append(signal)
    score_summary = [
        {"group": key, **_summary(rows, holding_days)}
        for key, rows in sorted(score_buckets.items(), key=lambda item: item[0])
    ]
    stage_summary = _group_summary(signals, "entry_stage", holding_days)
    status_summary = _group_summary(signals, "status", holding_days)
    return {
        "trade_date_from": trade_date_from,
        "trade_date_to": trade_date_to,
        "scope": scope,
        "stock_count": len(codes),
        "date_count": len(dates),
        "holding_days": holding_days,
        "params": {**params, "entry_stages": entry_stages},
        "performance": {"quote_preload": preload, "market_proxy_preload": market_preload},
        **summary,
        "stage_summary": stage_summary,
        "status_summary": status_summary,
        "score_summary": score_summary,
        "quality_notes": _backtest_quality_notes(summary, len(dates), holding_days),
        "recommendations": _backtest_recommendations(
            stage_summary=stage_summary,
            status_summary=status_summary,
            score_summary=score_summary,
            holding_days=holding_days,
        ),
        "signals": signals[:500],
    }


def run_main_wave_backtest_task(task_id: str, payload: dict[str, Any]) -> None:
    task = task_registry.get(task_id)
    db = SessionLocal()
    try:
        if task:
            task.progress = 0.02
            task.message = "主升浪规则回测准备中"
        result = run_main_wave_backtest(
            db,
            trade_date_from=payload["trade_date_from"],
            trade_date_to=payload["trade_date_to"],
            params=payload,
            max_signals_per_day=int(payload.get("max_signals_per_day") or 20),
            cooldown_days=int(payload.get("cooldown_days") or 5),
            progress_callback=(
                (lambda progress, message: (
                    setattr(task, "progress", min(0.99, float(progress))),
                    setattr(task, "message", message),
                ))
                if task
                else None
            ),
        )
        if task:
            task.result = result
            task.progress = 1.0
            task.message = f"主升浪回测完成：{result.get('total_signals', 0)} 个信号"
    finally:
        db.close()
