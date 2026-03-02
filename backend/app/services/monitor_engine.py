from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models.stock import DailyQuote
from app.models.pool import WatchPool, WatchStock
from app.models.monitor import MonitorRule, Alert
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


def evaluate_template(df: pd.DataFrame, template_id: str, params: dict) -> bool:
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
            if not base_price:
                return False
            return df["close"].iloc[-1] < base_price * ratio

    except Exception:
        return False
    return False


def evaluate_rule(df: pd.DataFrame, rule: MonitorRule) -> bool:
    if rule.template_id and rule.template_id in TEMPLATE_INFO:
        return evaluate_template(df, rule.template_id, rule.params or {})

    conditions = rule.params or {}
    if isinstance(conditions, dict) and "conditions" in conditions:
        results = []
        for cond in conditions["conditions"]:
            tid = cond.get("template_id")
            p = cond.get("params", {})
            if tid:
                results.append(evaluate_template(df, tid, p))
        logic = rule.logic or "and"
        if logic == "and":
            return all(results) if results else False
        else:
            return any(results) if results else False
    return False


def scan_stock(db: Session, watch_stock: WatchStock) -> list[Alert]:
    df = _get_df(db, watch_stock.ts_code)
    if df.empty:
        return []

    rules = db.query(MonitorRule).filter(
        MonitorRule.stock_id == watch_stock.id, MonitorRule.is_active == True
    ).all()
    if not rules:
        rules = db.query(MonitorRule).filter(
            MonitorRule.pool_id == watch_stock.pool_id, MonitorRule.is_active == True
        ).all()

    alerts = []
    for rule in rules:
        if evaluate_rule(df, rule):
            last_date = df["trade_date"].iloc[-1]
            existing = db.query(Alert).filter(
                Alert.stock_id == watch_stock.id,
                Alert.rule_id == rule.id,
                Alert.trigger_date == last_date,
            ).first()
            if not existing:
                snapshot = {
                    "close": df["close"].iloc[-1],
                    "open": df["open"].iloc[-1],
                    "high": df["high"].iloc[-1],
                    "low": df["low"].iloc[-1],
                    "vol": df["vol"].iloc[-1],
                }
                alert = Alert(
                    stock_id=watch_stock.id,
                    rule_id=rule.id,
                    ts_code=watch_stock.ts_code,
                    trigger_date=last_date,
                    snapshot=snapshot,
                )
                db.add(alert)
                alerts.append(alert)
    if alerts:
        watch_stock.monitor_status = "triggered"
    db.commit()
    return alerts


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
