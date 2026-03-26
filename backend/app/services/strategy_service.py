"""策略选股服务：指标组合选股、涨停回调买点选股"""
import types
from datetime import datetime, timedelta
import time
import pandas as pd
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.stock import StockBasic, DailyQuote
from app.models.pool import WatchPool, WatchStock
from app.services.indicator import calc_ma, calc_macd, calc_rsi, calc_vol_ma, calc_n_day_high
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
        _sync_stock_basic_full(db)

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
                sync_stock_info(db, ts_code)
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
