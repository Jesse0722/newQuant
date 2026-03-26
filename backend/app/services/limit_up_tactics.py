"""
涨停回调买入法 - 五大战法

公共前置筛选：
- 最近 N 天内涨停，非一字板
- 回调后未跌破涨停板最低价
- 涨停不在 60 日高位区间（排除拉升/出货板）

五大战法各自的买点条件：
1. 次日缩量买入 — 涨停次日缩量，靠拢均线企稳
2. 回踩5日线 — 回踩 MA5 止跌收阳
3. 三阴不破阳 — 3 根缩量阴线不破涨停低价，第 4 日放量阳
4. 缩倍量信号 — 缩倍量阴线锁筹，放量阳线突破涨停价
5. 均线金叉 — 回调缩量后 MA5 金叉 MA10
"""
import numpy as np
import pandas as pd

# ================================================================
# 公共工具
# ================================================================

def common_pre_filter(df: pd.DataFrame, limit_up_idx: int, max_days: int = 20) -> tuple[bool, str]:
    """公共前置条件检查，返回 (通过?, 原因)"""
    latest_idx = len(df) - 1
    days_since = latest_idx - limit_up_idx
    row = df.iloc[limit_up_idx]

    if row["high"] == row["low"]:
        return False, "一字板涨停，无回调操作空间"
    if days_since < 1:
        return False, "涨停当天，需等待后续走势"
    if days_since > max_days:
        return False, f"超出跟踪窗口（>{max_days}个交易日）"

    limit_low = row["low"]
    post = df.iloc[limit_up_idx + 1 : latest_idx + 1]
    if len(post) > 0 and post["low"].min() < limit_low * 0.98:
        return False, "跌破涨停板最低价"

    if limit_up_idx >= 60:
        win = df.iloc[limit_up_idx - 60 : limit_up_idx]
        pmin, pmax = win["close"].min(), win["close"].max()
        if pmax > pmin:
            pos = (row["close"] - pmin) / (pmax - pmin)
            if pos >= 0.75:
                return False, "涨停处于60日高位区间（疑似拉升/出货板）"

    return True, ""


def _metrics(df: pd.DataFrame, limit_up_idx: int) -> dict:
    """通用指标提取"""
    latest = df.iloc[-1]
    lu = df.iloc[limit_up_idx]
    days = len(df) - 1 - limit_up_idx
    post = df.iloc[limit_up_idx + 1:]
    ph = float(post["close"].max()) if len(post) > 0 else float(lu["close"])
    pb = round((ph - latest["close"]) / ph * 100, 2) if ph > 0 else 0

    def _safe(v):
        return None if v is None or (isinstance(v, float) and np.isnan(v)) else v

    rsi = _safe(latest.get("rsi14"))
    mh = _safe(latest.get("macd_hist"))
    vr = _safe(latest.get("volume_ratio"))
    pct = latest.get("pct_chg")
    return {
        "days_since_life_line": days,
        "phase2_high": ph,
        "pullback_pct": pb,
        "latest_close": float(latest["close"]),
        "latest_pct_chg": round(float(pct), 2) if pct is not None and not pd.isna(pct) else 0.0,
        "rsi": round(float(rsi), 1) if rsi is not None else None,
        "macd_hist": round(float(mh), 4) if mh is not None else None,
        "volume_ratio": round(float(vr), 2) if vr is not None else None,
    }


