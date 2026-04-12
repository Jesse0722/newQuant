"""
涨停回调买入法 — 六大战法（优化版）

公共前置筛选：
- 最近 N 天内涨停，非一字板
- 回调后未跌破涨停板最低价（1%容差）
- 涨停不在历史高位区间（排除拉升/出货板）
- 涨停日换手率在合理区间

六大战法各自的买点条件（统一加权评分）：
1. 次日缩量买入 — 涨停后5日内缩量靠拢均线企稳
2. 回踩5日线 — 回踩 MA5 止跌收阳
3. 三阴不破阳 — 连续阴线不破涨停低价，放量阳线反转
4. 缩倍量信号 — 缩倍量阴线锁筹，放量阳线突破涨停价
5. 均线金叉 — 回调缩量后 MA5 金叉 MA10
6. 搓揉线买入 — 长上影+长下影洗盘后突破起涨
"""

from __future__ import annotations
import numpy as np
import pandas as pd

# ================================================================
# 统一加权评分体系
# ================================================================

def _build_signal(conditions: dict[str, bool], cond_defs: dict[str, dict], metrics: dict) -> dict:
    """
    从条件结果 + 带权重定义构建信号字典。

    cond_defs 格式: {key: {"label": str, "weight": float, "core": bool}}
    """
    total_weight = sum(d["weight"] for d in cond_defs.values())
    met_weight = sum(cond_defs[k]["weight"] for k, v in conditions.items() if v)
    score = min(100, int(met_weight / total_weight * 100)) if total_weight > 0 else 0

    met = [cond_defs[k]["label"] for k, v in conditions.items() if v]
    unmet = [cond_defs[k]["label"] for k, v in conditions.items() if not v]

    all_core_met = all(
        conditions.get(k, False) for k, d in cond_defs.items() if d["core"]
    )

    if all_core_met and score >= 80:
        status = "triggered"
    elif all_core_met or score >= 65:
        status = "approaching"
    elif score >= 40:
        status = "tracking"
    else:
        status = "invalidated"

    return {
        "signal_status": status,
        "signal_score": score,
        "met_conditions": met,
        "unmet_conditions": unmet,
        **metrics,
    }


def _calc_persist_days(
    df: pd.DataFrame,
    limit_up_idx: int,
    analyze_fn,
    current_status: str,
    max_lookback: int = 2,
) -> int:
    """
    计算信号连续满足天数（含今日）。
    仅统计 triggered / approaching；其余状态返回 0。
    """
    if current_status not in ("triggered", "approaching"):
        return 0
    if max_lookback <= 0:
        return 1

    persist_days = 1
    total_len = len(df)
    for i in range(1, max_lookback + 1):
        cut_len = total_len - i
        if cut_len <= limit_up_idx + 1:
            break
        prev_df = df.iloc[:cut_len].copy()
        prev_sig = analyze_fn(prev_df, limit_up_idx)
        if prev_sig.get("signal_status") in ("triggered", "approaching"):
            persist_days += 1
        else:
            break
    return persist_days


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

    # 涨停日换手率过滤（可选：无数据时跳过）
    tr = row.get("turnover_rate")
    if tr is not None and not pd.isna(tr):
        if tr < 3.0 or tr > 25.0:
            return False, f"涨停日换手率异常({tr:.1f}%，合理区间3~25%)"

    limit_low = row["low"]
    post = df.iloc[limit_up_idx + 1 : latest_idx + 1]
    if len(post) > 0 and post["low"].min() < limit_low * 0.99:
        return False, "跌破涨停板最低价"

    # 高位判定：兼容短数据
    lookback = min(limit_up_idx, 60)
    if lookback >= 10:
        win = df.iloc[limit_up_idx - lookback : limit_up_idx]
        pmin, pmax = win["close"].min(), win["close"].max()
        if pmax > pmin:
            pos = (row["close"] - pmin) / (pmax - pmin)
            if pos >= 0.75:
                return False, "涨停处于历史高位区间（疑似拉升/出货板）"

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
    latest_close = float(latest["close"])
    stop_loss_price = round(float(lu["low"]) * 0.97, 2)
    target_price = round(float(lu["close"]) * 1.10, 2)
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
    return {
        "days_since_life_line": days,
        "phase2_high": ph,
        "pullback_pct": pb,
        "latest_close": latest_close,
        "latest_pct_chg": round(float(pct), 2) if pct is not None and not pd.isna(pct) else 0.0,
        "rsi": round(float(rsi), 1) if rsi is not None else None,
        "macd_hist": round(float(mh), 4) if mh is not None else None,
        "volume_ratio": round(float(vr), 2) if vr is not None else None,
        "signal_persist_days": 1,
        "stop_loss_price": stop_loss_price,
        "target_price": target_price,
        "stop_loss_pct": stop_loss_pct,
        "target_return_pct": target_return_pct,
        "risk_reward_ratio": risk_reward_ratio,
    }


