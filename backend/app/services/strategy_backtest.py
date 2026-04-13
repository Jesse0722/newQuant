"""
新买点策略回测：针对 7 个买点策略做历史逐日回测。
"""
from __future__ import annotations

from collections.abc import Callable
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.pool import WatchPool, WatchStock
from app.models.stock import StockBasic, DailyQuote
from app.services.buy_signal_service import (
    DEFAULT_PARAMS,
    _calc_indicators,
    _validate_life_line,
    _analyze_stock,
)
from app.services.limit_up_service import (
    LIMIT_UP_POOL_NAME,
    _get_limit_up_threshold,
    fetch_limit_up_stocks_from_db,
    fetch_limit_up_stocks_in_range,
)
from app.services.limit_up_tactics import TACTIC_REGISTRY, common_pre_filter
from app.tasks.background import task_registry


def _get_pool_id(db: Session, pool_id: str | None) -> str | None:
    if pool_id:
        return pool_id
    pool = db.query(WatchPool).filter(WatchPool.name == LIMIT_UP_POOL_NAME).first()
    return pool.id if pool else None


def _find_limit_up_idx(
    df: "pd.DataFrame",
    latest_idx: int,
    threshold: float,
    max_days: int,
) -> int | None:
    start = max(0, latest_idx - max_days)
    for i in range(latest_idx - 1, start - 1, -1):
        row = df.iloc[i]
        pct = row.get("pct_chg")
        if pct is None:
            continue
        try:
            pct_val = float(pct)
        except (TypeError, ValueError):
            continue
        if pct_val >= threshold:
            return i
    return None


def _calc_forward_return(
    df: "pd.DataFrame",
    latest_idx: int,
    days: int,
) -> float | None:
    target_idx = latest_idx + days
    if target_idx >= len(df):
        return None
    entry = float(df.iloc[latest_idx]["close"])
    exit_price = float(df.iloc[target_idx]["close"])
    if entry <= 0:
        return None
    return round((exit_price - entry) / entry * 100, 2)


def _build_backtest_df(db: Session, ts_code: str) -> "pd.DataFrame":
    rows = (
        db.query(DailyQuote)
        .filter(DailyQuote.ts_code == ts_code)
        .order_by(DailyQuote.trade_date.asc())
        .all()
    )
    if not rows:
        import pandas as pd
        return pd.DataFrame()
    import pandas as pd
    return pd.DataFrame(
        [
            {
                "trade_date": r.trade_date,
                "open": r.open,
                "high": r.high,
                "low": r.low,
                "close": r.close,
                "pre_close": r.pre_close,
                "pct_chg": r.pct_chg,
                "vol": r.vol,
                "amount": r.amount,
                "turnover_rate": r.turnover_rate,
            }
            for r in rows
        ]
    )