def _build_signal(conditions: dict[str, bool], labels: dict[str, str], metrics: dict) -> dict:
    """从条件结果构建信号字典"""
    total = len(labels)
    met = [labels[k] for k, v in conditions.items() if v]
    unmet = [labels[k] for k, v in conditions.items() if not v]
    n = len(met)

    if n == total:
        status = "triggered"
    elif n >= total - 1:
        status = "approaching"
    elif n >= max(total // 2, 1):
        status = "tracking"
    else:
        status = "invalidated"

    score = min(100, int(n / total * 100)) if total > 0 else 0
    return {
        "signal_status": status,
        "signal_score": score,
        "met_conditions": met,
        "unmet_conditions": unmet,
        **metrics,
    }


# ================================================================
# 战法 1: 次日缩量买入
# ================================================================

NEXT_DAY_SHRINK_LABELS = {
    "volume_shrink": "回调缩量（量<涨停日50%）",
    "near_ma": "价格靠近均线（MA5/MA10/MA20）",
    "not_break_low": "未破涨停板最低价",
    "stabilize": "企稳信号（止跌回升）",
    "no_big_yin": "非大阴线（跌幅<3%）",
}


def analyze_next_day_shrink(df: pd.DataFrame, limit_up_idx: int) -> dict:
    latest = df.iloc[-1]
    lu = df.iloc[limit_up_idx]
    c = {}

    c["volume_shrink"] = latest["vol"] < lu["vol"] * 0.6

    close = latest["close"]
    near = False
    for col in ("ma5", "ma10", "ma20"):
        ma = latest.get(col)
        if ma is not None and not pd.isna(ma) and ma > 0:
            if abs(close - ma) / ma < 0.02:
                near = True
                break
    c["near_ma"] = near

    c["not_break_low"] = latest["low"] >= lu["low"] * 0.99

    idx = len(df) - 1
    if idx > limit_up_idx + 1:
        prev = df.iloc[idx - 1]
        c["stabilize"] = latest["close"] >= prev["close"] * 0.99 or latest["low"] > prev["low"]
    else:
        c["stabilize"] = True

    pct = latest.get("pct_chg", 0)
    c["no_big_yin"] = not pd.isna(pct) and pct > -3.0

    return _build_signal(c, NEXT_DAY_SHRINK_LABELS, _metrics(df, limit_up_idx))


# ================================================================
# 战法 2: 回踩5日线
# ================================================================

MA5_PULLBACK_LABELS = {
    "touch_ma5": "回踩至MA5附近",
    "moderate_vol": "成交量温和（无巨量砸盘）",
    "yang_candle": "收出阳线（收盘>开盘）",
    "above_ma5": "收盘站上MA5",
    "pullback_done": "经历回调（非直接拉升）",
}


def analyze_ma5_pullback(df: pd.DataFrame, limit_up_idx: int) -> dict:
    latest = df.iloc[-1]
    c = {}
    ma5 = latest.get("ma5")
    vol_ma5 = latest.get("vol_ma5")

    if ma5 is not None and not pd.isna(ma5) and ma5 > 0:
        c["touch_ma5"] = latest["low"] <= ma5 * 1.015 and latest["close"] >= ma5 * 0.985
    else:
        c["touch_ma5"] = False

    if vol_ma5 is not None and not pd.isna(vol_ma5) and vol_ma5 > 0:
        vr = latest["vol"] / vol_ma5
        c["moderate_vol"] = 0.3 <= vr <= 2.5
    else:
        c["moderate_vol"] = True

    c["yang_candle"] = latest["close"] > latest["open"]

    if ma5 is not None and not pd.isna(ma5):
        c["above_ma5"] = latest["close"] >= ma5
    else:
        c["above_ma5"] = False

    idx = len(df) - 1
    post = df.iloc[limit_up_idx + 1 : idx + 1]
    if len(post) > 1:
        ph = post["close"].max()
        c["pullback_done"] = latest["close"] < ph * 0.99 or (idx - limit_up_idx <= 3)
    else:
        c["pullback_done"] = idx - limit_up_idx >= 2

    return _build_signal(c, MA5_PULLBACK_LABELS, _metrics(df, limit_up_idx))


# ================================================================
# 战法 3: 三阴不破阳
# ================================================================

THREE_YIN_LABELS = {
    "has_three_yin": "涨停后连续≥3根阴线",
    "yin_shrink_vol": "阴线逐步缩量",
    "yin_not_break": "阴线未破涨停板最低价",
    "today_yang": "当日收出阳线",
    "today_vol_expand": "当日放量（>前日1.3倍）",
}


def analyze_three_yin(df: pd.DataFrame, limit_up_idx: int) -> dict:
    latest = df.iloc[-1]
    lu = df.iloc[limit_up_idx]
    idx = len(df) - 1
    c = {}

    yin_count = 0
    yin_vols: list[float] = []
    yin_ok = True
    for i in range(idx - 1, limit_up_idx, -1):
        r = df.iloc[i]
        if r["close"] < r["open"]:
            yin_count += 1
            yin_vols.insert(0, float(r["vol"]))
            if r["low"] < lu["low"] * 0.99:
                yin_ok = False
        else:
            break

    c["has_three_yin"] = yin_count >= 3

    if len(yin_vols) >= 2:
        c["yin_shrink_vol"] = all(
            yin_vols[j] <= yin_vols[j - 1] * 1.15 for j in range(1, len(yin_vols))
        )
    else:
        c["yin_shrink_vol"] = False

    c["yin_not_break"] = yin_ok

    c["today_yang"] = latest["close"] > latest["open"]

    if yin_vols:
        c["today_vol_expand"] = latest["vol"] > yin_vols[-1] * 1.3
    else:
        c["today_vol_expand"] = False

    return _build_signal(c, THREE_YIN_LABELS, _metrics(df, limit_up_idx))


# ================================================================
# 战法 4: 缩倍量信号
# ================================================================

HALF_VOL_LABELS = {
    "has_half_vol_yin": "涨停后出现缩倍量阴线",
    "vol_half": "阴线量≤涨停日50%（主力锁筹）",
    "today_yang": "当日收出阳线",
    "break_limit_price": "突破涨停收盘价",
    "today_vol_expand": "当日放量（>缩倍量日1.5倍）",
}


def analyze_half_volume(df: pd.DataFrame, limit_up_idx: int) -> dict:
    latest = df.iloc[-1]
    lu = df.iloc[limit_up_idx]
    idx = len(df) - 1
    c = {}

    hv_candle = None
    for i in range(limit_up_idx + 1, idx):
        r = df.iloc[i]
        if r["close"] < r["open"] and r["vol"] <= lu["vol"] * 0.6:
            hv_candle = r
            break

    c["has_half_vol_yin"] = hv_candle is not None
    c["vol_half"] = hv_candle is not None and hv_candle["vol"] <= lu["vol"] * 0.55

    c["today_yang"] = latest["close"] > latest["open"]
    c["break_limit_price"] = latest["close"] > lu["close"]

    if hv_candle is not None:
        c["today_vol_expand"] = latest["vol"] > hv_candle["vol"] * 1.5
    elif idx > limit_up_idx:
        c["today_vol_expand"] = latest["vol"] > df.iloc[idx - 1]["vol"] * 1.3
    else:
        c["today_vol_expand"] = False

    return _build_signal(c, HALF_VOL_LABELS, _metrics(df, limit_up_idx))


# ================================================================
# 战法 5: 均线金叉
# ================================================================

MA_CROSS_LABELS = {
    "pullback_shrink": "回调阶段缩量",
    "ma5_cross_ma10": "MA5金叉MA10（3日内）",
    "above_ma5": "收盘站上MA5",
    "above_ma10": "收盘站上MA10",
    "vol_support": "量能配合（量比≥0.8）",
}


def analyze_ma_golden_cross(df: pd.DataFrame, limit_up_idx: int) -> dict:
    latest = df.iloc[-1]
    idx = len(df) - 1
    c = {}

    if idx >= limit_up_idx + 4:
        mid = (limit_up_idx + idx) // 2
        v1 = df.iloc[limit_up_idx + 1 : mid + 1]["vol"].mean()
        v2 = df.iloc[mid + 1 : idx]["vol"].mean()
        c["pullback_shrink"] = (
            not pd.isna(v1) and not pd.isna(v2) and v1 > 0 and v2 < v1 * 0.9
        )
    else:
        c["pullback_shrink"] = False

    cross = False
    for lb in range(min(3, idx)):
        ci = idx - lb
        if ci < 1:
            break
        cur5, cur10 = df.iloc[ci].get("ma5"), df.iloc[ci].get("ma10")
        pre5, pre10 = df.iloc[ci - 1].get("ma5"), df.iloc[ci - 1].get("ma10")
        if all(v is not None and not pd.isna(v) for v in (cur5, cur10, pre5, pre10)):
            if cur5 > cur10 and pre5 <= pre10:
                cross = True
                break
    c["ma5_cross_ma10"] = cross

    ma5 = latest.get("ma5")
    ma10 = latest.get("ma10")
    c["above_ma5"] = ma5 is not None and not pd.isna(ma5) and latest["close"] >= ma5
    c["above_ma10"] = ma10 is not None and not pd.isna(ma10) and latest["close"] >= ma10

    vr = latest.get("volume_ratio", 0)
    c["vol_support"] = not pd.isna(vr) and vr >= 0.8

    return _build_signal(c, MA_CROSS_LABELS, _metrics(df, limit_up_idx))


# ================================================================
# 战法注册表
# ================================================================

TACTIC_REGISTRY: dict[str, dict] = {
    "next_day_shrink": {
        "name": "次日缩量买入",
        "description": "涨停次日缩量调整，靠拢均线企稳时买入",
        "analyze_fn": analyze_next_day_shrink,
        "labels": NEXT_DAY_SHRINK_LABELS,
    },
    "ma5_pullback": {
        "name": "回踩5日线",
        "description": "涨停后回踩MA5止跌，温和量收阳线买入",
        "analyze_fn": analyze_ma5_pullback,
        "labels": MA5_PULLBACK_LABELS,
    },
    "three_yin": {
        "name": "三阴不破阳",
        "description": "连续三根缩量阴线不破涨停低价，第四日放量阳线买入",
        "analyze_fn": analyze_three_yin,
        "labels": THREE_YIN_LABELS,
    },
    "half_volume": {
        "name": "缩倍量信号",
        "description": "涨停后缩倍量阴线锁筹，放量阳线突破涨停价买入",
        "analyze_fn": analyze_half_volume,
        "labels": HALF_VOL_LABELS,
    },
    "ma_golden_cross": {
        "name": "均线金叉",
        "description": "回调缩量后MA5金叉MA10买入",
        "analyze_fn": analyze_ma_golden_cross,
        "labels": MA_CROSS_LABELS,
    },
}
