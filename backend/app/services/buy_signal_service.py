"""
买点识别服务

策略注册表：
- two_phase: 二阶段买点识别（冲高回落企稳反转，统一加权评分）
- next_day_shrink / ma5_pullback / three_yin / half_volume / ma_golden_cross / rubbing_line / ma5_hold_pullback: 涨停回调七大战法
"""

from __future__ import annotations
import numpy as np
import pandas as pd
import time
from datetime import datetime
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.monitor import Alert
from app.models.stock import StockBasic, DailyQuote
from app.models.pool import WatchPool, WatchStock
from app.services.limit_up_service import LIMIT_UP_POOL_NAME
from app.services.indicator import calc_ma, calc_macd, calc_rsi, calc_vol_ma
from app.services.limit_up_tactics import (
    TACTIC_REGISTRY,
    common_pre_filter,
    _build_signal,
    _calc_persist_days,
)
from app.services.trading_session import is_a_share_trading_session, shanghai_trade_date_str
from app.services.tushare_adapter import tushare_adapter

RT_K_CHUNK = 5000

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
    # 需要最近窗口用于买点扫描；先按倒序取 limit 条，再在内存中恢复为正序。
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

INTRADAY_PROVISIONAL = "provisional_triggered"
INTRADAY_CONFIRMED = "confirmed_triggered"


def list_buy_strategies() -> list[dict]:
    return [{"id": k, "name": v["name"], "description": v["description"]} for k, v in STRATEGY_REGISTRY.items()]


# ---------- 实时日 K（rt_k）与流通股本换手 ----------

_RT_CACHE_TTL = 60
_rt_k_cache: dict[str, tuple[float, dict]] = {}

def _fetch_rt_k_map(ts_codes: list[str]) -> dict[str, dict]:
    if not ts_codes:
        return {}
        
    now = time.time()
    out: dict[str, dict] = {}
    missing_codes: list[str] = []
    
    for code in ts_codes:
        if code in _rt_k_cache:
            ts, data = _rt_k_cache[code]
            if now - ts < _RT_CACHE_TTL:
                out[code] = data
                continue
        missing_codes.append(code)
        
    if not missing_codes:
        return out

    for i in range(0, len(missing_codes), RT_K_CHUNK):
        chunk = missing_codes[i : i + RT_K_CHUNK]
        df = tushare_adapter.get_rt_k(ts_code=",".join(chunk))
        if df is None or df.empty:
            continue
        for _, row in df.iterrows():
            code = row.get("ts_code")
            if code is not None:
                data = row.to_dict()
                sc = str(code)
                out[sc] = data
                _rt_k_cache[sc] = (now, data)
                
    # Optional: cleanup entirely stale cache elements to prevent memory leak over long periods
    stale_keys = [k for k, (t, _) in _rt_k_cache.items() if now - t > _RT_CACHE_TTL * 2]
    for k in stale_keys:
        _rt_k_cache.pop(k, None)
        
    return out


def resolve_float_share(db: Session, ts_code: str, ref_trade_date: str) -> float | None:
    row = (
        db.query(DailyQuote.float_share)
        .filter(
            DailyQuote.ts_code == ts_code,
            DailyQuote.trade_date <= ref_trade_date,
            DailyQuote.float_share.isnot(None),
        )
        .order_by(DailyQuote.trade_date.desc())
        .first()
    )
    if row and row[0] is not None:
        v = float(row[0])
        if v > 0:
            return v
    br = db.query(StockBasic.float_share).filter(StockBasic.ts_code == ts_code).first()
    if br and br[0] is not None:
        v = float(br[0])
        if v > 0:
            return v
    return None


def _merge_rt_k_into_df(df: pd.DataFrame, rt: dict, trade_date_today: str) -> pd.DataFrame:
    """rt_k 的 vol 为股、daily 库内为手；amount 为元 vs 千元。"""
    if df.empty:
        return df
    df = df.copy()
    vol_raw = rt.get("vol")
    if vol_raw is None or (isinstance(vol_raw, float) and vol_raw != vol_raw):
        return df
    vol_hands = float(vol_raw) / 100.0
    amt = rt.get("amount")
    amount_k = float(amt) / 1000.0 if amt is not None and not (isinstance(amt, float) and amt != amt) else None
    pre_close = rt.get("pre_close")
    close = rt.get("close")
    pc = float(pre_close) if pre_close is not None and not (isinstance(pre_close, float) and pre_close != pre_close) else None
    cl = float(close) if close is not None and not (isinstance(close, float) and close != close) else None
    if cl is None:
        return df
    pct_chg = None
    if pc is not None and pc > 0:
        pct_chg = (cl / pc - 1.0) * 100.0
    def _f(k):
        x = rt.get(k)
        if x is None or (isinstance(x, float) and x != x):
            return None
        return float(x)
    new_row = {
        "trade_date": trade_date_today,
        "open": _f("open"),
        "high": _f("high"),
        "low": _f("low"),
        "close": cl,
        "pre_close": pc,
        "pct_chg": pct_chg,
        "vol": vol_hands,
        "amount": amount_k,
        "turnover_rate": None,
    }
    last_td = str(df.iloc[-1]["trade_date"])
    if last_td == trade_date_today:
        idx = len(df) - 1
        for col, val in new_row.items():
            if val is not None and col in df.columns:
                df.iat[idx, df.columns.get_loc(col)] = val
    else:
        df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
    return df


