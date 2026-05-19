"""股票 AI 智能分析服务。"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta
from typing import Any

import pandas as pd
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.message import MessageOpportunity, MessageSourceItem, MessageTopic
from app.models.pool import WatchPool, WatchStock
from app.models.stock import DailyQuote, StockAiAnalysis, StockBasic
from app.models.trade import TradeDetail
from app.services.buy_signal_service import _build_df, _calc_indicators
from app.services.limit_up_tactics import TACTIC_REGISTRY, common_pre_filter
from app.services.llm_client import call_llm_model
from app.services.sync_service import sync_daily, sync_stock_info
from app.services.trading_session import latest_daily_k_trade_date_str
from app.services.x_message_service import collect_x_stock_analysis_posts

PROMPT_VERSION = "1.0"
DISCLAIMER = "仅基于系统内数据生成，用于研究记录，不构成投资建议"
ORDER_SIGNAL_KEYWORDS = (
    "订单",
    "定单",
    "合同",
    "中标",
    "招标",
    "采购",
    "供货",
    "出货",
    "交付",
    "量产",
    "产能",
    "订单落地",
    "大单",
    "框架协议",
    "order",
    "contract",
    "purchase order",
    "supply agreement",
    "delivery",
    "shipment",
    "backlog",
    "bookings",
    "award",
    "tender",
)

ANALYSIS_PROMPT_TEMPLATE = """你是专业的A股研究助手。请只基于输入 JSON 中的系统数据进行分析。

硬性规则：
1. 不得承诺收益，不得使用“必涨、稳赚、确定买入”等表达。
2. 输入中缺失的基本面、消息面或交易数据，必须明确写“数据不足”，不得猜测。
3. 基本面只能基于 fundamental 中的基础画像、流通规模、上市年限、市场活跃度等字段；不要编造营收、利润、PE/PB。
4. 消息面优先判断 news.order_signals 是否存在订单、合同、中标、采购、出货、交付、量产等硬催化；没有则明确写“暂无订单/合同类消息”。
5. 每个结论应尽量引用输入中的客观证据。
6. 只返回 JSON，不要返回 markdown，不要补充解释。

输出 JSON 格式：
{{
  "version": "1.0",
  "rating": "强关注/观察/谨慎/回避",
  "score": 1-100 的整数,
  "confidence": 0-100 的整数,
  "trend": "上涨/震荡/下跌",
  "time_horizon": "短线/波段/中线",
  "summary": "80字以内综合总结",
  "sections": {{
    "technical": {{"score": 0-100, "conclusion": "一句话", "evidence": ["证据1"], "risk": "主要风险"}},
    "fundamental": {{"score": null 或 0-100, "conclusion": "一句话", "evidence": [], "risk": "主要风险"}},
    "news": {{"score": null 或 0-100, "conclusion": "一句话", "evidence": [], "risk": "主要风险"}},
    "trading": {{"score": null 或 0-100, "conclusion": "一句话", "evidence": [], "risk": "主要风险"}}
  }},
  "watch_plan": {{
    "key_levels": {{"support": [数字], "pressure": [数字], "risk_line": 数字或null}},
    "trigger_conditions": ["观察触发条件"],
    "invalid_conditions": ["失效条件"],
    "next_review": "复查时机"
  }},
  "data_quality": {{"score": 0-100, "warnings": ["数据质量提示"]}},
  "disclaimer": "{disclaimer}"
}}

