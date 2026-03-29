"""
买点识别服务

策略注册表：
- two_phase: 二阶段买点识别（冲高回落企稳反转，统一加权评分）
- next_day_shrink / ma5_pullback / three_yin / half_volume / ma_golden_cross / rubbing_line: 涨停回调六大战法
"""
import numpy as np
import pandas as pd
from datetime import datetime
from sqlalchemy.orm import Session

from app.models.stock import StockBasic, DailyQuote
from app.models.pool import WatchPool, WatchStock
from app.services.limit_up_service import LIMIT_UP_POOL_NAME, _get_limit_up_threshold
from app.services.indicator import calc_ma, calc_macd, calc_rsi, calc_vol_ma
from app.services.limit_up_tactics import (
    TACTIC_REGISTRY,
    common_pre_filter,
    _build_signal,
    _calc_persist_days,
)

# ---------- 策略参数 ----------

DEFAULT_PARAMS = {
    "life_line_volume_ratio": 1.5,
    "life_line_volume_ratio_with_turnover": 1.2,
    "life_line_min_volume": 10000,
    "phase2_max_days": 60,
    "buy_min_days_since_life": 5,
}

# 二阶段策略条件定义（统一加权评分）
TWO_PHASE_CONDS = {
    "yang_candle":        {"label": "收阳线",              "weight": 1.0, "core": True},
    "volume_ratio":       {"label": "量能温和放量",         "weight": 1.0, "core": True},
    "pct_change":         {"label": "当日涨幅≥1%",         "weight": 0.5, "core": False},
    "macd_golden":        {"label": "MACD金叉/柱转正",     "weight": 1.0, "core": True},
    "above_ma5":          {"label": "站上MA5",             "weight": 1.0, "core": True},
    "above_ma10":         {"label": "站上MA10",            "weight": 0.5, "core": False},
    "rsi_range":          {"label": "RSI在45~70",          "weight": 0.5, "core": False},
    "not_break_low":      {"label": "未破生命线低价",       "weight": 1.5, "core": True},
    "pullback_stabilize": {"label": "冲高回落企稳",         "weight": 1.5, "core": True},
    "volume_trend":       {"label": "成交量趋势向好",       "weight": 0.5, "core": False},
    "turnover_range":     {"label": "换手率适中(2~12%)",    "weight": 0.5, "core": False},
}


# ---------- 技术指标计算 ----------