# ================================================================
# 战法 1: 次日缩量买入（max_days=5）
# ================================================================

NEXT_DAY_SHRINK_CONDS = {
    "volume_shrink":    {"label": "回调期缩量（均量<涨停日60%）", "weight": 1.5, "core": True},
    "near_ma":          {"label": "价格靠近均线（MA5/MA10/MA20）", "weight": 1.0, "core": True},
    "not_break_low":    {"label": "未破涨停板最低价",             "weight": 1.5, "core": True},
    "stabilize":        {"label": "企稳信号（止跌回升）",         "weight": 1.0, "core": True},
    "no_big_yin":       {"label": "非大阴线（跌幅<3%）",          "weight": 0.5, "core": False},
    "time_window":      {"label": "涨停后5日内",                 "weight": 1.0, "core": True},
    "turnover_shrink":  {"label": "换手率缩小",                  "weight": 0.5, "core": False},
}


def analyze_next_day_shrink(df: pd.DataFrame, limit_up_idx: int) -> dict:
    latest_idx = len(df) - 1
    latest = df.iloc[latest_idx]
    lu = df.iloc[limit_up_idx]
    c: dict[str, bool] = {}

    # 回调期间平均量 < 涨停日量 * 0.6
    post = df.iloc[limit_up_idx + 1 : latest_idx + 1]
    if len(post) > 0:
        avg_vol = post["vol"].mean()
        c["volume_shrink"] = avg_vol < lu["vol"] * 0.6
    else:
        c["volume_shrink"] = False

    # 靠近均线
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

    # 企稳：今日收盘>=昨日收盘 且 今日最低>=昨日最低
    if latest_idx > limit_up_idx + 1:
        prev = df.iloc[latest_idx - 1]
        c["stabilize"] = (latest["close"] >= prev["close"]) and (latest["low"] >= prev["low"])
    elif latest_idx == limit_up_idx + 1:
        c["stabilize"] = latest["close"] >= lu["close"] * 0.95
    else:
        c["stabilize"] = False

    pct = latest.get("pct_chg", 0)
    c["no_big_yin"] = not pd.isna(pct) and pct > -3.0

    days_since = latest_idx - limit_up_idx
    c["time_window"] = 1 <= days_since <= 5

    # 换手率缩小
    lu_tr = lu.get("turnover_rate")
    cur_tr = latest.get("turnover_rate")
    if lu_tr is not None and not pd.isna(lu_tr) and cur_tr is not None and not pd.isna(cur_tr) and lu_tr > 0:
        c["turnover_shrink"] = cur_tr < lu_tr * 0.6
    else:
        c["turnover_shrink"] = False

    return _build_signal(c, NEXT_DAY_SHRINK_CONDS, _metrics(df, limit_up_idx))


# ================================================================
# 战法 2: 回踩5日线
# ================================================================

MA5_PULLBACK_CONDS = {
    "touch_ma5":          {"label": "日内回踩至MA5",       "weight": 1.0, "core": True},
    "close_near_ma5":     {"label": "收盘靠近MA5(偏离<2%)", "weight": 1.5, "core": True},
    "moderate_vol":       {"label": "成交量温和",           "weight": 0.5, "core": False},
    "yang_candle":        {"label": "收出阳线",             "weight": 1.0, "core": True},
    "above_ma5":          {"label": "收盘站上MA5",          "weight": 1.0, "core": True},
    "pullback_done":      {"label": "经历有效回调(>=3%)",    "weight": 1.0, "core": True},
    "ma5_rising":         {"label": "MA5走平或上升",        "weight": 1.0, "core": True},
    "turnover_moderate":  {"label": "换手率<5%",            "weight": 0.5, "core": False},
}