def _apply_intraday_turnover_if_needed(
    db: Session, df: pd.DataFrame, ts_code: str, trade_date_today: str
) -> pd.DataFrame:
    if df.empty:
        return df
    last_idx = len(df) - 1
    if str(df.iloc[last_idx]["trade_date"]) != trade_date_today:
        return df
    tr = df.iloc[last_idx].get("turnover_rate")
    if tr is not None and not pd.isna(tr):
        return df
    fs = resolve_float_share(db, ts_code, trade_date_today)
    if fs is None or fs <= 0:
        return df
    vol = df.iloc[last_idx].get("vol")
    if vol is None or pd.isna(vol) or float(vol) <= 0:
        return df
    vol = float(vol)
    pct = (vol * 100.0) / (fs * 10000.0) * 100.0
    df = df.copy()
    df.iat[last_idx, df.columns.get_loc("turnover_rate")] = round(pct, 4)
    return df


def _prepare_scan_dataframe(
    db: Session,
    ts_code: str,
    rt_map: dict[str, dict],
    trade_date_today: str,
    merge_rt: bool,
) -> pd.DataFrame:
    df = _build_df(db, ts_code)
    if df.empty or len(df) < 10:
        return df
    if merge_rt:
        rt = rt_map.get(ts_code)
        if rt is not None:
            df = _merge_rt_k_into_df(df, rt, trade_date_today)
    df = _apply_intraday_turnover_if_needed(db, df, ts_code, trade_date_today)
    return _calc_indicators(df)


def _inject_intraday_life_line_if_missing(
    df: pd.DataFrame,
    ts_code: str,
    limit_up_date: str | None,
    rt_map: dict[str, dict],
    trade_date_today: str,
) -> tuple[pd.DataFrame, bool]:
    """
    当日涨停票若本地 daily_quote 尚未落当天K线，使用 rt_k 临时补一根日K，
    避免扫描阶段因为“找不到涨停日”而漏扫。
    """
    if df.empty or not limit_up_date or limit_up_date != trade_date_today:
        return df, False
    if "trade_date" not in df.columns:
        return df, False
    if str(limit_up_date) in set(df["trade_date"].astype(str)):
        return df, False
    rt = rt_map.get(ts_code)
    if not rt:
        return df, False

    def _f(k: str):
        v = rt.get(k)
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return None
        try:
            return float(v)
        except Exception:
            return None

    o = _f("open")
    h = _f("high")
    l = _f("low")
    c = _f("close")
    pc = _f("pre_close")
    if None in (o, h, l, c) or min(o, h, l, c) <= 0:
        return df, False
    if h < l or h < o or h < c or l > o or l > c:
        return df, False

    vol_raw = _f("vol")
    amount_raw = _f("amount")
    vol_hands = vol_raw / 100.0 if vol_raw is not None else None
    amount_k = amount_raw / 1000.0 if amount_raw is not None else None
    pct = _f("pct_chg")
    if pct is None and pc is not None and pc > 0:
        pct = (c / pc - 1.0) * 100.0

    new_row = {
        "trade_date": trade_date_today,
        "open": o,
        "high": h,
        "low": l,
        "close": c,
        "pre_close": pc,
        "pct_chg": pct,
        "vol": vol_hands,
        "amount": amount_k,
        "turnover_rate": _f("turnover_rate"),
    }
    out = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
    out = out.drop_duplicates(subset=["trade_date"], keep="last").sort_values("trade_date").reset_index(drop=True)
    return _calc_indicators(out), True