def _build_df(db: Session, ts_code: str, limit: int = 250) -> pd.DataFrame:
    rows = (
        db.query(DailyQuote)
        .filter(DailyQuote.ts_code == ts_code)
        .order_by(DailyQuote.trade_date.asc())
        .limit(limit)
        .all()
    )
    if not rows:
        return pd.DataFrame()
    data = [
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
    return pd.DataFrame(data)


def _calc_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """在 df 上计算所有需要的技术指标列"""
    df = df.copy()
    df["ma5"] = calc_ma(df, 5)
    df["ma10"] = calc_ma(df, 10)
    df["ma20"] = calc_ma(df, 20)

    dif, dea, hist = calc_macd(df)
    df["macd_dif"] = dif
    df["macd_dea"] = dea
    df["macd_hist"] = hist

    df["rsi14"] = calc_rsi(df, 14)

    vol_ma5 = calc_vol_ma(df, 5)
    df["vol_ma5"] = vol_ma5
    df["volume_ratio"] = df["vol"] / vol_ma5.replace(0, np.nan)
    df["volume_ratio"] = df["volume_ratio"].fillna(1.0)

    if "pct_chg" not in df.columns or df["pct_chg"].isna().all():
        df["pct_chg"] = df["close"].pct_change() * 100

    return df


# ---------- 阶段一：验证生命线 ----------

def _validate_life_line(df: pd.DataFrame, limit_up_date: str, ts_code: str) -> dict | None:
    """
    验证涨停日是否为合格的"生命线"。
    返回生命线信息 dict 或 None（不合格）。
    """
    mask = df["trade_date"] == limit_up_date
    if not mask.any():
        return None
    idx = df.index[mask][0]
    row = df.loc[idx]

    if row["high"] == row["low"]:
        return None

    # 量比计算
    if idx >= 5:
        avg_vol = df.loc[idx - 5 : idx - 1, "vol"].mean()
        vol_ratio = row["vol"] / avg_vol if avg_vol > 0 else 1.0
    else:
        vol_ratio = row.get("volume_ratio", 1.0)

    # 量比阈值：有换手率时可降低至1.2，否则1.5
    tr = row.get("turnover_rate")
    has_valid_tr = tr is not None and not pd.isna(tr) and tr >= 3.0
    min_vol_ratio = (
        DEFAULT_PARAMS["life_line_volume_ratio_with_turnover"]
        if has_valid_tr else
        DEFAULT_PARAMS["life_line_volume_ratio"]
    )
    if vol_ratio < min_vol_ratio:
        return None

    if row["vol"] < DEFAULT_PARAMS["life_line_min_volume"]:
        return None

    # 价格位置：兼容短数据
    lookback = min(idx, 60)
    if lookback >= 10:
        window = df.loc[idx - lookback : idx - 1, "close"]
        pmin, pmax = window.min(), window.max()
        if pmax != pmin:
            position = (row["close"] - pmin) / (pmax - pmin)
            if position >= 0.7:
                return None

    return {
        "date": limit_up_date,
        "close": float(row["close"]),
        "low": float(row["low"]),
        "high": float(row["high"]),
        "vol": float(row["vol"]),
        "volume_ratio": float(vol_ratio),
        "pct_chg": float(row["pct_chg"]) if not pd.isna(row["pct_chg"]) else 0.0,
        "df_idx": int(idx),
    }


# ---------- 阶段二：跟踪与买点检测 ----------

def _check_conditions(df: pd.DataFrame, idx: int, life_info: dict, params: dict) -> dict[str, bool]:
    """逐项检查买点条件，返回 {条件名: True/False}"""
    row = df.iloc[idx]
    results: dict[str, bool] = {}
    life_idx = life_info["df_idx"]
    life_low = life_info["low"]
    life_close = life_info["close"]

    results["yang_candle"] = row["close"] > row["open"]

    vr = row.get("volume_ratio", 0)
    results["volume_ratio"] = not pd.isna(vr) and 1.2 <= vr <= 3.0

    pct = row.get("pct_chg", 0)
    results["pct_change"] = not pd.isna(pct) and pct >= 1.0

    # MACD 金叉或柱状图转正（3天内）
    macd_ok = False
    for lookback in range(min(3, idx)):
        ci = idx - lookback
        if ci < 1:
            break
        cur = df.iloc[ci]
        prev = df.iloc[ci - 1]
        if (
            not pd.isna(cur.get("macd_dif"))
            and not pd.isna(cur.get("macd_dea"))
            and not pd.isna(prev.get("macd_dif"))
            and not pd.isna(prev.get("macd_dea"))
        ):
            if cur["macd_dif"] > cur["macd_dea"] and prev["macd_dif"] <= prev["macd_dea"]:
                macd_ok = True
                break
    if not macd_ok and idx > 0:
        cur_hist = row.get("macd_hist", 0)
        prev_hist = df.iloc[idx - 1].get("macd_hist", 0)
        if not pd.isna(cur_hist) and not pd.isna(prev_hist) and cur_hist > 0 and prev_hist <= 0:
            macd_ok = True
    results["macd_golden"] = macd_ok

    ma5 = row.get("ma5", 0)
    results["above_ma5"] = not pd.isna(ma5) and row["close"] >= ma5

    ma10 = row.get("ma10", 0)
    results["above_ma10"] = not pd.isna(ma10) and row["close"] >= ma10

    rsi = row.get("rsi14", 50)
    results["rsi_range"] = not pd.isna(rsi) and 45 <= rsi <= 70

    results["not_break_low"] = row["low"] >= life_low * 0.995

    # 冲高回落企稳：明确三阶段
    pullback_ok = False
    days_since = idx - life_idx
    if days_since > params["buy_min_days_since_life"]:
        post_window = df.iloc[life_idx + 1 : idx + 1]
        if len(post_window) > 0:
            max_close = post_window["close"].max()
            has_rally = max_close > life_close * 1.03
            has_dip = row["close"] < max_close * 0.97
            if has_rally and has_dip:
                # 企稳：近3日最低价逐日抬升 或 近5日标准差<均价2%
                if idx >= 3:
                    lows_3 = [df.iloc[idx - 2]["low"], df.iloc[idx - 1]["low"], row["low"]]
                    rising_lows = lows_3[1] >= lows_3[0] and lows_3[2] >= lows_3[1]
                    if rising_lows:
                        pullback_ok = True
                if not pullback_ok and idx >= 5:
                    recent = df.iloc[idx - 4 : idx + 1]["close"]
                    if recent.mean() > 0 and recent.std() / recent.mean() < 0.02:
                        pullback_ok = True
    results["pullback_stabilize"] = pullback_ok

    vol_trend_ok = True
    if idx >= 3:
        vols = [df.iloc[idx - i]["vol"] for i in range(min(4, idx + 1))]
        if len(vols) >= 2:
            vol_trend_ok = vols[0] >= vols[1] * 0.7 or vols[0] >= np.mean(vols[1:]) * 0.9
    results["volume_trend"] = vol_trend_ok

    tr = row.get("turnover_rate")
    if tr is not None and not pd.isna(tr):
        results["turnover_range"] = 2.0 <= tr <= 12.0
    else:
        results["turnover_range"] = False

    return results


def _analyze_stock(df: pd.DataFrame, life_info: dict, params: dict) -> dict:
    """
    对一只股票进行阶段二分析，使用统一加权评分。
    """
    life_idx = life_info["df_idx"]
    life_low = life_info["low"]
    life_close = life_info["close"]
    max_days = params["phase2_max_days"]

    last_idx = len(df) - 1
    if last_idx <= life_idx:
        return {
            "signal_status": "invalidated", "signal_score": 0,
            "days_since_life_line": 0, "phase2_high": None, "pullback_pct": None,
            "latest_close": None, "latest_pct_chg": None,
            "rsi": None, "macd_hist": None, "volume_ratio": None,
            "signal_persist_days": 0,
            "stop_loss_price": None, "target_price": None,
            "stop_loss_pct": None, "target_return_pct": None, "risk_reward_ratio": None,
            "met_conditions": [], "unmet_conditions": ["无生命线后数据"],
        }

    days_since = last_idx - life_idx

    if days_since > max_days:
        return {
            "signal_status": "invalidated", "signal_score": 0,
            "days_since_life_line": days_since, "phase2_high": None, "pullback_pct": None,
            "latest_close": float(df.iloc[last_idx]["close"]),
            "latest_pct_chg": float(df.iloc[last_idx]["pct_chg"]) if not pd.isna(df.iloc[last_idx].get("pct_chg")) else 0.0,
            "rsi": None, "macd_hist": None, "volume_ratio": None,
            "signal_persist_days": 0,
            "stop_loss_price": None, "target_price": None,
            "stop_loss_pct": None, "target_return_pct": None, "risk_reward_ratio": None,
            "met_conditions": [], "unmet_conditions": [f"超过{max_days}天跟踪窗口"],
        }

    latest = df.iloc[last_idx]
    if latest["low"] < life_low * 0.98:
        return {
            "signal_status": "invalidated", "signal_score": 0,
            "days_since_life_line": days_since, "phase2_high": None, "pullback_pct": None,
            "latest_close": float(latest["close"]),
            "latest_pct_chg": float(latest["pct_chg"]) if not pd.isna(latest.get("pct_chg")) else 0.0,
            "rsi": None, "macd_hist": None, "volume_ratio": None,
            "signal_persist_days": 0,
            "stop_loss_price": None, "target_price": None,
            "stop_loss_pct": None, "target_return_pct": None, "risk_reward_ratio": None,
            "met_conditions": [], "unmet_conditions": ["跌破生命线最低价"],
        }

    post_window = df.iloc[life_idx + 1 : last_idx + 1]
    phase2_high = float(post_window["close"].max()) if len(post_window) > 0 else life_close
    pullback_pct = round((phase2_high - latest["close"]) / phase2_high * 100, 2) if phase2_high > 0 else 0

    conditions = _check_conditions(df, last_idx, life_info, params)

    # 用统一加权评分构建信号
    rsi = latest.get("rsi14", 50)
    vr = latest.get("volume_ratio", 1.0)
    latest_close = float(latest["close"])
    stop_loss_price = round(float(life_low) * 0.97, 2)
    target_price = round(float(life_close) * 1.10, 2)
    if latest_close > 0:
        stop_loss_pct = round((latest_close - stop_loss_price) / latest_close * 100, 2)
        target_return_pct = round((target_price - latest_close) / latest_close * 100, 2)
    else:
        stop_loss_pct = None
        target_return_pct = None
    risk_reward_ratio = (
        round(target_return_pct / stop_loss_pct, 2)
        if stop_loss_pct is not None and stop_loss_pct > 0 and target_return_pct is not None
        else None
    )
    metrics = {
        "days_since_life_line": days_since,
        "phase2_high": phase2_high,
        "pullback_pct": pullback_pct,
        "latest_close": latest_close,
        "latest_pct_chg": float(latest["pct_chg"]) if not pd.isna(latest.get("pct_chg")) else 0.0,
        "rsi": round(float(rsi), 1) if not pd.isna(rsi) else None,
        "macd_hist": round(float(latest.get("macd_hist", 0)), 4) if not pd.isna(latest.get("macd_hist")) else None,
        "volume_ratio": round(float(vr), 2) if not pd.isna(vr) else None,
        "signal_persist_days": 1,
        "stop_loss_price": stop_loss_price,
        "target_price": target_price,
        "stop_loss_pct": stop_loss_pct,
        "target_return_pct": target_return_pct,
        "risk_reward_ratio": risk_reward_ratio,
    }

    return _build_signal(conditions, TWO_PHASE_CONDS, metrics)


def _calc_two_phase_persist_days(
    df: pd.DataFrame,
    life_info: dict,
    params: dict,
    current_status: str,
    max_lookback: int = 2,
) -> int:
    """计算二阶段信号连续满足天数（含今日）。"""
    if current_status not in ("triggered", "approaching"):
        return 0
    persist_days = 1
    life_idx = life_info["df_idx"]
    total_len = len(df)
    for i in range(1, max_lookback + 1):
        cut_len = total_len - i
        if cut_len <= life_idx + 1:
            break
        prev_df = df.iloc[:cut_len].copy()
        prev_sig = _analyze_stock(prev_df, life_info, params)
        if prev_sig.get("signal_status") in ("triggered", "approaching"):
            persist_days += 1
        else:
            break
    return persist_days


# ---------- 信号标注（K线图用） ----------

def get_signal_marks(db: Session, ts_code: str, limit_up_date: str | None = None) -> list[dict]:
    if not limit_up_date:
        pool = db.query(WatchPool).filter(WatchPool.name == LIMIT_UP_POOL_NAME).first()
        if pool:
            ws = (
                db.query(WatchStock)
                .filter(WatchStock.pool_id == pool.id, WatchStock.ts_code == ts_code)
                .first()
            )
            if ws:
                limit_up_date = ws.limit_up_date

    if not limit_up_date:
        return []

    df = _build_df(db, ts_code)
    if df.empty or len(df) < 10:
        return []
    df = _calc_indicators(df)

    life_info = _validate_life_line(df, limit_up_date, ts_code)
    marks: list[dict] = []

    if not life_info:
        marks.append({"date": limit_up_date, "type": "life_line", "label": "涨停日", "value": None})
        return marks

    marks.append({
        "date": limit_up_date,
        "type": "life_line",
        "label": "生命线",
        "value": life_info["low"],
    })

    life_idx = life_info["df_idx"]
    last_idx = len(df) - 1
    if last_idx > life_idx:
        post = df.iloc[life_idx + 1 : last_idx + 1]
        if len(post) > 0:
            high_idx = post["close"].idxmax()
            marks.append({
                "date": df.loc[high_idx, "trade_date"],
                "type": "phase2_high",
                "label": "阶段高点",
                "value": float(post["close"].max()),
            })

    analysis = _analyze_stock(df, life_info, DEFAULT_PARAMS)
    if analysis["signal_status"] == "triggered":
        marks.append({
            "date": df.iloc[last_idx]["trade_date"],
            "type": "buy_signal",
            "label": "买点",
            "value": float(df.iloc[last_idx]["close"]),
        })

    return marks


def _scan_stub_invalidated(
    db: Session,
    ts_code: str,
    basic_cache: dict[str, StockBasic | None],
    reason: str,
    *,
    limit_up_date: str | None = None,
    latest_close: float | None = None,
    latest_pct_chg: float | None = None,
) -> dict:
    return {
        "ts_code": ts_code,
        "name": _get_stock_name(db, ts_code, basic_cache),
        "industry": _get_stock_industry(db, ts_code, basic_cache),
        "signal_status": "invalidated",
        "signal_score": 0,
        "life_line_date": limit_up_date,
        "life_line_price": None,
        "days_since_life_line": None,
        "latest_close": latest_close,
        "latest_pct_chg": latest_pct_chg,
        "phase2_high": None,
        "pullback_pct": None,
        "met_conditions": [],
        "unmet_conditions": [reason],
        "rsi": None,
        "macd_hist": None,
        "volume_ratio": None,
        "signal_persist_days": 0,
        "stop_loss_price": None,
        "target_price": None,
        "stop_loss_pct": None,
        "target_return_pct": None,
        "risk_reward_ratio": None,
    }


# ---------- 策略注册表 ----------

STRATEGY_REGISTRY: dict[str, dict] = {
    "two_phase": {
        "name": "二阶段买点识别",
        "description": "涨停后冲高回落企稳反转，统一加权评分",
    },
    **{
        k: {"name": v["name"], "description": v["description"]}
        for k, v in TACTIC_REGISTRY.items()
    },
}


def list_buy_strategies() -> list[dict]:
    return [{"id": k, "name": v["name"], "description": v["description"]} for k, v in STRATEGY_REGISTRY.items()]


# ---------- 主入口：扫描池内所有股票 ----------

def scan_pool_buy_signals(db: Session, pool_id: str | None = None, strategy_id: str = "two_phase") -> dict:
    if strategy_id in TACTIC_REGISTRY:
        return _scan_tactic(db, pool_id, strategy_id)
    return _scan_two_phase(db, pool_id)


def _scan_two_phase(db: Session, pool_id: str | None) -> dict:
    if not pool_id:
        pool = db.query(WatchPool).filter(WatchPool.name == LIMIT_UP_POOL_NAME).first()
        if not pool:
            return _empty_result("two_phase")
        pool_id = pool.id

    stocks = db.query(WatchStock).filter(WatchStock.pool_id == pool_id).all()
    basic_cache: dict[str, StockBasic | None] = {}
    signals: list[dict] = []
    params = DEFAULT_PARAMS.copy()

    for ws in stocks:
        ts_code = ws.ts_code
        if not ws.limit_up_date:
            signals.append(
                _scan_stub_invalidated(
                    db, ts_code, basic_cache,
                    "无涨停日记录，无法套用二阶段买点策略",
                )
            )
            continue

        df = _build_df(db, ts_code)
        if df.empty or len(df) < 10:
            signals.append(
                _scan_stub_invalidated(
                    db, ts_code, basic_cache,
                    "本地 K 线数据不足（请先同步日线）",
                    limit_up_date=ws.limit_up_date,
                )
            )
            continue

        df = _calc_indicators(df)
        life_info = _validate_life_line(df, ws.limit_up_date, ts_code)

        if not life_info:
            all_labels = [d["label"] for d in TWO_PHASE_CONDS.values()]
            signals.append({
                "ts_code": ts_code,
                "name": _get_stock_name(db, ts_code, basic_cache),
                "industry": _get_stock_industry(db, ts_code, basic_cache),
                "signal_status": "invalidated",
                "signal_score": 0,
                "life_line_date": ws.limit_up_date,
                "life_line_price": None,
                "days_since_life_line": None,
                "latest_close": float(df.iloc[-1]["close"]) if len(df) > 0 else None,
                "latest_pct_chg": float(df.iloc[-1]["pct_chg"]) if len(df) > 0 and not pd.isna(df.iloc[-1].get("pct_chg")) else None,
                "phase2_high": None,
                "pullback_pct": None,
                "met_conditions": [],
                "unmet_conditions": all_labels,
                "rsi": None,
                "macd_hist": None,
                "volume_ratio": None,
                "signal_persist_days": 0,
                "stop_loss_price": None,
                "target_price": None,
                "stop_loss_pct": None,
                "target_return_pct": None,
                "risk_reward_ratio": None,
            })
            continue

        analysis = _analyze_stock(df, life_info, params)
        analysis["signal_persist_days"] = _calc_two_phase_persist_days(
            df, life_info, params, analysis.get("signal_status", "")
        )
        signals.append({
            "ts_code": ts_code,
            "name": _get_stock_name(db, ts_code, basic_cache),
            "industry": _get_stock_industry(db, ts_code, basic_cache),
            "life_line_date": ws.limit_up_date,
            "life_line_price": life_info["close"],
            **analysis,
        })

    return _finalize(signals, "two_phase")


def _scan_tactic(db: Session, pool_id: str | None, strategy_id: str) -> dict:
    """六大战法通用扫描器"""
    tactic = TACTIC_REGISTRY[strategy_id]
    analyze_fn = tactic["analyze_fn"]
    tactic_max_days = tactic.get("max_days", 20)

    if not pool_id:
        pool = db.query(WatchPool).filter(WatchPool.name == LIMIT_UP_POOL_NAME).first()
        if not pool:
            return _empty_result(strategy_id)
        pool_id = pool.id

    stocks = db.query(WatchStock).filter(WatchStock.pool_id == pool_id).all()
    basic_cache: dict[str, StockBasic | None] = {}
    signals: list[dict] = []

    for ws in stocks:
        ts_code = ws.ts_code
        if not ws.limit_up_date:
            signals.append(
                _scan_stub_invalidated(db, ts_code, basic_cache, "无涨停日记录")
            )
            continue

        df = _build_df(db, ts_code)
        if df.empty or len(df) < 10:
            signals.append(
                _scan_stub_invalidated(
                    db, ts_code, basic_cache,
                    "K线数据不足（请先同步日线）",
                    limit_up_date=ws.limit_up_date,
                )
            )
            continue

        df = _calc_indicators(df)

        mask = df["trade_date"] == ws.limit_up_date
        if not mask.any():
            signals.append(
                _scan_stub_invalidated(
                    db, ts_code, basic_cache,
                    "K线中找不到涨停日数据",
                    limit_up_date=ws.limit_up_date,
                )
            )
            continue

        limit_up_idx = int(df.index[mask][0])

        ok, reason = common_pre_filter(df, limit_up_idx, max_days=tactic_max_days)
        if not ok:
            signals.append({
                "ts_code": ts_code,
                "name": _get_stock_name(db, ts_code, basic_cache),
                "industry": _get_stock_industry(db, ts_code, basic_cache),
                "signal_status": "invalidated",
                "signal_score": 0,
                "life_line_date": ws.limit_up_date,
                "life_line_price": float(df.iloc[limit_up_idx]["close"]),
                "days_since_life_line": len(df) - 1 - limit_up_idx,
                "latest_close": float(df.iloc[-1]["close"]),
                "latest_pct_chg": float(df.iloc[-1]["pct_chg"]) if not pd.isna(df.iloc[-1].get("pct_chg")) else 0.0,
                "phase2_high": None,
                "pullback_pct": None,
                "met_conditions": [],
                "unmet_conditions": [reason],
                "rsi": None,
                "macd_hist": None,
                "volume_ratio": None,
                "signal_persist_days": 0,
                "stop_loss_price": None,
                "target_price": None,
                "stop_loss_pct": None,
                "target_return_pct": None,
                "risk_reward_ratio": None,
            })
            continue

        analysis = analyze_fn(df, limit_up_idx)
        analysis["signal_persist_days"] = _calc_persist_days(
            df, limit_up_idx, analyze_fn, analysis.get("signal_status", "")
        )
        signals.append({
            "ts_code": ts_code,
            "name": _get_stock_name(db, ts_code, basic_cache),
            "industry": _get_stock_industry(db, ts_code, basic_cache),
            "life_line_date": ws.limit_up_date,
            "life_line_price": float(df.iloc[limit_up_idx]["close"]),
            **analysis,
        })

    return _finalize(signals, strategy_id)


def _empty_result(strategy_id: str) -> dict:
    name = STRATEGY_REGISTRY.get(strategy_id, {}).get("name", strategy_id)
    return {
        "signals": [],
        "scan_time": datetime.now().isoformat(),
        "total": 0,
        "triggered_count": 0,
        "approaching_count": 0,
        "strategy_id": strategy_id,
        "strategy_name": name,
    }


def _finalize(signals: list[dict], strategy_id: str) -> dict:
    status_order = {"triggered": 0, "approaching": 1, "tracking": 2, "invalidated": 3}
    signals.sort(
        key=lambda s: (
            status_order.get(s["signal_status"], 9),
            -int(s.get("signal_persist_days", 0) or 0),
            -s.get("signal_score", 0),
        )
    )
    name = STRATEGY_REGISTRY.get(strategy_id, {}).get("name", strategy_id)
    return {
        "signals": signals,
        "scan_time": datetime.now().isoformat(),
        "total": len(signals),
        "triggered_count": sum(1 for s in signals if s["signal_status"] == "triggered"),
        "approaching_count": sum(1 for s in signals if s["signal_status"] == "approaching"),
        "strategy_id": strategy_id,
        "strategy_name": name,
    }


# ---------- 辅助 ----------

def _get_stock_name(db: Session, ts_code: str, cache: dict) -> str:
    if ts_code not in cache:
        cache[ts_code] = db.query(StockBasic).filter(StockBasic.ts_code == ts_code).first()
    b = cache[ts_code]
    return b.name if b else ts_code


def _get_stock_industry(db: Session, ts_code: str, cache: dict) -> str | None:
    if ts_code not in cache:
        cache[ts_code] = db.query(StockBasic).filter(StockBasic.ts_code == ts_code).first()
    b = cache[ts_code]
    return b.industry if b else None