def analyze_ma5_pullback(df: pd.DataFrame, limit_up_idx: int) -> dict:
    latest_idx = len(df) - 1
    latest = df.iloc[latest_idx]
    c: dict[str, bool] = {}
    ma5 = latest.get("ma5")
    vol_ma5 = latest.get("vol_ma5")

    # 日内回踩MA5：最低价触及MA5附近
    if ma5 is not None and not pd.isna(ma5) and ma5 > 0:
        c["touch_ma5"] = latest["low"] <= ma5 * 1.01
    else:
        c["touch_ma5"] = False

    # 收盘靠近MA5：偏离不超过2%（防止日内探底后大幅反弹远离MA5的假信号）
    if ma5 is not None and not pd.isna(ma5) and ma5 > 0:
        dist = (latest["close"] - ma5) / ma5
        c["close_near_ma5"] = -0.005 <= dist <= 0.02
    else:
        c["close_near_ma5"] = False

    # 量能温和
    if vol_ma5 is not None and not pd.isna(vol_ma5) and vol_ma5 > 0:
        vr = latest["vol"] / vol_ma5
        c["moderate_vol"] = 0.3 <= vr <= 2.5
    else:
        c["moderate_vol"] = True

    c["yang_candle"] = latest["close"] > latest["open"]

    # 收盘站上MA5
    if ma5 is not None and not pd.isna(ma5):
        c["above_ma5"] = latest["close"] >= ma5 * 0.995
    else:
        c["above_ma5"] = False

    # 经历有效回调：阶段高点到当前收盘有>=3%回撤
    post = df.iloc[limit_up_idx + 1 : latest_idx + 1]
    if len(post) > 1:
        peak = post["close"].max()
        c["pullback_done"] = latest["close"] < peak * 0.97
    else:
        c["pullback_done"] = False

    # MA5方向：今日MA5 >= 昨日MA5（核心：防止下行趋势抄底）
    if latest_idx >= 1:
        prev_ma5 = df.iloc[latest_idx - 1].get("ma5")
        if ma5 is not None and not pd.isna(ma5) and prev_ma5 is not None and not pd.isna(prev_ma5):
            c["ma5_rising"] = ma5 >= prev_ma5
        else:
            c["ma5_rising"] = False
    else:
        c["ma5_rising"] = False

    # 换手率
    cur_tr = latest.get("turnover_rate")
    if cur_tr is not None and not pd.isna(cur_tr):
        c["turnover_moderate"] = cur_tr < 5.0
    else:
        c["turnover_moderate"] = False

    return _build_signal(c, MA5_PULLBACK_CONDS, _metrics(df, limit_up_idx))


# ================================================================
# 战法 3: 三阴不破阳
# ================================================================

THREE_YIN_CONDS = {
    "has_three_yin":    {"label": "涨停后连续≥3根阴线",         "weight": 1.5, "core": True},
    "yin_shrink_vol":   {"label": "阴线逐步缩量",              "weight": 1.0, "core": True},
    "yin_not_break":    {"label": "阴线未破涨停板最低价",        "weight": 1.5, "core": True},
    "today_yang":       {"label": "当日收出阳线",               "weight": 1.0, "core": True},
    "today_vol_expand": {"label": "当日放量（>阴线均量1.5倍）",  "weight": 1.0, "core": True},
    "small_yin_body":   {"label": "阴线跌幅均<3%",              "weight": 0.5, "core": False},
}


def analyze_three_yin(df: pd.DataFrame, limit_up_idx: int) -> dict:
    latest_idx = len(df) - 1
    latest = df.iloc[latest_idx]
    lu = df.iloc[limit_up_idx]
    c: dict[str, bool] = {}

    # 从今日前一天开始往回搜索连续阴线（允许最多1根几乎平盘的K线间断）
    yin_count = 0
    yin_vols: list[float] = []
    yin_pcts: list[float] = []
    yin_ok = True
    flat_tolerance = 1
    flat_used = 0
    for i in range(latest_idx - 1, limit_up_idx, -1):
        r = df.iloc[i]
        if r["close"] < r["open"]:
            yin_count += 1
            yin_vols.insert(0, float(r["vol"]))
            pct = r.get("pct_chg", 0)
            yin_pcts.insert(0, abs(float(pct)) if not pd.isna(pct) else 0.0)
            if r["low"] < lu["low"] * 0.99:
                yin_ok = False
        elif abs(float(r["close"]) - float(r["open"])) / max(float(r["open"]), 0.01) < 0.003:
            if flat_used < flat_tolerance:
                flat_used += 1
                if r["low"] < lu["low"] * 0.99:
                    yin_ok = False
            else:
                break
        else:
            break

    c["has_three_yin"] = yin_count >= 3

    # 缩量：5%容差
    if len(yin_vols) >= 2:
        c["yin_shrink_vol"] = all(
            yin_vols[j] <= yin_vols[j - 1] * 1.05 for j in range(1, len(yin_vols))
        )
    else:
        c["yin_shrink_vol"] = False

    c["yin_not_break"] = yin_ok

    c["today_yang"] = latest["close"] > latest["open"]

    # 放量：> 阴线期间平均量 * 1.5
    if yin_vols:
        avg_yin_vol = sum(yin_vols) / len(yin_vols)
        c["today_vol_expand"] = latest["vol"] > avg_yin_vol * 1.5
    else:
        c["today_vol_expand"] = False

    # 阴线实体均<3%
    if yin_pcts:
        c["small_yin_body"] = all(p < 3.0 for p in yin_pcts)
    else:
        c["small_yin_body"] = False

    return _build_signal(c, THREE_YIN_CONDS, _metrics(df, limit_up_idx))


