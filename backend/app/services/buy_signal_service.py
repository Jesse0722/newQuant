"""
二阶段买点识别服务：移植自 TwoPhaseTradingStrategy

阶段一：验证生命线质量（涨停日是否为放量涨停、非一字板、非高位）
阶段二：跟踪生命线后走势，识别"冲高回落企稳反转"买点
"""
import numpy as np
import pandas as pd
from datetime import datetime
from sqlalchemy.orm import Session

from app.models.stock import StockBasic, DailyQuote
from app.models.pool import WatchPool, WatchStock
from app.services.limit_up_service import LIMIT_UP_POOL_NAME, _get_limit_up_threshold
from app.services.indicator import calc_ma, calc_macd, calc_rsi, calc_vol_ma

# ---------- 策略参数 ----------

DEFAULT_PARAMS = {
    "life_line_volume_ratio": 2.0,
    "life_line_min_volume": 10000,
    "phase2_max_days": 60,
    "phase2_rally_min_pct": 5,
    "phase2_dip_min_pct": 3,
    "buy_volume_ratio_min": 1.2,
    "buy_volume_ratio_max": 3.0,
    "buy_price_increase_pct": 3.0,
    "buy_rsi_min": 50,
    "buy_rsi_max": 70,
    "buy_min_days_since_life": 5,
}

# 买点条件名称（用于前端展示已满足/未满足）
CONDITION_LABELS = {
    "volume_ratio": "量能温和放量",
    "pct_change": "当日涨幅≥3%",
    "macd_golden": "MACD金叉/柱转正",
    "above_ma5": "站上MA5",
    "above_ma10": "站上MA10",
    "rsi_range": "RSI在50~70",
    "not_break_low": "未破生命线低价",
    "pullback_stabilize": "冲高回落企稳",
    "volume_trend": "成交量趋势向好",
}

TOTAL_CONDITIONS = len(CONDITION_LABELS)


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

    # 非一字板
    if row["high"] == row["low"]:
        return None

    # 量比 >= 2（相对前5日均量）
    if idx >= 5:
        avg_vol = df.loc[idx - 5 : idx - 1, "vol"].mean()
        if avg_vol > 0:
            vol_ratio = row["vol"] / avg_vol
        else:
            vol_ratio = 1.0
    else:
        vol_ratio = row.get("volume_ratio", 1.0)

    if vol_ratio < DEFAULT_PARAMS["life_line_volume_ratio"]:
        return None

    # 最小成交量
    if row["vol"] < DEFAULT_PARAMS["life_line_min_volume"]:
        return None

    # 价格位置：不在60日高位70%以上
    if idx >= 60:
        window = df.loc[idx - 60 : idx - 1, "close"]
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

    # 1. 量能温和放量
    vr = row.get("volume_ratio", 0)
    results["volume_ratio"] = (
        not pd.isna(vr)
        and params["buy_volume_ratio_min"] <= vr <= params["buy_volume_ratio_max"]
    )

    # 2. 当日涨幅
    pct = row.get("pct_chg", 0)
    results["pct_change"] = not pd.isna(pct) and pct >= params["buy_price_increase_pct"]

    # 3. MACD 金叉或柱状图转正（3天内）
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

    # 4 & 5. 站上 MA5 / MA10
    ma5 = row.get("ma5", 0)
    results["above_ma5"] = not pd.isna(ma5) and row["close"] >= ma5

    ma10 = row.get("ma10", 0)
    results["above_ma10"] = not pd.isna(ma10) and row["close"] >= ma10

    # 6. RSI 区间
    rsi = row.get("rsi14", 50)
    results["rsi_range"] = not pd.isna(rsi) and params["buy_rsi_min"] <= rsi <= params["buy_rsi_max"]

    # 7. 未破生命线最低价
    results["not_break_low"] = row["low"] >= life_low * 0.995

    # 8. 冲高回落企稳
    pullback_ok = False
    days_since = idx - life_idx
    if days_since > params["buy_min_days_since_life"]:
        post_window = df.iloc[life_idx + 1 : idx + 1]
        if len(post_window) > 0:
            max_close = post_window["close"].max()
            # 需要从高点回落
            if row["close"] < max_close * 0.97:
                # 检查企稳：近5日价格稳定且当前高于近期低点
                if idx >= 5:
                    recent = df.iloc[idx - 4 : idx + 1]["close"]
                    recent_low = recent.min()
                    if row["close"] >= recent_low * 1.01:
                        pullback_ok = True
            elif days_since > 10:
                # 长时间横盘也算企稳
                if idx >= 5:
                    recent = df.iloc[idx - 4 : idx + 1]["close"]
                    recent_low = recent.min()
                    if row["close"] >= recent_low * 1.01:
                        pullback_ok = True
    results["pullback_stabilize"] = pullback_ok

    # 9. 成交量趋势
    vol_trend_ok = True
    if idx >= 3:
        vols = [df.iloc[idx - i]["vol"] for i in range(min(4, idx + 1))]
        if len(vols) >= 2:
            vol_trend_ok = vols[0] >= vols[1] * 0.7 or vols[0] >= np.mean(vols[1:]) * 0.9
    results["volume_trend"] = vol_trend_ok

    return results


