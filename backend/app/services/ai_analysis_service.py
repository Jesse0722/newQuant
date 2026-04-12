"""股票 AI 智能分析服务。"""

from __future__ import annotations
import json
import re
from datetime import datetime

import pandas as pd
from sqlalchemy.orm import Session

from app.models.pool import WatchStock
from app.models.stock import StockBasic
from app.services.buy_signal_service import _build_df, _calc_indicators
from app.services.limit_up_tactics import TACTIC_REGISTRY, common_pre_filter
from app.services.llm_client import call_llm

ANALYSIS_PROMPT_TEMPLATE = """你是专业的A股分析师。请基于下列客观数据进行评估，避免空泛表述。

## 股票信息
- 名称：{name}
- 代码：{ts_code}
- 行业：{industry}
- 上市日期：{list_date}

## 最新技术指标（{latest_date}）
- 收盘价：{close}
- 涨跌幅：{pct_chg}%
- MA5={ma5}, MA10={ma10}, MA20={ma20}
- MACD DIF={dif}, DEA={dea}, HIST={hist}
- RSI14={rsi14}
- 5日均量比={vol_ratio_5d}
- 20日价格区间：{low_20d} ~ {high_20d}，当前位置 {position_20d}%

## 近5日K线（日期 开 高 低 收 涨跌幅 成交量）
{kline_text}

## 买点策略扫描摘要
{strategy_hits}

请严格仅返回 JSON，不要返回 markdown，不要补充解释。格式如下：
{{
  "score": 1-10 的整数,
  "trend": "上涨/震荡/下跌",
  "技术面": "一句话，20字以内",
  "基本面": "一句话，20字以内",
  "量能": "一句话，20字以内",
  "风险提示": "一句话，25字以内",
  "操作建议": "一句话，25字以内",
  "summary": "50字以内综合总结"
}}
"""


def _to_float(v) -> float | None:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    try:
        return float(v)
    except Exception:
        return None


def _fmt_num(v, digits: int = 2) -> str:
    x = _to_float(v)
    if x is None:
        return "-"
    return f"{x:.{digits}f}"


def _extract_json(text: str) -> dict:
    raw = text.strip()
    try:
        return json.loads(raw)
    except Exception:
        pass

    match = re.search(r"\{[\s\S]*\}", raw)
    if match:
        try:
            return json.loads(match.group(0))
        except Exception:
            pass
    raise ValueError("AI 返回结果不是有效 JSON")


def _sanitize_result(data: dict) -> dict:
    score = data.get("score", 0)
    try:
        score = int(score)
    except Exception:
        score = 0
    score = max(1, min(10, score))

    trend = str(data.get("trend") or "震荡")
    if trend not in ("上涨", "震荡", "下跌"):
        trend = "震荡"

    return {
        "score": score,
        "trend": trend,
        "技术面": str(data.get("技术面") or ""),
        "基本面": str(data.get("基本面") or ""),
        "量能": str(data.get("量能") or ""),
        "风险提示": str(data.get("风险提示") or ""),
        "操作建议": str(data.get("操作建议") or ""),
        "summary": str(data.get("summary") or ""),
    }


def _build_kline_text(df: pd.DataFrame) -> str:
    rows = df.tail(5)
    lines = []
    for _, row in rows.iterrows():
        lines.append(
            f"{row['trade_date']} 开{_fmt_num(row.get('open'))} "
            f"高{_fmt_num(row.get('high'))} 低{_fmt_num(row.get('low'))} 收{_fmt_num(row.get('close'))} "
            f"涨跌{_fmt_num(row.get('pct_chg'))}% 量{_fmt_num(row.get('vol'), 0)}"
        )
    return "\n".join(lines)


def _build_strategy_hits(df: pd.DataFrame, limit_up_date: str | None) -> str:
    if not limit_up_date:
        return "无涨停日记录，未执行涨停回调战法。"

    mask = df["trade_date"] == limit_up_date
    if not mask.any():
        return "K线数据中找不到对应涨停日，未执行涨停回调战法。"

    limit_up_idx = int(df.index[mask][0])
    ok, reason = common_pre_filter(df, limit_up_idx)
    if not ok:
        return f"公共前置筛选未通过：{reason}"

    lines: list[str] = []
    for tactic_id, tactic in TACTIC_REGISTRY.items():
        analysis = tactic["analyze_fn"](df, limit_up_idx)
        lines.append(
            f"- {tactic['name']}({tactic_id})：{analysis.get('signal_status')}，"
            f"评分{analysis.get('signal_score', 0)}，"
            f"已满足={len(analysis.get('met_conditions', []))}项，"
            f"未满足={len(analysis.get('unmet_conditions', []))}项"
        )
    return "\n".join(lines)


def analyze_stock(db: Session, ts_code: str, stock_id: str) -> dict:
    """对单只股票执行 AI 分析并写回 watch_stock。"""
    stock = db.query(WatchStock).filter(WatchStock.id == stock_id).first()
    if not stock:
        raise ValueError("股票记录不存在")
    if stock.ts_code != ts_code:
        raise ValueError("stock_id 与 ts_code 不匹配")

    basic = db.query(StockBasic).filter(StockBasic.ts_code == ts_code).first()
    df = _build_df(db, ts_code, limit=250)
    if df.empty or len(df) < 40:
        raise ValueError("K线数据不足（至少需要 40 个交易日）")

    df = _calc_indicators(df)
    latest = df.iloc[-1]
    latest_date = str(latest["trade_date"])

    # 近 20 日位置
    win20 = df.tail(20)
    low_20d = _to_float(win20["low"].min())
    high_20d = _to_float(win20["high"].max())
    close = _to_float(latest.get("close"))
    if low_20d is not None and high_20d is not None and close is not None and high_20d > low_20d:
        pos_20 = (close - low_20d) / (high_20d - low_20d) * 100
    else:
        pos_20 = None

    vol_ratio_5d = _to_float(df.tail(5).get("volume_ratio").mean())
    prompt = ANALYSIS_PROMPT_TEMPLATE.format(
        name=basic.name if basic else ts_code,
        ts_code=ts_code,
        industry=(basic.industry if basic and basic.industry else "-"),
        list_date=(basic.list_date if basic and basic.list_date else "-"),
        latest_date=latest_date,
        close=_fmt_num(latest.get("close")),
        pct_chg=_fmt_num(latest.get("pct_chg")),
        ma5=_fmt_num(latest.get("ma5")),
        ma10=_fmt_num(latest.get("ma10")),
        ma20=_fmt_num(latest.get("ma20")),
        dif=_fmt_num(latest.get("macd_dif"), 4),
        dea=_fmt_num(latest.get("macd_dea"), 4),
        hist=_fmt_num(latest.get("macd_hist"), 4),
        rsi14=_fmt_num(latest.get("rsi14")),
        vol_ratio_5d=_fmt_num(vol_ratio_5d),
        low_20d=_fmt_num(low_20d),
        high_20d=_fmt_num(high_20d),
        position_20d=_fmt_num(pos_20),
        kline_text=_build_kline_text(df),
        strategy_hits=_build_strategy_hits(df, stock.limit_up_date),
    )

    raw = call_llm(prompt, temperature=0.2)
    parsed = _sanitize_result(_extract_json(raw))

    now = datetime.utcnow()
    stock.ai_analysis = json.dumps(parsed, ensure_ascii=False)
    stock.ai_analyzed_at = now
    db.commit()
    db.refresh(stock)

    return {
        "stock_id": stock.id,
        "ts_code": stock.ts_code,
        "analysis": parsed,
        "ai_analyzed_at": now.isoformat(),
        "raw": raw,
    }