输入 JSON：
{snapshot_json}
"""


def _to_float(v) -> float | None:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    try:
        return float(v)
    except Exception:
        return None


def _round(v, digits: int = 2) -> float | None:
    x = _to_float(v)
    return None if x is None else round(x, digits)


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


def _clip_int(v: Any, low: int, high: int, default: int) -> int:
    try:
        n = int(v)
    except Exception:
        n = default
    return max(low, min(high, n))


def _list_of_str(v: Any, limit: int = 6) -> list[str]:
    if not isinstance(v, list):
        return []
    out: list[str] = []
    for item in v[:limit]:
        text = str(item).strip()
        if text:
            out.append(text[:120])
    return out


def _section(data: dict, key: str, default: str) -> dict:
    raw = data.get(key)
    if not isinstance(raw, dict):
        raw = {}
    score = raw.get("score")
    return {
        "score": None if score is None else _clip_int(score, 0, 100, 50),
        "conclusion": str(raw.get("conclusion") or default)[:160],
        "evidence": _list_of_str(raw.get("evidence")),
        "risk": str(raw.get("risk") or "")[:160],
    }


def _sanitize_result(data: dict, snapshot: dict) -> dict:
    rating = str(data.get("rating") or "观察")
    if rating not in ("强关注", "观察", "谨慎", "回避"):
        rating = "观察"

    trend = str(data.get("trend") or "震荡")
    if trend not in ("上涨", "震荡", "下跌"):
        trend = "震荡"

    time_horizon = str(data.get("time_horizon") or "波段")
    if time_horizon not in ("短线", "波段", "中线"):
        time_horizon = "波段"

    sections_raw = data.get("sections") if isinstance(data.get("sections"), dict) else {}
    watch_raw = data.get("watch_plan") if isinstance(data.get("watch_plan"), dict) else {}
    levels_raw = watch_raw.get("key_levels") if isinstance(watch_raw.get("key_levels"), dict) else {}
    data_quality_raw = data.get("data_quality") if isinstance(data.get("data_quality"), dict) else {}

    technical_snapshot = snapshot.get("technical") if isinstance(snapshot.get("technical"), dict) else {}
    default_support = technical_snapshot.get("support_levels") or []
    default_pressure = technical_snapshot.get("pressure_levels") or []

    result = {
        "version": "1.0",
        "rating": rating,
        "score": _clip_int(data.get("score"), 1, 100, 50),
        "confidence": _clip_int(data.get("confidence"), 0, 100, snapshot.get("data_quality", {}).get("score", 50)),
        "trend": trend,
        "time_horizon": time_horizon,
        "summary": str(data.get("summary") or "")[:220],
        "sections": {
            "technical": _section(sections_raw, "technical", "技术面需结合最新K线继续观察"),
            "fundamental": _section(sections_raw, "fundamental", "系统暂未接入完整财务指标，基本面数据不足"),
            "news": _section(sections_raw, "news", "消息面数据不足或暂无明显催化"),
            "trading": _section(sections_raw, "trading", "交易上下文不足，按观察计划跟踪"),
        },
        "watch_plan": {
            "key_levels": {
                "support": [_round(x) for x in levels_raw.get("support", default_support) if _round(x) is not None][:3],
                "pressure": [_round(x) for x in levels_raw.get("pressure", default_pressure) if _round(x) is not None][:3],
                "risk_line": _round(levels_raw.get("risk_line")),
            },
            "trigger_conditions": _list_of_str(watch_raw.get("trigger_conditions"), limit=4),
            "invalid_conditions": _list_of_str(watch_raw.get("invalid_conditions"), limit=4),
            "next_review": str(watch_raw.get("next_review") or "收盘后结合量价变化复查")[:80],
        },
        "data_quality": {
            "score": _clip_int(data_quality_raw.get("score"), 0, 100, snapshot.get("data_quality", {}).get("score", 50)),
            "warnings": _list_of_str(data_quality_raw.get("warnings") or snapshot.get("data_quality", {}).get("warnings")),
        },
        "disclaimer": DISCLAIMER,
    }

    # 兼容观察池旧卡片展示。
    result["技术面"] = result["sections"]["technical"]["conclusion"]
    result["基本面"] = result["sections"]["fundamental"]["conclusion"]
    result["量能"] = _volume_summary(snapshot)
    result["风险提示"] = result["sections"]["technical"]["risk"] or result["sections"]["news"]["risk"]
    result["操作建议"] = result["watch_plan"]["next_review"]
    return result


def _volume_summary(snapshot: dict) -> str:
    ratio = (snapshot.get("technical") or {}).get("volume_ratio_5d")
    if ratio is None:
        return "量能数据不足"
    if ratio >= 1.5:
        return "近5日明显放量"
    if ratio >= 1.1:
        return "近5日温和放量"
    if ratio <= 0.8:
        return "近5日量能收缩"
    return "近5日量能平稳"


def _parse_trade_date(value: str | None) -> datetime | None:
    if not value or len(value) != 8:
        return None
    try:
        return datetime.strptime(value, "%Y%m%d")
    except Exception:
        return None


def _years_between(start: str | None, end: str | None) -> float | None:
    start_dt = _parse_trade_date(start)
    end_dt = _parse_trade_date(end)
    if not start_dt or not end_dt:
        return None
    return round(max(0, (end_dt - start_dt).days) / 365.25, 1)


def _classify_float_cap(float_market_cap_yuan: float | None) -> str | None:
    if float_market_cap_yuan is None:
        return None
    yi = float_market_cap_yuan / 100000000
    if yi >= 1000:
        return "超大盘"
    if yi >= 300:
        return "大盘"
    if yi >= 100:
        return "中大盘"
    if yi >= 50:
        return "中盘"
    return "小盘"


def _build_fundamental_snapshot(basic: StockBasic | None, latest: pd.Series, latest_date: str) -> dict:
    close = _to_float(latest.get("close"))
    float_share = _to_float(latest.get("float_share")) or (_to_float(basic.float_share) if basic else None)
    # Tushare float_share 通常为万股；估算流通市值 = 万股 * 10000 * 元。
    float_market_cap_yuan = close * float_share * 10000 if close is not None and float_share is not None else None
    latest_amount_yuan = _to_float(latest.get("amount"))
    if latest_amount_yuan is not None:
        # daily_quote.amount 在系统内沿用行情源原始口径，多数为千元；仅作为市场活跃度近似值。
        latest_amount_yuan = latest_amount_yuan * 1000

    available_fields = []
    for key, value in (
        ("industry", basic.industry if basic else None),
        ("area", basic.area if basic else None),
        ("market", basic.market if basic else None),
        ("list_date", basic.list_date if basic else None),
        ("float_share", float_share),
        ("turnover_rate", latest.get("turnover_rate")),
    ):
        if value is not None and value != "":
            available_fields.append(key)

    missing_fields = [
        label
        for key, label in (
            ("financial_report", "财报指标"),
            ("valuation", "估值指标"),
            ("revenue_profit", "营收/利润增速"),
            ("shareholder", "股东结构"),
        )
    ]

    return {
        "available": bool(available_fields),
        "available_fields": available_fields,
        "missing_fields": missing_fields,
        "profile": {
            "industry": basic.industry if basic else None,
            "area": basic.area if basic else None,
            "market": basic.market if basic else None,
            "list_date": basic.list_date if basic else None,
            "listed_years": _years_between(basic.list_date if basic else None, latest_date),
        },
        "scale_liquidity": {
            "float_share_10k_shares": _round(float_share),
            "float_market_cap_yuan_est": _round(float_market_cap_yuan, 0),
            "float_market_cap_yi_est": _round(float_market_cap_yuan / 100000000 if float_market_cap_yuan else None),
            "float_cap_bucket": _classify_float_cap(float_market_cap_yuan),
            "turnover_rate": _round(latest.get("turnover_rate")),
            "latest_amount_yuan_est": _round(latest_amount_yuan, 0),
            "latest_amount_yi_est": _round(latest_amount_yuan / 100000000 if latest_amount_yuan else None),
        },
        "limitations": "当前系统尚未接入营收、利润、现金流、PE/PB 等完整财务指标，基本面结论仅能做基础画像和流动性判断。",
    }


def _build_strategy_hits(df: pd.DataFrame, limit_up_date: str | None) -> list[dict]:
    if not limit_up_date:
        return []

    mask = df["trade_date"] == limit_up_date
    if not mask.any():
        return [{"name": "涨停回调战法", "status": "skipped", "reason": "K线数据中找不到对应涨停日"}]

    limit_up_idx = int(df.index[mask][0])
    ok, reason = common_pre_filter(df, limit_up_idx)
    if not ok:
        return [{"name": "公共前置筛选", "status": "failed", "reason": reason}]

    hits: list[dict] = []
    for tactic_id, tactic in TACTIC_REGISTRY.items():
        analysis = tactic["analyze_fn"](df, limit_up_idx)
        hits.append({
            "tactic_id": tactic_id,
            "name": tactic["name"],
            "status": analysis.get("signal_status"),
            "score": int(analysis.get("signal_score", 0) or 0),
            "met_count": len(analysis.get("met_conditions", [])),
            "unmet_count": len(analysis.get("unmet_conditions", [])),
        })
    return hits


def _build_data_quality(
    df: pd.DataFrame,
    latest_date: str | None,
    news: dict,
    trades: list[dict],
    fundamental: dict,
) -> dict:
    score = 0
    warnings: list[str] = []
    if len(df) >= 120:
        score += 35
    elif len(df) >= 40:
        score += 20
        warnings.append("K线满足最低分析要求，但中期样本不足")
    else:
        warnings.append("K线数据不足")

    if latest_date:
        score += 15
    else:
        warnings.append("缺少最新交易日")

    if fundamental.get("available"):
        score += 10
        if fundamental.get("missing_fields"):
            warnings.append("基本面仅含基础画像/流通规模，未含完整财报与估值指标")
    else:
        warnings.append("系统暂未接入可用基本面字段，基本面置信度受限")

    if news.get("items"):
        score += 20
        if news.get("order_signals"):
            score += 5
    else:
        warnings.append("近30日暂无系统内消息面记录")

    if trades:
        score += 10
    else:
        warnings.append("暂无近期交易明细")

    score += 10
    return {"score": min(100, score), "warnings": warnings}


def _ensure_analysis_kline_fresh(db: Session, ts_code: str) -> dict:
    target_latest = latest_daily_k_trade_date_str()
    latest = db.query(func.max(DailyQuote.trade_date)).filter(DailyQuote.ts_code == ts_code).scalar()
    if latest and latest >= target_latest:
        return {
            "attempted": False,
            "status": "up_to_date",
            "latest_trade_date": latest,
            "target_trade_date": target_latest,
        }

    try:
        sync_stock_info(db, ts_code)
        added = sync_daily(db, ts_code, days=250)
        db.expire_all()
        latest_after = db.query(func.max(DailyQuote.trade_date)).filter(DailyQuote.ts_code == ts_code).scalar()
        return {
            "attempted": True,
            "status": "updated" if (added or 0) > 0 else "unchanged",
            "latest_trade_date": latest_after or latest,
            "target_trade_date": target_latest,
            "added_count": int(added or 0),
        }
    except Exception as e:
        db.rollback()
        latest_after = db.query(func.max(DailyQuote.trade_date)).filter(DailyQuote.ts_code == ts_code).scalar()
        return {
            "attempted": True,
            "status": "failed",
            "latest_trade_date": latest_after or latest,
            "target_trade_date": target_latest,
            "message": str(e)[:160],
        }


def _latest_stock_analysis(db: Session, ts_code: str) -> StockAiAnalysis | None:
    return (
        db.query(StockAiAnalysis)
        .filter(StockAiAnalysis.ts_code == ts_code, StockAiAnalysis.status == "success")
        .order_by(StockAiAnalysis.created_at.desc())
        .first()
    )


def get_latest_stock_analysis(db: Session, ts_code: str) -> dict | None:
    record = _latest_stock_analysis(db, ts_code)
    return _record_to_response(record) if record else None


def _text_contains_order_signal(*parts: Any) -> bool:
    text = " ".join(str(part or "") for part in parts).lower()
    return any(keyword.lower() in text for keyword in ORDER_SIGNAL_KEYWORDS)


def _order_signal_keywords(*parts: Any) -> list[str]:
    text = " ".join(str(part or "") for part in parts).lower()
    return [keyword for keyword in ORDER_SIGNAL_KEYWORDS if keyword.lower() in text][:6]


def _topic_map(db: Session, topic_ids: list[str]) -> dict[str, MessageTopic]:
    if not topic_ids:
        return {}
    rows = db.query(MessageTopic).filter(MessageTopic.id.in_(topic_ids)).all()
    return {row.id: row for row in rows}


def _recent_stock_themes(db: Session, ts_code: str) -> list[str]:
    rows = (
        db.query(MessageOpportunity.theme)
        .filter(MessageOpportunity.ts_code == ts_code)
        .order_by(MessageOpportunity.trade_date.desc(), MessageOpportunity.opportunity_score.desc())
        .limit(5)
        .all()
    )
    themes: list[str] = []
    for (theme,) in rows:
        if theme and theme not in themes:
            themes.append(theme)
    return themes


def _collect_x_for_analysis(db: Session, ts_code: str, basic: StockBasic | None) -> dict:
    enabled = (os.getenv("AI_ANALYSIS_X_COLLECT_ENABLED") or "true").strip().lower() in {"1", "true", "yes", "on"}
    if not enabled:
        return {"attempted": False, "status": "disabled"}

    themes = _recent_stock_themes(db, ts_code)
    if basic and basic.industry and basic.industry not in themes:
        themes.append(basic.industry)

    try:
        result = collect_x_stock_analysis_posts(
            db,
            ts_code=ts_code,
            stock_name=basic.name if basic else None,
            industry=basic.industry if basic else None,
            themes=themes,
            max_results=10,
        )
        db.expire_all()
        return {"attempted": True, "status": "ok", **result}
    except Exception as e:
        db.rollback()
        return {"attempted": True, "status": "failed", "message": str(e)[:180]}


def _query_messages(db: Session, ts_code: str) -> dict:
    cutoff = (datetime.utcnow() - timedelta(days=45)).strftime("%Y%m%d")
    opportunities = (
        db.query(MessageOpportunity)
        .filter(MessageOpportunity.ts_code == ts_code, MessageOpportunity.trade_date >= cutoff)
        .order_by(MessageOpportunity.trade_date.desc(), MessageOpportunity.opportunity_score.desc())
        .limit(8)
        .all()
    )
    sources = (
        db.query(MessageSourceItem)
        .filter(MessageSourceItem.ts_code == ts_code, MessageSourceItem.trade_date >= cutoff)
        .order_by(MessageSourceItem.trade_date.desc(), MessageSourceItem.heat_score.desc())
        .limit(6)
        .all()
    )
    topics = _topic_map(db, [o.topic_id for o in opportunities if o.topic_id])
    items: list[dict] = []
    order_signals: list[dict] = []
    themes: dict[str, dict] = {}

    for o in opportunities:
        topic = topics.get(o.topic_id) if o.topic_id else None
        catalysts = o.catalysts or []
        risks = o.risks or []
        order_like = _text_contains_order_signal(o.reason, catalysts, risks, o.theme)
        row = {
            "type": "opportunity",
            "trade_date": o.trade_date,
            "theme": o.theme,
            "score": o.opportunity_score,
            "heat_score": o.heat_score,
            "credibility_score": o.credibility_score,
            "risk_score": o.risk_score,
            "reason": o.reason,
            "catalysts": catalysts,
            "risks": risks,
            "order_signal": order_like,
            "order_keywords": _order_signal_keywords(o.reason, catalysts, risks, o.theme),
            "topic_heat_score": topic.heat_score if topic else None,
            "topic_crowding_score": topic.crowding_score if topic else None,
            "topic_lifecycle_stage": topic.lifecycle_stage if topic else None,
        }
        items.append(row)
        theme_row = themes.setdefault(o.theme, {"theme": o.theme, "count": 0, "max_heat_score": 0, "max_risk_score": 0})
        theme_row["count"] += 1
        theme_row["max_heat_score"] = max(theme_row["max_heat_score"], o.heat_score)
        theme_row["max_risk_score"] = max(theme_row["max_risk_score"], o.risk_score)
        if order_like:
            order_signals.append({
                "source_type": "opportunity",
                "trade_date": o.trade_date,
                "theme": o.theme,
                "score": o.opportunity_score,
                "reason": o.reason,
                "matched_keywords": row["order_keywords"],
                "catalysts": catalysts,
            })

    for s in sources:
        order_like = _text_contains_order_signal(s.title, s.content, s.tags, s.theme)
        row = {
            "type": "source",
            "trade_date": s.trade_date,
            "channel": s.channel,
            "theme": s.theme,
            "title": s.title,
            "content": (s.content or "")[:180],
            "sentiment": s.sentiment,
            "heat_score": s.heat_score,
            "credibility_score": s.credibility_score,
            "order_signal": order_like,
            "order_keywords": _order_signal_keywords(s.title, s.content, s.tags, s.theme),
        }
        items.append(row)
        if s.theme:
            theme_row = themes.setdefault(s.theme, {"theme": s.theme, "count": 0, "max_heat_score": 0, "max_risk_score": 0})
            theme_row["count"] += 1
            theme_row["max_heat_score"] = max(theme_row["max_heat_score"], s.heat_score)
        if order_like:
            order_signals.append({
                "source_type": "source",
                "trade_date": s.trade_date,
                "channel": s.channel,
                "theme": s.theme,
                "title": s.title,
                "content": (s.content or "")[:220],
                "matched_keywords": row["order_keywords"],
                "credibility_score": s.credibility_score,
            })

    heat_scores = [int(item.get("heat_score") or 0) for item in items if item.get("heat_score") is not None]
    credibility_scores = [int(item.get("credibility_score") or 0) for item in items if item.get("credibility_score") is not None]
    return {
        "available": bool(items),
        "window_days": 45,
        "items": items[:12],
        "order_signals": order_signals[:8],
        "order_signal_count": len(order_signals),
        "has_order_signal": bool(order_signals),
        "themes": sorted(themes.values(), key=lambda x: (x["max_heat_score"], x["count"]), reverse=True)[:6],
        "summary_metrics": {
            "message_count": len(items),
            "theme_count": len(themes),
            "avg_heat_score": round(sum(heat_scores) / len(heat_scores), 1) if heat_scores else None,
            "avg_credibility_score": round(sum(credibility_scores) / len(credibility_scores), 1) if credibility_scores else None,
            "latest_trade_date": max([str(item.get("trade_date") or "") for item in items], default=None),
        },
        "interpretation_hint": (
            "存在订单/合同/中标/采购/出货等硬催化线索，请优先评估真实性、金额/客户/交付节点是否明确。"
            if order_signals
            else "近45日系统消息中未识别到订单/合同/中标/采购/出货等硬催化线索。"
        ),
    }


def _query_trades(db: Session, ts_code: str) -> list[dict]:
    rows = (
        db.query(TradeDetail)
        .filter(TradeDetail.ts_code == ts_code)
        .order_by(TradeDetail.trade_date.desc(), TradeDetail.created_at.desc())
        .limit(8)
        .all()
    )
    return [
        {
            "trade_date": r.trade_date,
            "direction": r.direction,
            "price": r.price,
            "quantity": r.quantity,
            "amount": r.amount,
            "note": r.exec_note,
        }
        for r in rows
    ]


def _build_snapshot(db: Session, ts_code: str, watch_stock_id: str | None = None, pool_id: str | None = None) -> dict:
    watch_stock = None
    pool = None
    if watch_stock_id:
        watch_stock = db.query(WatchStock).filter(WatchStock.id == watch_stock_id).first()
        if not watch_stock:
            raise ValueError("股票记录不存在")
        if watch_stock.ts_code != ts_code:
            raise ValueError("stock_id 与 ts_code 不匹配")
        pool_id = pool_id or watch_stock.pool_id
    if pool_id:
        pool = db.query(WatchPool).filter(WatchPool.id == pool_id).first()

    sync_meta = _ensure_analysis_kline_fresh(db, ts_code)
    basic = db.query(StockBasic).filter(StockBasic.ts_code == ts_code).first()
    x_collect_meta = _collect_x_for_analysis(db, ts_code, basic)
    df = _build_df(db, ts_code, limit=250)
    if df.empty or len(df) < 40:
        raise ValueError("K线数据不足（至少需要 40 个交易日）")

    df = _calc_indicators(df)
    latest = df.iloc[-1]
    latest_date = str(latest["trade_date"])
    win20 = df.tail(20)
    close = _to_float(latest.get("close"))
    low_20d = _to_float(win20["low"].min())
    high_20d = _to_float(win20["high"].max())
    if low_20d is not None and high_20d is not None and close is not None and high_20d > low_20d:
        pos_20 = (close - low_20d) / (high_20d - low_20d) * 100
    else:
        pos_20 = None

    recent_lows = sorted([_round(x) for x in win20["low"].tail(10).nsmallest(3).tolist() if _round(x) is not None])
    recent_highs = sorted([_round(x) for x in win20["high"].tail(10).nlargest(3).tolist() if _round(x) is not None])
    news = _query_messages(db, ts_code)
    news["x_collect_meta"] = x_collect_meta
    fundamental = _build_fundamental_snapshot(basic, latest, latest_date)
    trades = _query_trades(db, ts_code)

    snapshot = {
        "stock": {
            "ts_code": ts_code,
            "name": basic.name if basic else (watch_stock.stock_name if watch_stock else ts_code),
            "industry": basic.industry if basic else None,
            "area": basic.area if basic else None,
            "market": basic.market if basic else None,
            "list_date": basic.list_date if basic else None,
        },
        "market": {
            "latest_trade_date": latest_date,
            "close": _round(latest.get("close")),
            "pct_chg": _round(latest.get("pct_chg")),
            "turnover_rate": _round(latest.get("turnover_rate")),
            "amount": _round(latest.get("amount"), 0),
            "sync_meta": sync_meta,
        },
        "technical": {
            "ma5": _round(latest.get("ma5")),
            "ma10": _round(latest.get("ma10")),
            "ma20": _round(latest.get("ma20")),
            "macd_dif": _round(latest.get("macd_dif"), 4),
            "macd_dea": _round(latest.get("macd_dea"), 4),
            "macd_hist": _round(latest.get("macd_hist"), 4),
            "rsi14": _round(latest.get("rsi14")),
            "volume_ratio_5d": _round(df.tail(5).get("volume_ratio").mean()),
            "low_20d": _round(low_20d),
            "high_20d": _round(high_20d),
            "position_20d": _round(pos_20),
            "support_levels": recent_lows,
            "pressure_levels": recent_highs,
            "recent_kline": [
                {
                    "trade_date": str(row["trade_date"]),
                    "open": _round(row.get("open")),
                    "high": _round(row.get("high")),
                    "low": _round(row.get("low")),
                    "close": _round(row.get("close")),
                    "pct_chg": _round(row.get("pct_chg")),
                    "vol": _round(row.get("vol"), 0),
                }
                for _, row in df.tail(8).iterrows()
            ],
        },
        "signals": {
            "limit_up_date": watch_stock.limit_up_date if watch_stock else None,
            "limit_up_tactics": _build_strategy_hits(df, watch_stock.limit_up_date if watch_stock else None),
        },
        "fundamental": fundamental,
        "news": news,
        "user_context": {
            "pool_id": pool_id,
            "pool_name": pool.name if pool else None,
            "watch_stock_id": watch_stock_id,
            "note": watch_stock.note if watch_stock else None,
            "trades": trades,
        },
    }
    snapshot["data_quality"] = _build_data_quality(df, latest_date, news, trades, fundamental)
    return snapshot


def _select_model(mode: str) -> tuple[str, str]:
    provider = (os.getenv("AI_PROVIDER") or "deepseek").strip().lower()
    if provider == "deepseek":
        if mode == "fast":
            return provider, os.getenv("DEEPSEEK_FAST_MODEL", "deepseek-v4-flash")
        return provider, os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro")
    if provider == "openai":
        return provider, os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    if provider == "qwen":
        return provider, os.getenv("DASHSCOPE_MODEL", "qwen-plus")
    if provider == "ollama":
        return provider, os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
    return provider, os.getenv("OPENAI_MODEL", "gpt-4o-mini")


def _build_prompt(snapshot: dict) -> str:
    return ANALYSIS_PROMPT_TEMPLATE.format(
        disclaimer=DISCLAIMER,
        snapshot_json=json.dumps(snapshot, ensure_ascii=False, indent=2),
    )


def analyze_stock_detail(
    db: Session,
    ts_code: str,
    *,
    mode: str = "deep",
    scope: str = "stock_detail",
    pool_id: str | None = None,
    watch_stock_id: str | None = None,
    force_refresh: bool = False,
) -> dict:
    """对单只股票执行结构化 AI 分析，并保存分析记录。"""
    mode = mode if mode in ("fast", "deep") else "deep"
    snapshot = _build_snapshot(db, ts_code, watch_stock_id=watch_stock_id, pool_id=pool_id)
    data_trade_date = snapshot.get("market", {}).get("latest_trade_date")

    if not force_refresh:
        cached = _latest_stock_analysis(db, ts_code)
        if cached and cached.data_trade_date == data_trade_date:
            return _record_to_response(cached)

    provider, model_name = _select_model(mode)
    prompt = _build_prompt(snapshot)
    now = datetime.utcnow()
    try:
        raw = call_llm_model(prompt, provider=provider, model=model_name, temperature=0.15)
        parsed = _sanitize_result(_extract_json(raw), snapshot)
    except Exception as e:
        record = StockAiAnalysis(
            ts_code=ts_code,
            scope=scope,
            pool_id=pool_id,
            watch_stock_id=watch_stock_id,
            mode=mode,
            model_provider=provider,
            model_name=model_name,
            prompt_version=PROMPT_VERSION,
            snapshot_json=snapshot,
            raw_response=None,
            data_trade_date=data_trade_date,
            status="failed",
            error_message=str(e)[:500],
            created_at=now,
            updated_at=now,
        )
        db.add(record)
        db.commit()
        raise

    record = StockAiAnalysis(
        ts_code=ts_code,
        scope=scope,
        pool_id=pool_id,
        watch_stock_id=watch_stock_id,
        mode=mode,
        model_provider=provider,
        model_name=model_name,
        prompt_version=PROMPT_VERSION,
        snapshot_json=snapshot,
        analysis_json=parsed,
        raw_response=raw,
        data_trade_date=data_trade_date,
        status="success",
        created_at=now,
        updated_at=now,
    )
    db.add(record)

    if watch_stock_id:
        stock = db.query(WatchStock).filter(WatchStock.id == watch_stock_id).first()
        if stock and stock.ts_code == ts_code:
            stock.ai_analysis = json.dumps(parsed, ensure_ascii=False)
            stock.ai_analyzed_at = now

    db.commit()
    db.refresh(record)
    return _record_to_response(record)


def analyze_stock(db: Session, ts_code: str, stock_id: str) -> dict:
    """兼容旧策略路由：单只观察池股票 AI 分析。"""
    return analyze_stock_detail(
        db,
        ts_code,
        mode="deep",
        scope="watch_pool",
        watch_stock_id=stock_id,
        force_refresh=True,
    )


def _record_to_response(record: StockAiAnalysis | None) -> dict | None:
    if not record:
        return None
    analyzed_at = record.created_at.isoformat() if record.created_at else None
    return {
        "id": record.id,
        "stock_id": record.watch_stock_id,
        "ts_code": record.ts_code,
        "scope": record.scope,
        "mode": record.mode,
        "model_provider": record.model_provider,
        "model_name": record.model_name,
        "prompt_version": record.prompt_version,
        "analysis": record.analysis_json or {},
        "snapshot": record.snapshot_json or {},
        "data_trade_date": record.data_trade_date,
        "ai_analyzed_at": analyzed_at,
        "created_at": analyzed_at,
        "raw": record.raw_response or "",
    }
