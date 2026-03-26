"""
涨停回调策略回测：基于历史涨停股数据模拟买点触发，计算买入后次日涨跌幅。
"""
import types
from datetime import datetime, timedelta
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.stock import DailyQuote
from app.services.limit_up_service import fetch_limit_up_stocks_in_range
from app.services.monitor_engine import _get_df, evaluate_template
from app.services.strategy_service import LIMIT_UP_BUY_POINT_TEMPLATES


def _get_trade_dates_in_range(trade_date_from: str, trade_date_to: str) -> list[str]:
    """获取日期范围内的交易日列表（过滤周末）"""
    if trade_date_from > trade_date_to:
        return []
    current = datetime.strptime(trade_date_from, "%Y%m%d")
    end = datetime.strptime(trade_date_to, "%Y%m%d")
    dates: list[str] = []
    while current <= end:
        s = current.strftime("%Y%m%d")
        if current.weekday() < 5:
            dates.append(s)
        current += timedelta(days=1)
    return dates


def run_single_strategy_backtest(
    db: Session,
    trade_date_from: str,
    trade_date_to: str,
    conditions: list[dict],
    logic: str,
) -> dict:
    """
    单策略回测：按日期范围拉取涨停股，逐日检测买点，计算次日涨跌幅。
    返回 { signals, avg_pct, win_rate, total_signals }
    """
    conditions = conditions[:10]
    logic = logic or "and"

    limit_up_map = fetch_limit_up_stocks_in_range(db, trade_date_from, trade_date_to)
    if not limit_up_map:
        return {
            "signals": [],
            "avg_pct": 0.0,
            "win_rate": 0.0,
            "total_signals": 0,
        }

    trade_dates = _get_trade_dates_in_range(trade_date_from, trade_date_to)
    if len(trade_dates) < 2:
        return {
            "signals": [],
            "avg_pct": 0.0,
            "win_rate": 0.0,
            "total_signals": 0,
        }

    signals: list[dict] = []

    for i, T in enumerate(trade_dates):
        next_idx = i + 1
        if next_idx >= len(trade_dates):
            break
        T_plus_1 = trade_dates[next_idx]

        for ts_code, limit_up_date in limit_up_map.items():
            if limit_up_date > T:
                continue

            df_full = _get_df(db, ts_code)
            if df_full.empty:
                continue
            df = df_full[df_full["trade_date"] <= T].copy()
            if df.empty or df["trade_date"].iloc[-1] != T:
                continue
            if len(df) < 5:
                continue

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
                triggered = all(results)
            else:
                triggered = any(results)
            if not triggered:
                continue

            close_T = df["close"].iloc[-1]
            try:
                ct = float(close_T)
                if ct <= 0 or (ct != ct):
                    continue
            except (TypeError, ValueError):
                continue

            row_next = db.query(DailyQuote).filter(
                DailyQuote.ts_code == ts_code,
                DailyQuote.trade_date == T_plus_1,
            ).first()
            if not row_next or row_next.close is None:
                continue

            close_T1 = float(row_next.close)
            if close_T1 <= 0:
                continue

            next_day_pct = (close_T1 - float(close_T)) / float(close_T)
            signals.append({
                "ts_code": ts_code,
                "trigger_date": T,
                "next_day_pct": round(next_day_pct * 100, 2),
            })

    if not signals:
        return {
            "signals": [],
            "avg_pct": 0.0,
            "win_rate": 0.0,
            "total_signals": 0,
        }

    pcts = [s["next_day_pct"] for s in signals]
    avg_pct = round(sum(pcts) / len(pcts), 2)
    win_count = sum(1 for p in pcts if p > 0)
    win_rate = round(win_count / len(pcts) * 100, 1)

    return {
        "signals": signals,
        "avg_pct": avg_pct,
        "win_rate": win_rate,
        "total_signals": len(signals),
    }