def _analyze_stock(
    df: pd.DataFrame, life_info: dict, params: dict
) -> dict:
    """
    对一只股票进行阶段二分析。
    返回信号字典：status, score, conditions, snapshot 等。
    """
    life_idx = life_info["df_idx"]
    life_low = life_info["low"]
    life_close = life_info["close"]
    max_days = params["phase2_max_days"]

    last_idx = len(df) - 1
    if last_idx <= life_idx:
        return {"signal_status": "invalidated", "reason": "无生命线后数据"}

    days_since = last_idx - life_idx

    # 超时失效
    if days_since > max_days:
        return {"signal_status": "invalidated", "reason": f"超过{max_days}天跟踪窗口"}

    # 破位失效：检查最新价是否跌破生命线最低价
    latest = df.iloc[last_idx]
    if latest["low"] < life_low * 0.98:
        return {"signal_status": "invalidated", "reason": "跌破生命线最低价"}

    # 阶段二高点
    post_window = df.iloc[life_idx + 1 : last_idx + 1]
    phase2_high = float(post_window["close"].max()) if len(post_window) > 0 else life_close
    pullback_pct = round((phase2_high - latest["close"]) / phase2_high * 100, 2) if phase2_high > 0 else 0

    # 检查最新一天的买点条件
    conditions = _check_conditions(df, last_idx, life_info, params)
    met = [k for k, v in conditions.items() if v]
    unmet = [k for k, v in conditions.items() if not v]
    met_count = len(met)

    # 判断状态
    if met_count == TOTAL_CONDITIONS:
        status = "triggered"
    elif met_count >= TOTAL_CONDITIONS - 2:
        status = "approaching"
    else:
        status = "tracking"

    # 评分（0~100）
    base_score = int(met_count / TOTAL_CONDITIONS * 80)
    rsi = latest.get("rsi14", 50)
    rsi_bonus = 10 if (not pd.isna(rsi) and 50 <= rsi <= 65) else 0
    vr = latest.get("volume_ratio", 1.0)
    vr_bonus = 5 if (not pd.isna(vr) and 1.5 <= vr <= 2.5) else 0
    macd_bonus = 5 if (not pd.isna(latest.get("macd_hist", 0)) and latest["macd_hist"] > 0) else 0
    score = min(100, base_score + rsi_bonus + vr_bonus + macd_bonus)

    return {
        "signal_status": status,
        "signal_score": score,
        "days_since_life_line": days_since,
        "phase2_high": phase2_high,
        "pullback_pct": pullback_pct,
        "latest_close": float(latest["close"]),
        "latest_pct_chg": float(latest["pct_chg"]) if not pd.isna(latest.get("pct_chg")) else 0.0,
        "rsi": round(float(rsi), 1) if not pd.isna(rsi) else None,
        "macd_hist": round(float(latest.get("macd_hist", 0)), 4) if not pd.isna(latest.get("macd_hist")) else None,
        "volume_ratio": round(float(vr), 2) if not pd.isna(vr) else None,
        "met_conditions": [CONDITION_LABELS[k] for k in met],
        "unmet_conditions": [CONDITION_LABELS[k] for k in unmet],
    }