def run_strategy_backtest(
    db: Session,
    strategy_id: str,
    trade_date_from: str,
    trade_date_to: str,
    pool_id: str | None = None,
    progress_cb: Callable[[float, str], None] | None = None,
    *,
    codes: list[str] | None = None,
    use_limit_up_universe: bool = False,
    universe_from_local_db: bool = True,
) -> dict:
    if strategy_id not in {"two_phase", *TACTIC_REGISTRY.keys()}:
        raise ValueError(f"不支持的策略: {strategy_id}")
    if trade_date_from > trade_date_to:
        raise ValueError("开始日期不能大于结束日期")

    if use_limit_up_universe:
        if universe_from_local_db:
            uni = fetch_limit_up_stocks_from_db(db, trade_date_from, trade_date_to)
        else:
            uni = fetch_limit_up_stocks_in_range(db, trade_date_from, trade_date_to)
        codes = list(uni.keys())
    elif codes is None:
        resolved_pool_id = _get_pool_id(db, pool_id)
        if not resolved_pool_id:
            return {
                "strategy_id": strategy_id,
                "trade_date_from": trade_date_from,
                "trade_date_to": trade_date_to,
                "total_signals": 0,
                "win_rate_1d": 0.0,
                "win_rate_3d": 0.0,
                "win_rate_5d": 0.0,
                "avg_return_1d": 0.0,
                "avg_return_3d": 0.0,
                "avg_return_5d": 0.0,
                "max_drawdown": 0.0,
                "profit_factor": 0.0,
                "signals": [],
            }

        stocks = db.query(WatchStock).filter(WatchStock.pool_id == resolved_pool_id).all()
        if not stocks:
            return {
                "strategy_id": strategy_id,
                "trade_date_from": trade_date_from,
                "trade_date_to": trade_date_to,
                "total_signals": 0,
                "win_rate_1d": 0.0,
                "win_rate_3d": 0.0,
                "win_rate_5d": 0.0,
                "avg_return_1d": 0.0,
                "avg_return_3d": 0.0,
                "avg_return_5d": 0.0,
                "max_drawdown": 0.0,
                "profit_factor": 0.0,
                "signals": [],
            }

        codes = [s.ts_code for s in stocks]
    else:
        codes = list(codes)

    if not codes:
        return {
            "strategy_id": strategy_id,
            "trade_date_from": trade_date_from,
            "trade_date_to": trade_date_to,
            "total_signals": 0,
            "win_rate_1d": 0.0,
            "win_rate_3d": 0.0,
            "win_rate_5d": 0.0,
            "avg_return_1d": 0.0,
            "avg_return_3d": 0.0,
            "avg_return_5d": 0.0,
            "max_drawdown": 0.0,
            "profit_factor": 0.0,
            "signals": [],
        }
    basics = (
        db.query(StockBasic.ts_code, StockBasic.market, StockBasic.name)
        .filter(StockBasic.ts_code.in_(codes))
        .all()
    )
    basic_map: dict[str, tuple[str | None, str | None]] = {
        row[0]: (row[1], row[2]) for row in basics
    }

    signals: list[dict] = []
    ret_1d_vals: list[float] = []
    ret_3d_vals: list[float] = []
    ret_5d_vals: list[float] = []
    total = len(codes)

    for idx_s, ts_code in enumerate(codes):
        if progress_cb:
            progress_cb(idx_s / max(total, 1), f"回测中 {idx_s + 1}/{total}: {ts_code}")
        df = _build_backtest_df(db, ts_code)
        if df.empty or len(df) < 30:
            continue
        df = _calc_indicators(df)

        market = (basic_map.get(ts_code) or (None, None))[0]
        threshold = _get_limit_up_threshold(market)
        tactic = TACTIC_REGISTRY.get(strategy_id)
        max_days = tactic.get("max_days", 20) if tactic else DEFAULT_PARAMS["phase2_max_days"]
        analyze_fn = tactic["analyze_fn"] if tactic else None

        for i in range(1, len(df) - 5):
            trade_date = str(df.iloc[i]["trade_date"])
            if trade_date < trade_date_from or trade_date > trade_date_to:
                continue

            snap = df.iloc[: i + 1].copy()
            latest_idx = len(snap) - 1
            if str(snap.iloc[-1]["trade_date"]) != trade_date:
                continue

            limit_up_idx = _find_limit_up_idx(snap, latest_idx, threshold, max_days)
            if limit_up_idx is None:
                continue

            if strategy_id == "two_phase":
                life_date = str(snap.iloc[limit_up_idx]["trade_date"])
                life_info = _validate_life_line(snap, life_date, ts_code)
                if not life_info:
                    continue
                analysis = _analyze_stock(snap, life_info, DEFAULT_PARAMS.copy())
            else:
                ok, _ = common_pre_filter(snap, limit_up_idx, max_days=max_days)
                if not ok:
                    continue
                analysis = analyze_fn(snap, limit_up_idx)  # type: ignore[misc]

            if analysis.get("signal_status") != "triggered":
                continue

            ret_1d = _calc_forward_return(df, i, 1)
            ret_3d = _calc_forward_return(df, i, 3)
            ret_5d = _calc_forward_return(df, i, 5)

            if ret_1d is not None:
                ret_1d_vals.append(ret_1d)
            if ret_3d is not None:
                ret_3d_vals.append(ret_3d)
            if ret_5d is not None:
                ret_5d_vals.append(ret_5d)

            name = (basic_map.get(ts_code) or (None, ts_code))[1] or ts_code
            signals.append({
                "ts_code": ts_code,
                "name": name,
                "trigger_date": trade_date,
                "entry_price": round(float(df.iloc[i]["close"]), 2),
                "return_1d": ret_1d,
                "return_3d": ret_3d,
                "return_5d": ret_5d,
                "signal_score": int(analysis.get("signal_score", 0) or 0),
            })

    def _avg(vals: list[float]) -> float:
        return round(sum(vals) / len(vals), 2) if vals else 0.0

    def _win(vals: list[float]) -> float:
        return round(sum(1 for v in vals if v > 0) / len(vals) * 100, 1) if vals else 0.0

    max_drawdown = round(min(ret_5d_vals), 2) if ret_5d_vals else 0.0
    pos_sum = sum(v for v in ret_1d_vals if v > 0)
    neg_sum = sum(v for v in ret_1d_vals if v < 0)
    profit_factor = round(pos_sum / abs(neg_sum), 2) if neg_sum < 0 else 0.0

    signals.sort(key=lambda x: (x["trigger_date"], x["ts_code"]))

    if progress_cb:
        progress_cb(1.0, "回测完成")

    return {
        "strategy_id": strategy_id,
        "trade_date_from": trade_date_from,
        "trade_date_to": trade_date_to,
        "total_signals": len(signals),
        "win_rate_1d": _win(ret_1d_vals),
        "win_rate_3d": _win(ret_3d_vals),
        "win_rate_5d": _win(ret_5d_vals),
        "avg_return_1d": _avg(ret_1d_vals),
        "avg_return_3d": _avg(ret_3d_vals),
        "avg_return_5d": _avg(ret_5d_vals),
        "max_drawdown": max_drawdown,
        "profit_factor": profit_factor,
        "signals": signals,
    }


def run_strategy_backtest_task(
    task_id: str,
    strategy_id: str,
    trade_date_from: str,
    trade_date_to: str,
    pool_id: str | None = None,
):
    db = SessionLocal()
    try:
        def _progress(p: float, msg: str):
            if task_id in task_registry:
                task_registry[task_id].progress = max(0.0, min(1.0, p))
                task_registry[task_id].message = msg

        result = run_strategy_backtest(
            db,
            strategy_id=strategy_id,
            trade_date_from=trade_date_from,
            trade_date_to=trade_date_to,
            pool_id=pool_id,
            progress_cb=_progress,
        )
        if task_id in task_registry:
            task_registry[task_id].result = result
    finally:
        db.close()