def _align_signal_latest_display_with_daily_db(
    db: Session, signals: list[dict], merge_rt: bool
) -> None:
    """
    盘中合并 rt_k 时，列表上的 latest_close / latest_pct_chg 与 K 线图（仅 daily_quote，不合并 rt）对齐；
    信号判定仍基于上方 _prepare_scan_dataframe 中的合并数据，避免展示与图表口径不一致。
    """
    if not merge_rt:
        return
    cache: dict[str, pd.DataFrame] = {}
    for s in signals:
        code = s.get("ts_code")
        if not code:
            continue
        if code not in cache:
            cache[code] = _build_df(db, code)
        df0 = cache[code]
        if df0.empty:
            continue
        last = df0.iloc[-1]
        lc = last.get("close")
        pc = last.get("pct_chg")
        if lc is not None and not pd.isna(lc):
            s["latest_close"] = float(lc)
        if pc is not None and not pd.isna(pc):
            s["latest_pct_chg"] = float(pc)


def _resolve_pool_id(db: Session, pool_id: str | None) -> str | None:
    if pool_id:
        return pool_id
    pool = db.query(WatchPool).filter(WatchPool.name == LIMIT_UP_POOL_NAME).first()
    return pool.id if pool else None


def _scan_context(db: Session, pool_id: str | None):
    trade_date_today = shanghai_trade_date_str()
    pid = _resolve_pool_id(db, pool_id)
    if not pid:
        return None, [], {}, {"requested": False, "applied": False, "error": None}, trade_date_today, False
    stocks = db.query(WatchStock).filter(WatchStock.pool_id == pid).all()
    in_session = is_a_share_trading_session()
    # 非交易时段若池内存在“当日涨停”票，仍尝试拉一次 rt_k，补齐当日临时K线避免漏扫。
    need_today_fallback = any((ws.limit_up_date == trade_date_today) for ws in stocks)
    should_fetch_rt = in_session or need_today_fallback
    realtime = {"requested": should_fetch_rt, "applied": False, "error": None}
    rt_map: dict[str, dict] = {}
    if should_fetch_rt and stocks:
        try:
            rt_map = _fetch_rt_k_map([ws.ts_code for ws in stocks])
            realtime["applied"] = len(rt_map) > 0
        except Exception as e:
            realtime["error"] = str(e)[:500]
            rt_map = {}
            realtime["applied"] = False
    merge_rt = bool(realtime["applied"])
    return pid, stocks, rt_map, realtime, trade_date_today, merge_rt


