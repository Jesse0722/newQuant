from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models.stock import DailyQuote
from app.models.pool import WatchPool, WatchStock
from app.models.monitor import MonitorRule
from app.services.indicator import calc_ma, calc_macd, calc_rsi, calc_vol_ma, calc_n_day_high
from app.tasks.background import task_registry
import pandas as pd

TEMPLATE_INFO = {
    "ma_support": {"name": "均线支撑", "description": "收盘价回踩 MA(N) 附近（±2%）", "default_params": {"n": 20}},
    "macd_golden": {"name": "MACD 金叉", "description": "DIF 上穿 DEA", "default_params": {}},
    "rsi_oversold": {"name": "RSI 超卖", "description": "RSI 低于阈值", "default_params": {"period": 14, "threshold": 30}},
    "volume_shrink": {"name": "缩量回调", "description": "价格下跌且成交量萎缩", "default_params": {"ratio": 0.7}},
    "breakout_high": {"name": "突破新高", "description": "收盘价创 N 日新高", "default_params": {"n": 60}},
    "price_threshold": {"name": "价格阈值", "description": "跌破基准价 × 比例", "default_params": {"base_price": 0, "ratio": 0.95}},
    "limit_up_price_support": {"name": "涨停板价支撑", "description": "收盘价回踩涨停板价附近（±tolerance）", "default_params": {"tolerance": 0.03}},
    "days_since_limit_up": {"name": "涨停后时间窗口", "description": "涨停后 N~M 个交易日内", "default_params": {"min_days": 3, "max_days": 15}},
    "fibonacci_retrace": {"name": "黄金分割回调", "description": "涨停后最高点回调至 0.382/0.5 附近", "default_params": {"level": 0.382, "tolerance": 0.03}},
}


def _get_df(db: Session, ts_code: str, limit: int = 250) -> pd.DataFrame:
    rows = db.query(DailyQuote).filter(
        DailyQuote.ts_code == ts_code
    ).order_by(DailyQuote.trade_date.asc()).limit(limit).all()
    if not rows:
        return pd.DataFrame()
    data = [{"trade_date": r.trade_date, "open": r.open, "high": r.high, "low": r.low,
             "close": r.close, "pre_close": r.pre_close, "vol": r.vol, "amount": r.amount} for r in rows]
    return pd.DataFrame(data)


def _get_limit_up_price(df: pd.DataFrame, limit_up_date: str | None) -> float | None:
    """从 K 线中取涨停日收盘价（涨停价）"""
    if not limit_up_date:
        return None
    row = df[df["trade_date"] == limit_up_date]
    if row.empty:
        return None
    close = row["close"].iloc[0]
    return float(close) if close is not None and not pd.isna(close) else None


def _get_days_since_limit_up(df: pd.DataFrame, limit_up_date: str | None) -> int | None:
    """涨停日到最新交易日之间的交易日数量（不含涨停日）"""
    if not limit_up_date:
        return None
    after = df[df["trade_date"] > limit_up_date]
    return len(after) if not after.empty else None


def evaluate_template(
    df: pd.DataFrame,
    template_id: str,
    params: dict,
    watch_stock: WatchStock | None = None,
) -> bool:
    if len(df) < 5:
        return False
    try:
        if template_id == "ma_support":
            n = params.get("n", 20)
            ma = calc_ma(df, n)
            if ma.iloc[-1] is None or pd.isna(ma.iloc[-1]):
                return False
            close = df["close"].iloc[-1]
            return ma.iloc[-1] * 0.98 <= close <= ma.iloc[-1] * 1.02

        elif template_id == "macd_golden":
            dif, dea, _ = calc_macd(df)
            if len(dif) < 2 or pd.isna(dif.iloc[-1]) or pd.isna(dif.iloc[-2]):
                return False
            return dif.iloc[-2] < dea.iloc[-2] and dif.iloc[-1] >= dea.iloc[-1]

        elif template_id == "rsi_oversold":
            period = params.get("period", 14)
            threshold = params.get("threshold", 30)
            rsi = calc_rsi(df, period)
            if pd.isna(rsi.iloc[-1]):
                return False
            return rsi.iloc[-1] < threshold

        elif template_id == "volume_shrink":
            ratio = params.get("ratio", 0.7)
            vol_ma = calc_vol_ma(df, 5)
            if pd.isna(vol_ma.iloc[-1]):
                return False
            return (df["close"].iloc[-1] < df["close"].iloc[-2]
                    and df["vol"].iloc[-1] < vol_ma.iloc[-1] * ratio)

        elif template_id == "breakout_high":
            n = params.get("n", 60)
            n_high = calc_n_day_high(df, n)
            if pd.isna(n_high.iloc[-2]):
                return False
            return df["close"].iloc[-1] >= n_high.iloc[-2]

        elif template_id == "price_threshold":
            base_price = params.get("base_price", 0)
            ratio = params.get("ratio", 0.95)
            if not base_price and watch_stock and watch_stock.limit_up_date:
                base_price = _get_limit_up_price(df, watch_stock.limit_up_date)
            if not base_price:
                return False
            return df["close"].iloc[-1] < base_price * ratio

        elif template_id == "limit_up_price_support":
            if not watch_stock or not watch_stock.limit_up_date:
                return False
            limit_price = _get_limit_up_price(df, watch_stock.limit_up_date)
            if not limit_price:
                return False
            tolerance = params.get("tolerance", 0.03)
            close = df["close"].iloc[-1]
            return limit_price * (1 - tolerance) <= close <= limit_price * (1 + tolerance)

        elif template_id == "days_since_limit_up":
            if not watch_stock or not watch_stock.limit_up_date:
                return False
            days = _get_days_since_limit_up(df, watch_stock.limit_up_date)
            if days is None:
                return False
            min_days = params.get("min_days", 3)
            max_days = params.get("max_days", 15)
            return min_days <= days <= max_days

        elif template_id == "fibonacci_retrace":
            if not watch_stock or not watch_stock.limit_up_date:
                return False
            after = df[df["trade_date"] > watch_stock.limit_up_date]
            if after.empty:
                return False
            high_max = after["high"].max()
            if pd.isna(high_max) or high_max <= 0:
                return False
            close = df["close"].iloc[-1]
            retrace = (high_max - close) / high_max
            level = params.get("level", 0.382)
            tolerance = params.get("tolerance", 0.03)
            target = level
            return abs(retrace - target) <= tolerance

    except Exception:
        return False
    return False