# ================================================================
# 战法 4: 缩倍量信号
# ================================================================

HALF_VOL_CONDS = {
    "vol_lock":          {"label": "存在缩倍量阴线（≤涨停50%）", "weight": 1.5, "core": True},
    "today_yang":        {"label": "当日收出阳线",               "weight": 1.0, "core": True},
    "break_limit_price": {"label": "有效突破涨停收盘价",          "weight": 1.5, "core": True},
    "today_vol_expand":  {"label": "当日放量（>缩倍量日1.5倍）",  "weight": 1.0, "core": True},
    "time_proximity":    {"label": "缩倍量日在涨停后5日内",       "weight": 0.5, "core": False},
}


def analyze_half_volume(df: pd.DataFrame, limit_up_idx: int) -> dict:
    latest_idx = len(df) - 1
    latest = df.iloc[latest_idx]
    lu = df.iloc[limit_up_idx]
    c: dict[str, bool] = {}

    # 遍历所有缩倍量阴线，选量能最小的
    best_hv = None
    best_hv_idx = -1
    for i in range(limit_up_idx + 1, latest_idx):
        r = df.iloc[i]
        if r["close"] < r["open"] and r["vol"] <= lu["vol"] * 0.5:
            if best_hv is None or r["vol"] < best_hv["vol"]:
                best_hv = r
                best_hv_idx = i

    c["vol_lock"] = best_hv is not None

    c["today_yang"] = latest["close"] > latest["open"]
    c["break_limit_price"] = latest["close"] > lu["close"] * 1.005

    if best_hv is not None:
        c["today_vol_expand"] = latest["vol"] > best_hv["vol"] * 1.5
    elif latest_idx > limit_up_idx:
        c["today_vol_expand"] = latest["vol"] > df.iloc[latest_idx - 1]["vol"] * 1.3
    else:
        c["today_vol_expand"] = False

    # 时间邻近
    if best_hv_idx > 0:
        c["time_proximity"] = (best_hv_idx - limit_up_idx) <= 5
    else:
        c["time_proximity"] = False

    return _build_signal(c, HALF_VOL_CONDS, _metrics(df, limit_up_idx))


# ================================================================
# 战法 5: 均线金叉（max_days=30）
# ================================================================

MA_CROSS_CONDS = {
    "pullback_shrink":  {"label": "回调段缩量",          "weight": 1.0, "core": True},
    "ma5_cross_ma10":   {"label": "MA5金叉MA10（3日内）", "weight": 1.5, "core": True},
    "above_ma5":        {"label": "收盘站上MA5",          "weight": 1.0, "core": True},
    "above_ma10":       {"label": "收盘站上MA10",         "weight": 1.0, "core": True},
    "vol_support":      {"label": "量比≥1.0",            "weight": 0.8, "core": False},
    "ma5_turning_up":   {"label": "MA5拐头向上",          "weight": 0.8, "core": False},
    "ma10_flattening":  {"label": "MA10走平",             "weight": 0.5, "core": False},
}