def _json_safe_for_alert(obj):
    if isinstance(obj, dict):
        return {k: _json_safe_for_alert(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_safe_for_alert(v) for v in obj]
    if isinstance(obj, (np.floating, np.integer)):
        return float(obj) if isinstance(obj, np.floating) else int(obj)
    if hasattr(obj, "item") and callable(getattr(obj, "item", None)):
        try:
            return obj.item()
        except Exception:
            pass
    return obj


def _batch_last_trade_dates(db: Session, ts_codes: list[str], fallback: str) -> dict[str, str]:
    if not ts_codes:
        return {}
    rows = (
        db.query(DailyQuote.ts_code, func.max(DailyQuote.trade_date).label("md"))
        .filter(DailyQuote.ts_code.in_(ts_codes))
        .group_by(DailyQuote.ts_code)
        .all()
    )
    out = {r.ts_code: (str(r.md) if r.md is not None else fallback) for r in rows}
    for c in ts_codes:
        if c not in out:
            out[c] = fallback
    return out


def _sync_buy_radar_alerts(
    db: Session,
    pool_id: str,
    stocks: list,
    rt_map: dict[str, dict],
    merge_rt: bool,
    trade_date_today: str,
    strategy_id: str,
    signals: list[dict],
    scan_meta_base: dict,
) -> None:
    triggered = [
        s for s in signals
        if s.get("signal_status") in ("triggered", INTRADAY_CONFIRMED)
    ]
    if not triggered:
        return

    ts_to_ws = {ws.ts_code: ws for ws in stocks}
    ts_codes = [s["ts_code"] for s in triggered]
    last_dates = _batch_last_trade_dates(db, ts_codes, trade_date_today)
    strat_name = STRATEGY_REGISTRY.get(strategy_id, {}).get("name", strategy_id)
    scan_meta = {**scan_meta_base, "pool_id": pool_id}

    for sig in triggered:
        ts_code = sig["ts_code"]
        if merge_rt and ts_code in rt_map:
            trig_date = trade_date_today
        else:
            trig_date = last_dates.get(ts_code, trade_date_today)

        watch = ts_to_ws.get(ts_code)
        if not watch:
            watch = (
                db.query(WatchStock)
                .filter(WatchStock.pool_id == pool_id, WatchStock.ts_code == ts_code)
                .first()
            )
        if not watch:
            continue

        signal_payload = _json_safe_for_alert({**sig, "strategy_id": strategy_id, "strategy_name": strat_name})
        snapshot = {"_v": 1, "signal": signal_payload, "scan_meta": _json_safe_for_alert(scan_meta)}

        existing = (
            db.query(Alert)
            .filter(
                Alert.stock_id == watch.id,
                Alert.source == "buy_radar",
                Alert.buy_strategy_id == strategy_id,
                Alert.trigger_date == trig_date,
            )
            .first()
        )
        if existing:
            existing.snapshot = snapshot
            existing.ts_code = ts_code
        else:
            db.add(
                Alert(
                    stock_id=watch.id,
                    rule_id=None,
                    ts_code=ts_code,
                    trigger_date=trig_date,
                    status="pending",
                    snapshot=snapshot,
                    source="buy_radar",
                    buy_strategy_id=strategy_id,
                )
            )
    db.commit()


def _scan_meta_fields(realtime: dict, trade_date_today: str) -> dict:
    applied = bool(realtime.get("applied"))
    mode = "intraday_merged" if applied else "historical_only"
    return {
        "scan_data_mode": mode,
        "as_of": datetime.now().isoformat(),
        "intraday_provisional": applied,
        "realtime": realtime,
        "trade_date_today": trade_date_today,
    }


_intraday_hit_cache: dict[str, tuple[int, float]] = {}
_INTRADAY_HIT_TTL_SECONDS = 3600


def _apply_intraday_reliability_state(
    signals: list[dict],
    strategy_id: str,
    pool_id: str | None,
    trade_date_today: str,
    merge_rt: bool,
    min_confirm_hits: int,
) -> tuple[int, int]:
    """
    低误报优先：
    - 盘中触发先标记 provisional_triggered，连续命中达到阈值才确证 confirmed_triggered
    - 非盘中（历史口径）触发直接确证
    """
    now = time.time()
    provisional = 0
    confirmed = 0
    safe_min_hits = max(1, int(min_confirm_hits or 1))

    # 清理过期缓存，防止内存无限增长
    expired = [k for k, (_, ts) in _intraday_hit_cache.items() if now - ts > _INTRADAY_HIT_TTL_SECONDS]
    for k in expired:
        _intraday_hit_cache.pop(k, None)

    for s in signals:
        status = s.get("signal_status")
        if status != "triggered":
            continue
        code = s.get("ts_code") or ""
        key = f"{pool_id or ''}|{strategy_id}|{code}|{trade_date_today}"
        if merge_rt:
            prev_hits, _ = _intraday_hit_cache.get(key, (0, now))
            hits = prev_hits + 1
            _intraday_hit_cache[key] = (hits, now)
            if hits >= safe_min_hits:
                s["signal_status"] = INTRADAY_CONFIRMED
                confirmed += 1
            else:
                s["signal_status"] = INTRADAY_PROVISIONAL
                provisional += 1
        else:
            s["signal_status"] = INTRADAY_CONFIRMED
            confirmed += 1
    return provisional, confirmed

# ---------- 主入口：扫描池内所有股票 ----------

def scan_pool_buy_signals(
    db: Session,
    pool_id: str | None = None,
    strategy_id: str = "two_phase",
    *,
    min_confirm_hits: int = 2,
    limit_up_date_from: str | None = None,
    limit_up_date_to: str | None = None,
) -> dict:
    pid, stocks, rt_map, realtime, trade_date_today, merge_rt = _scan_context(db, pool_id)
    if not pid:
        meta = _scan_meta_fields(realtime, trade_date_today)
        return {**_empty_result(strategy_id), **meta}
    if limit_up_date_from:
        stocks = [s for s in stocks if s.limit_up_date and s.limit_up_date >= limit_up_date_from]
    if limit_up_date_to:
        stocks = [s for s in stocks if s.limit_up_date and s.limit_up_date <= limit_up_date_to]
    if not stocks:
        meta = _scan_meta_fields(realtime, trade_date_today)
        return {**_empty_result(strategy_id), **meta}
    if strategy_id in TACTIC_REGISTRY:
        return _scan_tactic(
            db, pid, strategy_id, stocks, rt_map, trade_date_today, merge_rt, realtime, min_confirm_hits=min_confirm_hits
        )
    return _scan_two_phase(
        db, pid, stocks, rt_map, trade_date_today, merge_rt, realtime, min_confirm_hits=min_confirm_hits
    )


def _scan_two_phase(
    db: Session,
    pool_id: str,
    stocks: list,
    rt_map: dict[str, dict],
    trade_date_today: str,
    merge_rt: bool,
    realtime: dict,
    min_confirm_hits: int = 2,
) -> dict:
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

        df = _prepare_scan_dataframe(db, ts_code, rt_map, trade_date_today, merge_rt)
        df, _ = _inject_intraday_life_line_if_missing(
            df, ts_code, ws.limit_up_date, rt_map, trade_date_today
        )
        if df.empty or len(df) < 10:
            signals.append(
                _scan_stub_invalidated(
                    db, ts_code, basic_cache,
                    "本地 K 线数据不足（请先同步日线）",
                    limit_up_date=ws.limit_up_date,
                )
            )
            continue
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

    _align_signal_latest_display_with_daily_db(db, signals, merge_rt)
    meta = _scan_meta_fields(realtime, trade_date_today)
    provisional_cnt, confirmed_cnt = _apply_intraday_reliability_state(
        signals, "two_phase", pool_id, trade_date_today, merge_rt, min_confirm_hits
    )
    meta["provisional_count"] = provisional_cnt
    meta["confirmed_count"] = confirmed_cnt
    meta["min_confirm_hits"] = max(1, int(min_confirm_hits or 1))
    out = _finalize(signals, "two_phase", **meta)
    _sync_buy_radar_alerts(
        db, pool_id, stocks, rt_map, merge_rt, trade_date_today, "two_phase", signals, meta
    )
    return out


def _scan_tactic(
    db: Session,
    pool_id: str,
    strategy_id: str,
    stocks: list,
    rt_map: dict[str, dict],
    trade_date_today: str,
    merge_rt: bool,
    realtime: dict,
    min_confirm_hits: int = 2,
) -> dict:
    """六大战法通用扫描器"""
    tactic = TACTIC_REGISTRY[strategy_id]
    analyze_fn = tactic["analyze_fn"]
    tactic_max_days = tactic.get("max_days", 20)

    basic_cache: dict[str, StockBasic | None] = {}
    signals: list[dict] = []

    for ws in stocks:
        ts_code = ws.ts_code
        if not ws.limit_up_date:
            signals.append(
                _scan_stub_invalidated(db, ts_code, basic_cache, "无涨停日记录")
            )
            continue

        df = _prepare_scan_dataframe(db, ts_code, rt_map, trade_date_today, merge_rt)
        df, _ = _inject_intraday_life_line_if_missing(
            df, ts_code, ws.limit_up_date, rt_map, trade_date_today
        )
        if df.empty or len(df) < 10:
            signals.append(
                _scan_stub_invalidated(
                    db, ts_code, basic_cache,
                    "K线数据不足（请先同步日线）",
                    limit_up_date=ws.limit_up_date,
                )
            )
            continue

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

    _align_signal_latest_display_with_daily_db(db, signals, merge_rt)
    meta = _scan_meta_fields(realtime, trade_date_today)
    provisional_cnt, confirmed_cnt = _apply_intraday_reliability_state(
        signals, strategy_id, pool_id, trade_date_today, merge_rt, min_confirm_hits
    )
    meta["provisional_count"] = provisional_cnt
    meta["confirmed_count"] = confirmed_cnt
    meta["min_confirm_hits"] = max(1, int(min_confirm_hits or 1))
    out = _finalize(signals, strategy_id, **meta)
    _sync_buy_radar_alerts(
        db, pool_id, stocks, rt_map, merge_rt, trade_date_today, strategy_id, signals, meta
    )
    return out


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


def _finalize(signals: list[dict], strategy_id: str, **meta) -> dict:
    status_order = {
        INTRADAY_CONFIRMED: 0,
        "triggered": 0,
        INTRADAY_PROVISIONAL: 1,
        "approaching": 2,
        "tracking": 3,
        "invalidated": 4,
    }
    signals.sort(
        key=lambda s: (
            status_order.get(s["signal_status"], 9),
            -int(s.get("signal_persist_days", 0) or 0),
            -s.get("signal_score", 0),
        )
    )
    name = STRATEGY_REGISTRY.get(strategy_id, {}).get("name", strategy_id)
    out = {
        "signals": signals,
        "scan_time": datetime.now().isoformat(),
        "total": len(signals),
        "triggered_count": sum(
            1
            for s in signals
            if s["signal_status"] in ("triggered", INTRADAY_CONFIRMED)
        ),
        "approaching_count": sum(1 for s in signals if s["signal_status"] == "approaching"),
        "strategy_id": strategy_id,
        "strategy_name": name,
    }
    out.update(meta)
    return out


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