def evaluate_rule(df: pd.DataFrame, rule: MonitorRule, watch_stock: WatchStock | None = None) -> bool:
    if rule.template_id and rule.template_id in TEMPLATE_INFO:
        return evaluate_template(df, rule.template_id, rule.params or {}, watch_stock)

    conditions = rule.params or {}
    if isinstance(conditions, dict) and "conditions" in conditions:
        results = []
        for cond in conditions["conditions"]:
            tid = cond.get("template_id")
            p = cond.get("params", {})
            if tid:
                results.append(evaluate_template(df, tid, p, watch_stock))
        logic = rule.logic or "and"
        if logic == "and":
            return all(results) if results else False
        else:
            return any(results) if results else False
    return False


def scan_stock(db: Session, watch_stock: WatchStock) -> None:
    df = _get_df(db, watch_stock.ts_code)
    if df.empty:
        return

    rules = db.query(MonitorRule).filter(
        MonitorRule.stock_id == watch_stock.id, MonitorRule.is_active == True
    ).all()
    if not rules:
        rules = db.query(MonitorRule).filter(
            MonitorRule.pool_id == watch_stock.pool_id, MonitorRule.is_active == True
        ).all()

    rule_matched = any(evaluate_rule(df, rule, watch_stock) for rule in rules)
    if rule_matched:
        watch_stock.monitor_status = "triggered"
        pool = db.query(WatchPool).filter(WatchPool.id == watch_stock.pool_id).first()
        if pool and pool.trigger_target_pool_id:
            existing = db.query(WatchStock).filter(
                WatchStock.pool_id == pool.trigger_target_pool_id,
                WatchStock.ts_code == watch_stock.ts_code,
            ).first()
            if not existing:
                target_stock = WatchStock(
                    pool_id=pool.trigger_target_pool_id,
                    ts_code=watch_stock.ts_code,
                    source="limit_up_trigger",
                )
                db.add(target_stock)
    db.commit()


def scan_pool(task_id: str, pool_id: str):
    db = SessionLocal()
    try:
        stocks = db.query(WatchStock).filter(
            WatchStock.pool_id == pool_id,
            WatchStock.monitor_status == "monitoring",
        ).all()
        total = len(stocks)
        for i, ws in enumerate(stocks):
            scan_stock(db, ws)
            task_registry[task_id].progress = (i + 1) / total if total else 1.0
            task_registry[task_id].message = f"已扫描 {i+1}/{total}"
    finally:
        db.close()


def scan_all(task_id: str):
    db = SessionLocal()
    try:
        pools = db.query(WatchPool).all()
        all_stocks = []
        for p in pools:
            stocks = db.query(WatchStock).filter(
                WatchStock.pool_id == p.id,
                WatchStock.monitor_status == "monitoring",
            ).all()
            all_stocks.extend(stocks)
        total = len(all_stocks)
        for i, ws in enumerate(all_stocks):
            scan_stock(db, ws)
            task_registry[task_id].progress = (i + 1) / total if total else 1.0
            task_registry[task_id].message = f"已扫描 {i+1}/{total}"
    finally:
        db.close()