def analyze_ma_golden_cross(df: pd.DataFrame, limit_up_idx: int) -> dict:
    latest_idx = len(df) - 1
    latest = df.iloc[latest_idx]
    lu = df.iloc[limit_up_idx]
    c: dict[str, bool] = {}

    # 回调段缩量：找阶段高点后的回调段
    post = df.iloc[limit_up_idx + 1 : latest_idx]
    if len(post) > 1:
        high_idx = post["close"].idxmax()
        pullback = df.iloc[high_idx + 1 : latest_idx]
        if len(pullback) > 0:
            pullback_avg_vol = pullback["vol"].mean()
            c["pullback_shrink"] = pullback_avg_vol < lu["vol"] * 0.6
        else:
            c["pullback_shrink"] = False
    else:
        c["pullback_shrink"] = False

    # MA5 金叉 MA10（3日内）
    cross = False
    for lb in range(min(3, latest_idx)):
        ci = latest_idx - lb
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
    c["vol_support"] = not pd.isna(vr) and vr >= 1.0

    # MA5 拐头向上：近2日至少1日上升
    ma5_up = False
    for lb in range(min(2, latest_idx)):
        ci = latest_idx - lb
        if ci < 1:
            break
        cur_ma5 = df.iloc[ci].get("ma5")
        prev_ma5 = df.iloc[ci - 1].get("ma5")
        if cur_ma5 is not None and not pd.isna(cur_ma5) and prev_ma5 is not None and not pd.isna(prev_ma5):
            if cur_ma5 > prev_ma5:
                ma5_up = True
                break
    c["ma5_turning_up"] = ma5_up

    # MA10 走平：近3日斜率绝对值 < 0.5%
    if latest_idx >= 3 and ma10 is not None and not pd.isna(ma10):
        prev3_ma10 = df.iloc[latest_idx - 3].get("ma10")
        if prev3_ma10 is not None and not pd.isna(prev3_ma10) and prev3_ma10 > 0:
            slope = abs(ma10 - prev3_ma10) / prev3_ma10
            c["ma10_flattening"] = slope < 0.005 * 3
        else:
            c["ma10_flattening"] = False
    else:
        c["ma10_flattening"] = False

    return _build_signal(c, MA_CROSS_CONDS, _metrics(df, limit_up_idx))


# ================================================================
# 战法 6: 搓揉线买入法
# ================================================================

RUBBING_LINE_CONDS = {
    "rubbing_pattern":        {"label": "发现搓揉线形态（长上影+长下影）", "weight": 1.5, "core": True},
    "day_upper_vol_moderate":  {"label": "上影日量能适中（≤涨停日量能）",  "weight": 1.0, "core": True},
    "day_upper_low_turnover": {"label": "上影日换手相对前一日±3%以内",     "weight": 1.5, "core": True},
    "day_lower_vol_shrink":   {"label": "下影日缩量（<上影日）",          "weight": 1.0, "core": True},
    "not_break_low":          {"label": "全程未破涨停板最低价",           "weight": 1.5, "core": True},
    "breakout_close":         {"label": "收盘突破上影最高价",             "weight": 1.5, "core": True},
}


def _long_upper_shadow(row) -> bool:
    body = abs(float(row["close"]) - float(row["open"]))
    rng = float(row["high"]) - float(row["low"])
    upper = float(row["high"]) - max(float(row["close"]), float(row["open"]))
    if rng <= 0:
        return False
    return upper > max(body * 1.5, rng * 0.3)


def _long_lower_shadow(row) -> bool:
    body = abs(float(row["close"]) - float(row["open"]))
    rng = float(row["high"]) - float(row["low"])
    lower = min(float(row["close"]), float(row["open"])) - float(row["low"])
    if rng <= 0:
        return False
    return lower > max(body * 1.5, rng * 0.3)