# ---------- 信号标注（K线图用） ----------

def get_signal_marks(db: Session, ts_code: str, limit_up_date: str | None = None) -> list[dict]:
    """
    返回 K 线图上需要标注的信号点（生命线、阶段高点、买点）。
    若未传 limit_up_date，尝试从涨停池查询。
    """
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

    # 检查是否有买点触发
    analysis = _analyze_stock(df, life_info, DEFAULT_PARAMS)
    if analysis["signal_status"] == "triggered":
        marks.append({
            "date": df.iloc[last_idx]["trade_date"],
            "type": "buy_signal",
            "label": "买点",
            "value": float(df.iloc[last_idx]["close"]),
        })

    return marks


# ---------- 主入口：扫描池内所有股票 ----------

def scan_pool_buy_signals(db: Session, pool_id: str | None = None) -> dict:
    """
    对指定池（默认涨停池）内所有股票运行二阶段买点分析。
    返回 { signals: [...], scan_time, total, triggered_count, approaching_count }
    """
    if not pool_id:
        pool = db.query(WatchPool).filter(WatchPool.name == LIMIT_UP_POOL_NAME).first()
        if not pool:
            return {
                "signals": [],
                "scan_time": datetime.now().isoformat(),
                "total": 0,
                "triggered_count": 0,
                "approaching_count": 0,
            }
        pool_id = pool.id

    stocks = db.query(WatchStock).filter(WatchStock.pool_id == pool_id).all()
    basic_cache: dict[str, StockBasic | None] = {}
    signals: list[dict] = []
    params = DEFAULT_PARAMS.copy()

    for ws in stocks:
        if not ws.limit_up_date:
            continue

        ts_code = ws.ts_code
        df = _build_df(db, ts_code)
        if df.empty or len(df) < 10:
            continue

        df = _calc_indicators(df)

        # 阶段一：验证生命线
        life_info = _validate_life_line(df, ws.limit_up_date, ts_code)

        if not life_info:
            # 生命线不合格（一字板 / 量能不足等），但仍返回以便前端知晓
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
                "unmet_conditions": list(CONDITION_LABELS.values()),
                "rsi": None,
                "macd_hist": None,
                "volume_ratio": None,
            })
            continue

        # 阶段二：分析买点
        analysis = _analyze_stock(df, life_info, params)

        signals.append({
            "ts_code": ts_code,
            "name": _get_stock_name(db, ts_code, basic_cache),
            "industry": _get_stock_industry(db, ts_code, basic_cache),
            "life_line_date": ws.limit_up_date,
            "life_line_price": life_info["close"],
            **analysis,
        })

    # 排序：triggered > approaching > tracking > invalidated，同级按 score 降序
    status_order = {"triggered": 0, "approaching": 1, "tracking": 2, "invalidated": 3}
    signals.sort(key=lambda s: (status_order.get(s["signal_status"], 9), -s.get("signal_score", 0)))

    triggered = sum(1 for s in signals if s["signal_status"] == "triggered")
    approaching = sum(1 for s in signals if s["signal_status"] == "approaching")

    return {
        "signals": signals,
        "scan_time": datetime.now().isoformat(),
        "total": len(signals),
        "triggered_count": triggered,
        "approaching_count": approaching,
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