def analyze_rubbing_line(df: pd.DataFrame, limit_up_idx: int) -> dict:
    latest_idx = len(df) - 1
    lu = df.iloc[limit_up_idx]
    c: dict[str, bool] = {}

    # 窗口搜索：涨停后 1~5 日内找"长上影+次日长下影"组合
    rubbing_pair = None
    search_end = min(limit_up_idx + 6, latest_idx)
    for i in range(limit_up_idx + 1, search_end):
        if i + 1 > latest_idx:
            break
        if _long_upper_shadow(df.iloc[i]) and _long_lower_shadow(df.iloc[i + 1]):
            rubbing_pair = (i, i + 1)
            break

    c["rubbing_pattern"] = rubbing_pair is not None

    if rubbing_pair:
        day_upper_idx, day_lower_idx = rubbing_pair
        day_upper = df.iloc[day_upper_idx]
        day_lower = df.iloc[day_lower_idx]

        c["day_upper_vol_moderate"] = float(day_upper["vol"]) <= float(lu["vol"]) * 1.1
        c["day_lower_vol_shrink"] = float(day_lower["vol"]) < float(day_upper["vol"])

        # 上影日换手率与前一交易日之差的绝对值 <= 3 个百分点
        upper_tr = day_upper.get("turnover_rate")
        prev_tr = df.iloc[day_upper_idx - 1].get("turnover_rate")
        if (
            upper_tr is not None
            and not pd.isna(upper_tr)
            and prev_tr is not None
            and not pd.isna(prev_tr)
        ):
            c["day_upper_low_turnover"] = abs(float(upper_tr) - float(prev_tr)) <= 3.0
        else:
            c["day_upper_low_turnover"] = False

        # 全程未破涨停最低价
        post = df.iloc[limit_up_idx + 1 : latest_idx + 1]
        c["not_break_low"] = float(post["low"].min()) >= float(lu["low"]) * 0.99

        # 收盘突破上影最高价
        day_upper_high = float(day_upper["high"])
        if latest_idx > day_lower_idx:
            post_lower = df.iloc[day_lower_idx + 1 : latest_idx + 1]
            c["breakout_close"] = any(
                float(post_lower.iloc[j]["close"]) > day_upper_high
                for j in range(len(post_lower))
            ) if len(post_lower) > 0 else False
        else:
            c["breakout_close"] = False
    else:
        c["day_upper_vol_moderate"] = False
        c["day_upper_low_turnover"] = False
        c["day_lower_vol_shrink"] = False
        c["not_break_low"] = True
        c["breakout_close"] = False

    m = _metrics(df, limit_up_idx)

    # 双组搓揉线检测（在窗口中搜索第二组）
    double_rubbing = False
    if rubbing_pair:
        _, first_lower_idx = rubbing_pair
        search_end2 = min(first_lower_idx + 4, latest_idx)
        for i in range(first_lower_idx + 1, search_end2):
            if i + 1 > latest_idx:
                break
            if _long_upper_shadow(df.iloc[i]) and _long_lower_shadow(df.iloc[i + 1]):
                double_rubbing = True
                break

    sig = _build_signal(c, RUBBING_LINE_CONDS, m)

    if double_rubbing and sig["signal_score"] > 0:
        sig["signal_score"] = min(100, sig["signal_score"] + 10)
        if "两组搓揉线（更强信号）" not in sig["met_conditions"]:
            sig["met_conditions"].append("两组搓揉线（更强信号）")

    return sig


# ================================================================
# 战法注册表
# ================================================================

TACTIC_REGISTRY: dict[str, dict] = {
    "next_day_shrink": {
        "name": "次日缩量买入",
        "description": "涨停后5日内缩量调整，靠拢均线企稳时买入",
        "analyze_fn": analyze_next_day_shrink,
        "cond_defs": NEXT_DAY_SHRINK_CONDS,
        "max_days": 5,
    },
    "ma5_pullback": {
        "name": "回踩5日线",
        "description": "涨停后回踩MA5止跌，温和量收阳线买入",
        "analyze_fn": analyze_ma5_pullback,
        "cond_defs": MA5_PULLBACK_CONDS,
        "max_days": 20,
    },
    "three_yin": {
        "name": "三阴不破阳",
        "description": "连续三根缩量阴线不破涨停低价，放量阳线买入",
        "analyze_fn": analyze_three_yin,
        "cond_defs": THREE_YIN_CONDS,
        "max_days": 20,
    },
    "half_volume": {
        "name": "缩倍量信号",
        "description": "涨停后缩倍量阴线锁筹，放量阳线突破涨停价买入",
        "analyze_fn": analyze_half_volume,
        "cond_defs": HALF_VOL_CONDS,
        "max_days": 20,
    },
    "ma_golden_cross": {
        "name": "均线金叉",
        "description": "回调缩量后MA5金叉MA10买入",
        "analyze_fn": analyze_ma_golden_cross,
        "cond_defs": MA_CROSS_CONDS,
        "max_days": 30,
    },
    "rubbing_line": {
        "name": "搓揉线买入",
        "description": "涨停后长上影+长下影洗盘，突破上影高点起涨买入",
        "analyze_fn": analyze_rubbing_line,
        "cond_defs": RUBBING_LINE_CONDS,
        "max_days": 20,
    },
}
