"""股票 AI 智能分析服务。"""

from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request
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
from app.services.industry_report_service import get_stock_graph_context
from app.services.sync_service import sync_daily, sync_stock_info
from app.services.trading_session import latest_daily_k_trade_date_str
from app.services.x_message_service import collect_x_stock_analysis_posts

PROMPT_VERSION = "1.0"
DISCLAIMER = "仅基于系统内数据生成，用于研究记录，不构成投资建议"
OFFICIAL_CONTEXT_KEYWORDS = (
    "年度报告",
    "季度报告",
    "一季度",
    "年报",
    "业绩",
    "利润",
    "营收",
    "现金流",
    "毛利率",
    "合同负债",
    "分红",
    "转增",
    "异常波动",
    "算力",
    "订单",
    "客户",
    "合同",
    "调研",
    "投资者关系",
    "互动易",
    "业绩说明会",
    "新存科技",
    "天链芯",
    "PCM",
    "相变存储",
    "存储芯片",
    "存储模组",
    "固态硬盘",
    "SSD",
    "企业级SSD",
    "工程样品",
    "核心测试",
    "客户验证",
    "小批量",
    "未量产",
    "尚未量产",
    "没有量产",
)
MAJOR_CHANGE_KEYWORDS = (
    "再融资",
    "问询",
    "回复",
    "募投",
    "定增",
    "增发",
    "收购",
    "并购",
    "重组",
    "重大资产",
    "转型",
    "投资",
    "设立",
    "增资",
    "算力",
    "云服务",
    "新业务",
    "新存科技",
    "天链芯",
    "PCM",
    "相变存储",
    "存储芯片",
    "存储模组",
    "固态硬盘",
    "SSD",
    "工程样品",
    "核心测试",
    "客户验证",
    "小批量",
)
PROGRESS_SIGNAL_KEYWORDS = (
    "完成研发",
    "研发完成",
    "工程样品",
    "核心测试",
    "客户验证",
    "小批量",
    "小批量出货",
    "批量出货",
    "量产",
    "试产",
    "认证",
    "导入",
    "交付",
    "出货",
    "投产",
)
NEGATIVE_VERIFICATION_KEYWORDS = (
    "未量产",
    "尚未量产",
    "没有量产",
    "不属实",
    "未形成收入",
    "尚未形成收入",
    "不存在",
    "未签署",
    "未达到",
)
MAJOR_MEDIA_SOURCES = (
    "上海证券报",
    "证券时报",
    "中国证券报",
    "证券日报",
    "中证报",
    "财联社",
    "第一财经",
    "经济观察网",
    "每日经济新闻",
    "界面新闻",
    "澎湃",
    "新浪财经",
    "东方财富",
    "同花顺",
    "证券之星",
    "智通财经",
)
SOCIAL_MESSAGE_CHANNELS = (
    "X",
    "Twitter",
    "雪球",
    "淘股吧",
    "小红书",
    "微博",
)
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
VALUE_SIGNAL_KEYWORDS = (
    "扩产",
    "产能提升",
    "产能爬坡",
    "新增产能",
    "产能利用率",
    "订单量",
    "订单增长",
    "在手订单",
    "大客户",
    "客户导入",
    "批量供货",
    "收入指引",
    "业绩指引",
    "销售额",
    "营收",
    "毛利率",
    "市占率",
    "份额提升",
    "亿元",
    "capacity",
    "capacity expansion",
    "ramp",
    "utilization",
    "volume",
    "shipment volume",
    "backlog",
    "book-to-bill",
    "customer win",
    "design win",
    "guidance",
    "revenue",
    "margin",
    "market share",
)

ANALYSIS_PROMPT_TEMPLATE = """你是专业的A股研究助手。请只基于输入 JSON 中的系统数据进行分析。

硬性规则：
1. 不得承诺收益，不得使用“必涨、稳赚、确定买入”等表达。
2. 输入中缺失的基本面、消息面或交易数据，必须明确写“数据不足”，不得猜测。
3. 基本面只能使用财报、公告、正规财务接口返回的 fundamental.business.latest_financial_abstract、latest_financial_metrics、official_context.verified_facts 中的最新报告期数据；不要使用更早报告期覆盖最新报告期，不得引用社媒或市场传闻作为基本面证据。
4. 消息面可信度顺序：公司公告/财报 > 大型财经媒体/交易所披露转载 > 系统内消息机会 > X/社媒。没有官方公告或大型媒体支撑时，不得把“订单、客户、英伟达/NVIDIA合作、收入指引、量产、产业链闭环”写成确定事实，只能写“X/社媒小作文线索，待公告或大型媒体验证”。
5. 消息面优先判断 news.official_context、news.order_signals 与 news.value_signals 是否存在订单、合同、中标、采购、出货、交付、量产、扩产、客户、收入指引、工程样品、核心测试、客户验证等可验证催化；没有则明确写“暂无官方订单/产能/客户/收入类公告”。如果存在“未量产、未形成收入、未签署”等反证，必须在消息面风险中优先提示。
6. 每个结论应尽量引用输入中的客观证据，证据需带报告期/公告日期/来源类型/source_note；不允许凭主题关键词编造具体客户、合同金额或交付节点。
7. 只返回 JSON，不要返回 markdown，不要补充解释。

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
    _enrich_fundamental_section(result, snapshot)
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


def _append_unique_text(items: list[str], text: str | None, limit: int = 6) -> None:
    value = _compact_text(text, 140)
    if value and value not in items and len(items) < limit:
        items.append(value)


def _business_profile_from_snapshot(snapshot: dict) -> dict:
    fundamental = snapshot.get("fundamental") if isinstance(snapshot.get("fundamental"), dict) else {}
    return _compact_business_profile(fundamental.get("business") or {}, fundamental.get("related_concepts"))


def _major_change_signals_from_context(official_context: dict, limit: int = 3) -> list[str]:
    signals: list[str] = []
    rows = []
    rows.extend(official_context.get("announcements") or [])
    rows.extend(official_context.get("market_news") or [])
    for row in rows:
        text = _record_text(row)
        if not _contains_any_keyword(text, MAJOR_CHANGE_KEYWORDS):
            continue
        date = row.get("date") or row.get("published_at")
        title = row.get("title")
        note = row.get("source_note")
        _append_unique_text(signals, f"{date or ''} {title or ''}（{note or '来源待核验'}）", limit=limit)
    return signals


def _progress_signals_from_context(official_context: dict, limit: int = 3) -> list[str]:
    signals: list[str] = []
    rows = []
    rows.extend(official_context.get("announcements") or [])
    rows.extend(official_context.get("market_news") or [])
    for row in rows:
        text = _record_text(row)
        if not _contains_any_keyword(text, PROGRESS_SIGNAL_KEYWORDS):
            continue
        date = row.get("date") or row.get("published_at")
        title = row.get("title")
        note = row.get("source_note")
        _append_unique_text(signals, f"{date or ''} {title or ''}（{note or '来源待核验'}）", limit=limit)
    return signals


def _verification_risk_signals_from_context(official_context: dict, limit: int = 3) -> list[str]:
    signals: list[str] = []
    rows = []
    rows.extend(official_context.get("announcements") or [])
    rows.extend(official_context.get("market_news") or [])
    for row in rows:
        text = _record_text(row)
        if not _contains_any_keyword(text, NEGATIVE_VERIFICATION_KEYWORDS):
            continue
        date = row.get("date") or row.get("published_at")
        title = row.get("title")
        note = row.get("source_note")
        _append_unique_text(signals, f"{date or ''} {title or ''}（{note or '来源待核验'}）", limit=limit)
    return signals


def _business_evidence_from_snapshot(snapshot: dict) -> list[str]:
    profile = _business_profile_from_snapshot(snapshot)
    evidence: list[str] = []
    _append_unique_text(evidence, f"主营业务：{profile.get('main_business')}" if profile.get("main_business") else None, limit=8)
    _append_unique_text(evidence, f"产品类型：{profile.get('product_types')}" if profile.get("product_types") else None, limit=8)
    top_segments = profile.get("top_segments") or []
    if top_segments:
        segment_parts = []
        for item in top_segments[:3]:
            segment = item.get("segment")
            revenue_pct = item.get("revenue_pct")
            gross_margin = item.get("gross_margin_pct")
            if segment:
                segment_parts.append(f"{segment}收入占比{revenue_pct}%/毛利率{gross_margin}%")
        _append_unique_text(evidence, "主营构成：" + "；".join(segment_parts) if segment_parts else None, limit=8)
    official_context = (
        ((snapshot.get("fundamental") or {}).get("business") or {}).get("official_context")
        or (snapshot.get("news") or {}).get("official_context")
        or {}
    )
    for signal in _verification_risk_signals_from_context(official_context, limit=1):
        _append_unique_text(evidence, "核验反证：" + signal, limit=8)
    for signal in _progress_signals_from_context(official_context, limit=2):
        _append_unique_text(evidence, "研发/量产进展：" + signal, limit=8)
    for signal in _major_change_signals_from_context(official_context, limit=2):
        _append_unique_text(evidence, "重大变化线索：" + signal, limit=8)
    return evidence[:8]


def _enrich_fundamental_section(result: dict, snapshot: dict) -> None:
    fundamental = result.get("sections", {}).get("fundamental")
    if not isinstance(fundamental, dict):
        return
    evidence = fundamental.setdefault("evidence", [])
    if not isinstance(evidence, list):
        evidence = []
        fundamental["evidence"] = evidence
    business_evidence = _business_evidence_from_snapshot(snapshot)
    for item in reversed(business_evidence):
        if item not in evidence:
            evidence.insert(0, item)
    fundamental["evidence"] = evidence[:8]
    result["基本面"] = fundamental.get("conclusion") or result.get("基本面")


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


def _ts_symbol(ts_code: str) -> str:
    return str(ts_code or "").split(".")[0]


def _em_symbol(ts_code: str) -> str:
    symbol, _, exch = str(ts_code or "").partition(".")
    if exch.upper() in {"SH", "SZ", "BJ"}:
        return f"{exch.upper()}{symbol}"
    return symbol


def _first_text_from_df(df: pd.DataFrame | None, keys: tuple[str, ...], limit: int = 500) -> str | None:
    if df is None or df.empty:
        return None
    for _, row in df.iterrows():
        for col in df.columns:
            text_col = str(col)
            if not any(key in text_col for key in keys):
                continue
            value = row.get(col)
            if value is not None and not pd.isna(value):
                text = str(value).strip()
                if text and text.lower() != "nan":
                    return text[:limit]
    return None


def _json_safe_value(value: Any) -> Any:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    return value


def _records_from_df(df: pd.DataFrame | None, limit: int = 5) -> list[dict]:
    if df is None or df.empty:
        return []
    out: list[dict] = []
    for record in df.head(limit).to_dict("records"):
        clean: dict[str, Any] = {}
        for key, value in record.items():
            if value is None or (isinstance(value, float) and pd.isna(value)):
                continue
            clean[str(key)] = _json_safe_value(value)
        if clean:
            out.append(clean)
    return out


def _find_period_column(columns: list[Any]) -> Any | None:
    candidates = ("报告期", "日期", "公告日期", "截止日期", "报表日期")
    for col in columns:
        col_name = str(col)
        if any(key in col_name for key in candidates):
            return col
    return None


def _normalize_period_value(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).strip()
    digits = re.sub(r"\D", "", text)
    if len(digits) >= 8:
        return digits[:8]
    return digits


def _sort_financial_rows_latest_first(df: pd.DataFrame | None) -> pd.DataFrame | None:
    if df is None or df.empty:
        return df
    period_col = _find_period_column(list(df.columns))
    if not period_col:
        return df
    sorted_df = df.copy()
    sorted_df["_period_sort_key"] = sorted_df[period_col].map(_normalize_period_value)
    sorted_df = sorted_df.sort_values("_period_sort_key", ascending=False, kind="stable")
    return sorted_df.drop(columns=["_period_sort_key"])


def _latest_financial_metrics(df: pd.DataFrame | None) -> dict:
    df = _sort_financial_rows_latest_first(df)
    if df is None or df.empty:
        return {}
    row = df.iloc[0]
    wanted = (
        "报告期",
        "日期",
        "营业收入",
        "营业总收入",
        "净利润",
        "扣非净利润",
        "每股收益",
        "净资产收益率",
        "毛利率",
        "资产负债率",
        "经营现金流",
        "每股净资产",
    )
    metrics: dict[str, Any] = {}
    for col in df.columns:
        col_name = str(col)
        if not any(key in col_name for key in wanted):
            continue
        value = row.get(col)
        if value is None or (isinstance(value, float) and pd.isna(value)):
            continue
        metrics[col_name] = _json_safe_value(value)
    return metrics


def _financial_abstract_latest_metrics(df: pd.DataFrame | None) -> dict:
    if df is None or df.empty:
        return {}
    period_cols = sorted(
        [str(col) for col in df.columns if re.fullmatch(r"\d{8}", str(col))],
        reverse=True,
    )
    if not period_cols:
        return {}
    latest_period = period_cols[0]
    wanted = (
        "营业总收入",
        "营业收入",
        "归母净利润",
        "扣非净利润",
        "毛利率",
        "净利率",
        "净资产收益率",
        "每股收益",
        "经营现金流",
        "资产负债率",
    )
    metrics: dict[str, Any] = {"报告期": latest_period}
    metric_col = next((col for col in df.columns if str(col) == "指标"), None)
    if metric_col is None:
        return metrics
    for _, row in df.iterrows():
        metric_name = str(row.get(metric_col) or "").strip()
        if not metric_name or not any(key in metric_name for key in wanted):
            continue
        value = row.get(latest_period)
        if value is None or (isinstance(value, float) and pd.isna(value)):
            continue
        metrics[metric_name] = _json_safe_value(value)
    return metrics


def _format_yi(value: Any) -> float | None:
    number = _to_float(value)
    return None if number is None else round(number / 100000000, 2)


def _pct_change(current: Any, previous: Any) -> float | None:
    cur = _to_float(current)
    prev = _to_float(previous)
    if cur is None or prev in (None, 0):
        return None
    return round((cur - prev) / abs(prev) * 100, 2)


def _financial_abstract_period_facts(df: pd.DataFrame | None) -> dict:
    if df is None or df.empty:
        return {}
    period_cols = sorted(
        [str(col) for col in df.columns if re.fullmatch(r"\d{8}", str(col))],
        reverse=True,
    )
    if not period_cols:
        return {}
    latest_period = period_cols[0]
    prior_year_period = f"{int(latest_period[:4]) - 1}{latest_period[4:]}"
    prior_period = prior_year_period if prior_year_period in period_cols else (period_cols[1] if len(period_cols) > 1 else None)
    metric_col = next((col for col in df.columns if str(col) == "指标"), None)
    if metric_col is None:
        return {}

    metrics_by_name: dict[str, Any] = {}
    prior_by_name: dict[str, Any] = {}
    for _, row in df.iterrows():
        metric_name = str(row.get(metric_col) or "").strip()
        if not metric_name:
            continue
        metrics_by_name[metric_name] = _json_safe_value(row.get(latest_period))
        if prior_period:
            prior_by_name[metric_name] = _json_safe_value(row.get(prior_period))

    def metric(*names: str) -> Any:
        for name in names:
            if name in metrics_by_name and metrics_by_name[name] is not None:
                return metrics_by_name[name]
        return None

    def prior_metric(*names: str) -> Any:
        for name in names:
            if name in prior_by_name and prior_by_name[name] is not None:
                return prior_by_name[name]
        return None

    revenue = metric("营业总收入", "营业收入")
    net_profit = metric("归母净利润", "净利润")
    deduct_profit = metric("扣非净利润")
    cash_flow = metric("经营现金流量净额", "经营现金流")
    gross_margin = metric("销售毛利率", "毛利率")
    debt_ratio = metric("资产负债率")
    return {
        "period": latest_period,
        "compare_period": prior_period,
        "revenue_yi": _format_yi(revenue),
        "revenue_yoy_pct": _pct_change(revenue, prior_metric("营业总收入", "营业收入")),
        "net_profit_yi": _format_yi(net_profit),
        "net_profit_yoy_pct": _pct_change(net_profit, prior_metric("归母净利润", "净利润")),
        "deduct_net_profit_yi": _format_yi(deduct_profit),
        "deduct_net_profit_yoy_pct": _pct_change(deduct_profit, prior_metric("扣非净利润")),
        "operating_cash_flow_yi": _format_yi(cash_flow),
        "operating_cash_flow_yoy_pct": _pct_change(cash_flow, prior_metric("经营现金流量净额", "经营现金流")),
        "gross_margin_pct": _round(gross_margin),
        "debt_ratio_pct": _round(debt_ratio),
    }


def _financial_balance_sheet_facts(df: pd.DataFrame | None) -> dict:
    if df is None or df.empty:
        return {}
    sorted_df = df.copy()
    if "REPORT_DATE" in sorted_df.columns:
        sorted_df["_period_sort_key"] = sorted_df["REPORT_DATE"].map(_normalize_period_value)
        sorted_df = sorted_df.sort_values("_period_sort_key", ascending=False, kind="stable")
    latest = sorted_df.iloc[0]
    prior = sorted_df.iloc[1] if len(sorted_df) > 1 else None

    def get(row: pd.Series | None, key: str) -> Any:
        if row is None or key not in row:
            return None
        return row.get(key)

    contract_liab = get(latest, "CONTRACT_LIAB")
    prior_contract_liab = get(prior, "CONTRACT_LIAB")
    total_assets = get(latest, "TOTAL_ASSETS")
    total_liabilities = get(latest, "TOTAL_LIABILITIES")
    return {
        "period": _normalize_period_value(get(latest, "REPORT_DATE")),
        "report_type": get(latest, "REPORT_TYPE"),
        "contract_liabilities_yi": _format_yi(contract_liab),
        "contract_liabilities_prev_yi": _format_yi(prior_contract_liab),
        "contract_liabilities_qoq_pct": _pct_change(contract_liab, prior_contract_liab),
        "total_assets_yi": _format_yi(total_assets),
        "total_liabilities_yi": _format_yi(total_liabilities),
        "debt_ratio_est_pct": _round((_to_float(total_liabilities) / _to_float(total_assets) * 100) if _to_float(total_assets) else None),
    }


def _record_text(record: dict) -> str:
    return " ".join(str(value or "") for value in record.values())


def _contains_any_keyword(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword.lower() in text.lower() for keyword in keywords)


def _is_major_media_source(*parts: Any) -> bool:
    text = " ".join(str(part or "") for part in parts)
    return any(source.lower() in text.lower() for source in MAJOR_MEDIA_SOURCES)


def _is_social_channel(channel: Any) -> bool:
    text = str(channel or "").strip().lower()
    return any(text == channel.lower() for channel in SOCIAL_MESSAGE_CHANNELS)


def _notice_art_code_from_url(url: Any) -> str | None:
    match = re.search(r"/(AN\d+)\.html", str(url or ""))
    return match.group(1) if match else None


def _should_fetch_notice_content(record: dict) -> bool:
    text = _record_text(record)
    return _contains_any_keyword(
        text,
        (
            "投资者关系",
            "调研",
            "业绩说明会",
            "互动易",
            "问询",
            "回复",
            "记录表",
        ),
    )


def _fetch_eastmoney_notice_content(url: Any, timeout: int = 6) -> dict:
    art_code = _notice_art_code_from_url(url)
    if not art_code:
        return {}
    api_url = "https://np-cnotice-stock.eastmoney.com/api/content/ann?" + urllib.parse.urlencode(
        {"art_code": art_code, "client_source": "web", "page_index": 1}
    )
    req = urllib.request.Request(api_url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="ignore"))
    except Exception:
        return {}
    data = payload.get("data") if isinstance(payload, dict) else {}
    if not isinstance(data, dict):
        return {}
    return {
        "content": data.get("notice_content"),
        "title": data.get("notice_title"),
        "pdf_url": data.get("attach_url_web") or data.get("attach_url"),
    }


def _keyword_snippet(text: Any, keywords: tuple[str, ...], limit: int = 220, fallback_to_start: bool = True) -> str | None:
    cleaned = re.sub(r"\s+", " ", str(text or "")).strip()
    if not cleaned:
        return None
    lower = cleaned.lower()
    positions = [lower.find(keyword.lower()) for keyword in keywords if keyword and lower.find(keyword.lower()) >= 0]
    if not positions:
        if not fallback_to_start:
            return None
        return _compact_text(cleaned, limit)
    start = max(0, min(positions) - 60)
    return _compact_text(cleaned[start : start + limit], limit)


def _source_confidence(channel: Any = None, source_name: Any = None, source_platforms: Any = None) -> str:
    platforms = source_platforms if isinstance(source_platforms, list) else []
    if _is_major_media_source(channel, source_name, platforms):
        return "major_financial_media"
    if _is_social_channel(channel) or any(_is_social_channel(item) for item in platforms):
        return "social_rumor"
    if channel or source_name or platforms:
        return "imported_source"
    return "unknown_source"


def _source_note(confidence: str, channel: Any = None, source_name: Any = None) -> str:
    source = " / ".join(str(item) for item in (channel, source_name) if item)
    if confidence == "official_announcement":
        return f"公司公告/财报来源：{source or '公告'}"
    if confidence == "major_financial_media":
        return f"大型财经媒体来源：{source or '财经媒体'}"
    if confidence == "market_news":
        return f"财经新闻来源：{source or '财经新闻'}"
    if confidence == "social_rumor":
        return f"X/社媒小作文线索，未按公告验证：{source or '社媒'}"
    if confidence == "system_derived_opportunity":
        return "系统聚合机会，需回看原始来源验证"
    if confidence == "imported_source":
        return f"导入消息来源：{source or '未知渠道'}"
    return "未知来源，需谨慎验证"


def _fetch_external_official_context(ts_code: str, mode: str, financial_df: pd.DataFrame | None = None) -> dict:
    if mode != "deep":
        return {"attempted": False, "status": "skipped_fast_mode"}
    try:
        import akshare as ak
    except Exception as e:
        return {"attempted": True, "status": "failed", "message": f"AkShare 不可用：{str(e)[:120]}"}

    symbol = _ts_symbol(ts_code)
    result: dict[str, Any] = {
        "attempted": True,
        "status": "partial",
        "sources": [],
        "verified_facts": {},
        "announcements": [],
        "market_news": [],
    }
    errors: list[str] = []

    facts = _financial_abstract_period_facts(financial_df)
    if facts:
        result["verified_facts"]["latest_financial_period"] = facts

    try:
        balance_df = ak.stock_balance_sheet_by_report_em(symbol=_em_symbol(ts_code))
        result["sources"].append("stock_balance_sheet_by_report_em")
        balance_facts = _financial_balance_sheet_facts(balance_df)
        if balance_facts:
            result["verified_facts"]["latest_balance_sheet"] = balance_facts
    except Exception as e:
        errors.append(f"资产负债表失败：{str(e)[:100]}")

    today = datetime.utcnow()
    begin_date = (today - timedelta(days=90)).strftime("%Y%m%d")
    end_date = today.strftime("%Y%m%d")
    try:
        notice_df = ak.stock_individual_notice_report(
            security=symbol,
            symbol="全部",
            begin_date=begin_date,
            end_date=end_date,
        )
        result["sources"].append("stock_individual_notice_report")
        notices = _records_from_df(notice_df, limit=40)
        relevant_notices = []
        for item in notices:
            record_text = _record_text(item)
            detail = _fetch_eastmoney_notice_content(item.get("网址")) if _should_fetch_notice_content(item) else {}
            detail_text = detail.get("content") or ""
            combined_text = f"{record_text} {detail_text}"
            if not _contains_any_keyword(combined_text, OFFICIAL_CONTEXT_KEYWORDS):
                continue
            summary = (
                _keyword_snippet(combined_text, PROGRESS_SIGNAL_KEYWORDS, fallback_to_start=False)
                or _keyword_snippet(combined_text, NEGATIVE_VERIFICATION_KEYWORDS, fallback_to_start=False)
                or _keyword_snippet(combined_text, MAJOR_CHANGE_KEYWORDS, fallback_to_start=False)
                or _keyword_snippet(combined_text, OFFICIAL_CONTEXT_KEYWORDS)
            )
            relevant_notices.append({
                "date": item.get("公告日期"),
                "title": detail.get("title") or item.get("公告标题"),
                "type": item.get("公告类型"),
                "url": item.get("网址"),
                "pdf_url": detail.get("pdf_url"),
                "summary": summary,
                "source_confidence": "official_announcement",
                "source_note": _source_note("official_announcement", "公司公告", item.get("公告类型")),
            })
        result["announcements"] = relevant_notices[:12]
    except Exception as e:
        errors.append(f"个股公告失败：{str(e)[:100]}")

    try:
        news_df = ak.stock_news_em(symbol=symbol)
        result["sources"].append("stock_news_em")
        news_rows = _records_from_df(news_df, limit=20)
        relevant_news = []
        for item in news_rows:
            if not _contains_any_keyword(_record_text(item), OFFICIAL_CONTEXT_KEYWORDS):
                continue
            confidence = "major_financial_media" if _is_major_media_source(item.get("文章来源")) else "market_news"
            relevant_news.append({
                "published_at": item.get("发布时间"),
                "title": item.get("新闻标题"),
                "summary": str(item.get("新闻内容") or "")[:220],
                "source": item.get("文章来源"),
                "url": item.get("新闻链接"),
                "source_confidence": confidence,
                "source_note": _source_note(confidence, item.get("文章来源")),
            })
        result["market_news"] = relevant_news[:8]
    except Exception as e:
        errors.append(f"个股新闻失败：{str(e)[:100]}")

    result["status"] = "ok" if (result["verified_facts"] or result["announcements"] or result["market_news"]) else "failed"
    if errors:
        result["errors"] = errors[:6]
    return result


def _fetch_external_fundamental(ts_code: str, stock_name: str | None, mode: str) -> dict:
    if mode != "deep":
        return {"attempted": False, "status": "skipped_fast_mode"}

    try:
        import akshare as ak
    except Exception as e:
        return {"attempted": True, "status": "failed", "message": f"AkShare 不可用：{str(e)[:120]}"}

    symbol = _ts_symbol(ts_code)
    em_symbol = _em_symbol(ts_code)
    result: dict[str, Any] = {"attempted": True, "status": "partial", "sources": []}
    errors: list[str] = []

    try:
        info_df = ak.stock_individual_info_em(symbol=symbol, timeout=8)
        result["sources"].append("stock_individual_info_em")
        result["company_profile"] = _records_from_df(info_df, limit=20)
    except Exception as e:
        errors.append(f"个股资料失败：{str(e)[:100]}")

    try:
        business_df = ak.stock_zyjs_ths(symbol=symbol)
        result["sources"].append("stock_zyjs_ths")
        result["main_business"] = _first_text_from_df(
            business_df,
            ("主营业务", "经营范围", "业务", "介绍", "公司简介"),
            limit=700,
        )
        result["business_description_rows"] = _records_from_df(business_df, limit=3)
    except Exception as e:
        errors.append(f"主营业务失败：{str(e)[:100]}")

    try:
        composition_df = ak.stock_zygc_em(symbol=em_symbol)
        result["sources"].append("stock_zygc_em")
        result["business_composition"] = _records_from_df(composition_df, limit=8)
    except Exception as e:
        errors.append(f"主营构成失败：{str(e)[:100]}")

    try:
        financial_df = ak.stock_financial_analysis_indicator(symbol=symbol, start_year=str(datetime.utcnow().year - 2))
        result["sources"].append("stock_financial_analysis_indicator")
        result["latest_financial_metrics"] = _latest_financial_metrics(financial_df)
        result["financial_rows"] = _records_from_df(_sort_financial_rows_latest_first(financial_df), limit=4)
    except Exception as e:
        errors.append(f"财务指标失败：{str(e)[:100]}")

    abstract_df = None
    try:
        abstract_df = ak.stock_financial_abstract(symbol=symbol)
        result["sources"].append("stock_financial_abstract")
        abstract_metrics = _financial_abstract_latest_metrics(abstract_df)
        if abstract_metrics:
            result["latest_financial_abstract"] = abstract_metrics
            result["latest_financial_period_facts"] = _financial_abstract_period_facts(abstract_df)
            if not result.get("latest_financial_metrics"):
                result["latest_financial_metrics"] = abstract_metrics
    except Exception as e:
        errors.append(f"财务摘要失败：{str(e)[:100]}")

    official_context = _fetch_external_official_context(ts_code, mode, financial_df=abstract_df)
    result["official_context"] = official_context

    has_payload = any(
        result.get(key)
        for key in (
            "company_profile",
            "main_business",
            "business_composition",
            "latest_financial_metrics",
            "latest_financial_abstract",
            "financial_rows",
        )
    )
    result["status"] = "ok" if has_payload else "failed"
    if errors:
        result["errors"] = errors[:6]
    if stock_name:
        result["stock_name"] = stock_name
    return result


def _build_fundamental_snapshot(
    basic: StockBasic | None,
    latest: pd.Series,
    latest_date: str,
    ts_code: str,
    mode: str,
    related_concepts: list[str],
) -> dict:
    close = _to_float(latest.get("close"))
    float_share = _to_float(latest.get("float_share")) or (_to_float(basic.float_share) if basic else None)
    # Tushare float_share 通常为万股；估算流通市值 = 万股 * 10000 * 元。
    float_market_cap_yuan = close * float_share * 10000 if close is not None and float_share is not None else None
    latest_amount_yuan = _to_float(latest.get("amount"))
    if latest_amount_yuan is not None:
        # daily_quote.amount 在系统内沿用行情源原始口径，多数为千元；仅作为市场活跃度近似值。
        latest_amount_yuan = latest_amount_yuan * 1000

    business = _fetch_external_fundamental(ts_code, basic.name if basic else None, mode)
    has_financial = bool(
        business.get("latest_financial_metrics")
        or business.get("latest_financial_abstract")
        or business.get("financial_rows")
    )
    available_fields = []
    for key, value in (
        ("industry", basic.industry if basic else None),
        ("area", basic.area if basic else None),
        ("market", basic.market if basic else None),
        ("list_date", basic.list_date if basic else None),
        ("float_share", float_share),
        ("turnover_rate", latest.get("turnover_rate")),
        ("financial_report", "yes" if has_financial else None),
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
        if key != "financial_report" or not has_financial
    ]

    return {
        "available": bool(available_fields),
        "available_fields": available_fields,
        "missing_fields": missing_fields,
        "business": business,
        "related_concepts": related_concepts,
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
        "limitations": "深度分析会尝试补充主营业务、主营构成和最新财务指标；若外部源不可用，基本面结论只能基于基础画像和流动性判断。",
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

    official_context = news.get("official_context") if isinstance(news.get("official_context"), dict) else {}
    has_official_context = bool(
        official_context.get("verified_facts")
        or official_context.get("announcements")
        or official_context.get("market_news")
    )
    if news.get("items") or has_official_context:
        score += 20
        if news.get("order_signals"):
            score += 5
    else:
        warnings.append("近30日暂无系统内消息面记录")

    if has_official_context:
        score += 10
    else:
        warnings.append("缺少近期公告/财报新闻上下文，异动原因可信度受限")

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


def _cache_hit_without_refresh(db: Session, ts_code: str) -> StockAiAnalysis | None:
    """Return cached analysis only when local market data is already fresh enough."""
    latest = db.query(func.max(DailyQuote.trade_date)).filter(DailyQuote.ts_code == ts_code).scalar()
    target_latest = latest_daily_k_trade_date_str()
    if not latest or latest < target_latest:
        return None
    cached = _latest_stock_analysis(db, ts_code)
    if cached and cached.data_trade_date == latest:
        return cached
    return None


def _text_contains_order_signal(*parts: Any) -> bool:
    text = " ".join(str(part or "") for part in parts).lower()
    return any(keyword.lower() in text for keyword in ORDER_SIGNAL_KEYWORDS)


def _order_signal_keywords(*parts: Any) -> list[str]:
    text = " ".join(str(part or "") for part in parts).lower()
    return [keyword for keyword in ORDER_SIGNAL_KEYWORDS if keyword.lower() in text][:6]


def _value_signal_keywords(*parts: Any) -> list[str]:
    text = " ".join(str(part or "") for part in parts).lower()
    return [keyword for keyword in VALUE_SIGNAL_KEYWORDS if keyword.lower() in text][:8]


def _signal_rank(row: dict) -> tuple[int, int, int, str]:
    confidence_weight = {
        "official_announcement": 5,
        "major_financial_media": 4,
        "market_news": 3,
        "system_derived_opportunity": 3,
        "imported_source": 2,
        "raw_message_or_social": 1,
        "social_rumor": 1,
        "unknown_source": 0,
    }.get(str(row.get("source_confidence") or ""), 0)
    value_signal = bool(row.get("value_keywords"))
    order_signal = bool(row.get("order_signal"))
    heat_score = int(row.get("heat_score") or row.get("score") or 0)
    credibility_score = int(row.get("credibility_score") or 0)
    return (
        confidence_weight,
        1 if value_signal else 0,
        1 if order_signal else 0,
        heat_score + credibility_score,
        str(row.get("trade_date") or ""),
    )


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
    enabled = (os.getenv("AI_ANALYSIS_X_COLLECT_ENABLED") or "false").strip().lower() in {"1", "true", "yes", "on"}
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
        source_platforms = o.source_platforms or []
        confidence = _source_confidence(source_platforms=source_platforms)
        if confidence == "imported_source":
            confidence = "system_derived_opportunity"
        value_keywords = _value_signal_keywords(o.reason, catalysts, risks, o.theme)
        order_like = _text_contains_order_signal(o.reason, catalysts, risks, o.theme)
        row = {
            "type": "opportunity",
            "source_confidence": confidence,
            "source_note": _source_note(confidence),
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
            "value_signal": bool(value_keywords),
            "value_keywords": value_keywords,
            "topic_heat_score": topic.heat_score if topic else None,
            "topic_crowding_score": topic.crowding_score if topic else None,
            "topic_lifecycle_stage": topic.lifecycle_stage if topic else None,
            "source_platforms": source_platforms,
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
                "source_confidence": confidence,
                "source_note": row["source_note"],
            })

    for s in sources:
        confidence = _source_confidence(channel=s.channel, source_name=s.source_name)
        value_keywords = _value_signal_keywords(s.title, s.content, s.tags, s.theme)
        order_like = _text_contains_order_signal(s.title, s.content, s.tags, s.theme)
        row = {
            "type": "source",
            "source_confidence": confidence,
            "source_note": _source_note(confidence, s.channel, s.source_name),
            "trade_date": s.trade_date,
            "channel": s.channel,
            "source_name": s.source_name,
            "theme": s.theme,
            "title": s.title,
            "content": (s.content or "")[:180],
            "url": s.url,
            "sentiment": s.sentiment,
            "heat_score": s.heat_score,
            "credibility_score": s.credibility_score,
            "order_signal": order_like,
            "order_keywords": _order_signal_keywords(s.title, s.content, s.tags, s.theme),
            "value_signal": bool(value_keywords),
            "value_keywords": value_keywords,
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
                "source_confidence": confidence,
                "source_note": row["source_note"],
                "url": s.url,
            })

    heat_scores = [int(item.get("heat_score") or 0) for item in items if item.get("heat_score") is not None]
    credibility_scores = [int(item.get("credibility_score") or 0) for item in items if item.get("credibility_score") is not None]
    ranked_items = sorted(items, key=_signal_rank, reverse=True)
    value_signals = [
        {
            "type": item.get("type"),
            "trade_date": item.get("trade_date"),
            "theme": item.get("theme"),
            "title": item.get("title"),
            "reason": item.get("reason"),
            "content": item.get("content"),
            "matched_keywords": item.get("value_keywords"),
            "heat_score": item.get("heat_score") or item.get("score"),
            "credibility_score": item.get("credibility_score"),
            "source_confidence": item.get("source_confidence"),
            "source_note": item.get("source_note"),
            "url": item.get("url"),
        }
        for item in ranked_items
        if item.get("value_keywords")
    ][:8]
    return {
        "available": bool(items),
        "window_days": 45,
        "items": ranked_items[:12],
        "order_signals": order_signals[:8],
        "value_signals": value_signals,
        "value_signal_count": len([item for item in items if item.get("value_keywords")]),
        "order_signal_count": len(order_signals),
        "has_order_signal": bool(order_signals),
        "has_value_signal": bool(value_signals),
        "themes": sorted(themes.values(), key=lambda x: (x["max_heat_score"], x["count"]), reverse=True)[:6],
        "summary_metrics": {
            "message_count": len(items),
            "theme_count": len(themes),
            "avg_heat_score": round(sum(heat_scores) / len(heat_scores), 1) if heat_scores else None,
            "avg_credibility_score": round(sum(credibility_scores) / len(credibility_scores), 1) if credibility_scores else None,
            "latest_trade_date": max([str(item.get("trade_date") or "") for item in items], default=None),
        },
        "interpretation_hint": (
            "存在订单/产能/客户/收入等可锚定市值的线索，请优先核验金额、客户、交付节点、产能兑现和收入弹性。"
            if order_signals or value_signals
            else "近45日系统消息中未识别到订单/产能/客户/收入等高价值催化线索。"
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


def _concepts_from_news(news: dict, basic: StockBasic | None) -> list[str]:
    concepts: list[str] = []
    if basic and basic.industry:
        concepts.append(basic.industry)
    for item in news.get("themes") or []:
        theme = item.get("theme") if isinstance(item, dict) else None
        if theme and theme not in concepts:
            concepts.append(theme)
    for item in news.get("items") or []:
        theme = item.get("theme") if isinstance(item, dict) else None
        if theme and theme not in concepts:
            concepts.append(theme)
    return concepts[:10]


def _compact_dict(data: dict | None, keys: tuple[str, ...]) -> dict:
    if not isinstance(data, dict):
        return {}
    return {key: data.get(key) for key in keys if data.get(key) is not None}


def _compact_text(value: Any, limit: int = 120) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    return text[:limit]


def _compact_list(values: Any, limit: int = 3) -> list[Any]:
    return values[:limit] if isinstance(values, list) else []


def _extract_business_tags(business: dict) -> list[str]:
    tags: list[str] = []
    for row in business.get("business_description_rows") or []:
        for field in ("产品类型", "产品名称"):
            text = str(row.get(field) or "")
            for part in re.split(r"[、,，/；;]", text):
                item = part.strip()
                if item and item not in tags:
                    tags.append(item[:30])
    for row in business.get("business_composition") or []:
        item = str(row.get("主营构成") or "").strip()
        if item and item not in tags:
            tags.append(item[:30])
    return tags[:8]


def _business_scope_hint(text: Any) -> str | None:
    raw = str(text or "").strip()
    if not raw:
        return None
    keywords = ("算力", "云计算", "互联网数据", "人工智能", "精密", "结构件", "电子元器件", "模具")
    hits: list[str] = []
    for part in re.split(r"[；;。]", raw):
        cleaned = part.strip()
        if cleaned and any(keyword in cleaned for keyword in keywords):
            hits.append(cleaned[:80])
        if len(hits) >= 3:
            break
    return "；".join(hits)[:180] if hits else None


def _compact_business_composition(business: dict, limit: int = 5) -> list[dict]:
    rows = business.get("business_composition") or []
    compact_rows: list[dict] = []
    for row in rows:
        name = row.get("主营构成")
        if not name:
            continue
        compact_rows.append({
            "report_date": row.get("报告日期"),
            "category_type": row.get("分类类型"),
            "segment": name,
            "revenue_yi": _format_yi(row.get("主营收入")),
            "revenue_pct": _round((_to_float(row.get("收入比例")) or 0) * 100),
            "profit_pct": _round((_to_float(row.get("利润比例")) or 0) * 100),
            "gross_margin_pct": _round((_to_float(row.get("毛利率")) or 0) * 100),
        })
    compact_rows = sorted(
        compact_rows,
        key=lambda item: (_to_float(item.get("revenue_pct")) or 0, _to_float(item.get("profit_pct")) or 0),
        reverse=True,
    )
    return _dedupe_rows(compact_rows, ("category_type", "segment"), limit)


def _compact_business_profile(business: dict, related_concepts: Any) -> dict:
    description_rows = business.get("business_description_rows") or []
    first_desc = description_rows[0] if description_rows else {}
    return {
        "main_business": _compact_text(business.get("main_business") or first_desc.get("主营业务"), 180),
        "product_types": _compact_text(first_desc.get("产品类型") or first_desc.get("产品名称"), 140),
        "business_scope_hint": _business_scope_hint(first_desc.get("经营范围")),
        "business_tags": _extract_business_tags(business),
        "top_segments": _compact_business_composition(business, limit=5),
        "related_concepts": _compact_list(related_concepts, 6),
    }


def _compact_major_change_signals(official_context: dict, limit: int = 4) -> list[dict]:
    rows = []
    rows.extend(official_context.get("announcements") or [])
    rows.extend(official_context.get("market_news") or [])
    signals: list[dict] = []
    for row in rows:
        text = _record_text(row)
        if not _contains_any_keyword(text, MAJOR_CHANGE_KEYWORDS):
            continue
        signals.append({
            "date": row.get("date") or row.get("published_at"),
            "title": _compact_text(row.get("title"), 90),
            "source_confidence": row.get("source_confidence"),
            "source_note": row.get("source_note"),
        })
    return _dedupe_rows(signals, ("date", "title"), limit)


def _compact_context_signals(official_context: dict, keywords: tuple[str, ...], limit: int = 4) -> list[dict]:
    rows = []
    rows.extend(official_context.get("announcements") or [])
    rows.extend(official_context.get("market_news") or [])
    signals: list[dict] = []
    for row in rows:
        text = _record_text(row)
        if not _contains_any_keyword(text, keywords):
            continue
        signals.append({
            "date": row.get("date") or row.get("published_at"),
            "title": _compact_text(row.get("title"), 90),
            "summary": _compact_text(row.get("summary"), 110),
            "source_confidence": row.get("source_confidence"),
            "source_note": row.get("source_note"),
        })
    return _dedupe_rows(signals, ("date", "title"), limit)


def _dedupe_rows(rows: list[dict], key_fields: tuple[str, ...], limit: int) -> list[dict]:
    out: list[dict] = []
    seen: set[tuple[Any, ...]] = set()
    for row in rows:
        key = tuple(row.get(field) for field in key_fields)
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
        if len(out) >= limit:
            break
    return out


def _computed_technical_score(technical: dict, market: dict) -> dict:
    score = 50
    evidence: list[str] = []
    risk_flags: list[str] = []
    position = _to_float(technical.get("position_20d"))
    rsi = _to_float(technical.get("rsi14"))
    volume_ratio = _to_float(technical.get("volume_ratio_5d"))
    close = _to_float(market.get("close"))
    ma5 = _to_float(technical.get("ma5"))
    ma10 = _to_float(technical.get("ma10"))
    ma20 = _to_float(technical.get("ma20"))

    if close and ma5 and ma10 and ma20 and close > ma5 > ma10 > ma20:
        score += 18
        evidence.append("收盘价站上 MA5/10/20 且均线多头")
    if position is not None:
        if position >= 90:
            score += 8
            risk_flags.append("20日位置接近高位")
        elif position <= 25:
            score -= 8
            risk_flags.append("20日位置偏低")
    if rsi is not None:
        if rsi >= 80:
            score -= 12
            risk_flags.append("RSI 超买")
        elif rsi >= 65:
            score += 6
            evidence.append("RSI 偏强")
        elif rsi <= 35:
            score -= 8
            risk_flags.append("RSI 偏弱")
    if volume_ratio is not None:
        if volume_ratio >= 1.5:
            score += 8
            evidence.append("近5日放量")
        elif volume_ratio <= 0.75:
            score -= 6
            risk_flags.append("近5日缩量")

    return {
        "score": _clip_int(score, 0, 100, 50),
        "evidence": evidence[:4],
        "risk_flags": risk_flags[:4],
    }


def _computed_fundamental_score(fundamental: dict) -> dict:
    facts = (
        ((fundamental.get("business") or {}).get("official_context") or {})
        .get("verified_facts", {})
        .get("latest_financial_period", {})
    )
    balance = (
        ((fundamental.get("business") or {}).get("official_context") or {})
        .get("verified_facts", {})
        .get("latest_balance_sheet", {})
    )
    score = 45
    evidence: list[str] = []
    risk_flags: list[str] = []

    revenue_yoy = _to_float(facts.get("revenue_yoy_pct"))
    profit_yoy = _to_float(facts.get("net_profit_yoy_pct"))
    cash_yoy = _to_float(facts.get("operating_cash_flow_yoy_pct"))
    gross_margin = _to_float(facts.get("gross_margin_pct"))
    debt_ratio = _to_float(facts.get("debt_ratio_pct") or balance.get("debt_ratio_est_pct"))
    contract_liab = _to_float(balance.get("contract_liabilities_yi"))
    prev_contract_liab = _to_float(balance.get("contract_liabilities_prev_yi"))

    if revenue_yoy is not None:
        score += 10 if revenue_yoy >= 30 else 4 if revenue_yoy > 0 else -8
        evidence.append(f"营收同比 {revenue_yoy}%")
    if profit_yoy is not None:
        score += 18 if profit_yoy >= 100 else 10 if profit_yoy >= 30 else 4 if profit_yoy > 0 else -12
        evidence.append(f"归母净利同比 {profit_yoy}%")
    if cash_yoy is not None:
        score += 8 if cash_yoy > 0 else -8
        evidence.append(f"经营现金流同比 {cash_yoy}%")
    if gross_margin is not None and gross_margin >= 35:
        score += 6
        evidence.append(f"毛利率 {gross_margin}%")
    if debt_ratio is not None and debt_ratio >= 70:
        score -= 10
        risk_flags.append(f"资产负债率偏高 {debt_ratio}%")
    if contract_liab is not None and prev_contract_liab is not None and contract_liab > prev_contract_liab * 3:
        score += 6
        evidence.append(f"合同负债 {prev_contract_liab}亿升至 {contract_liab}亿")

    return {
        "score": _clip_int(score, 0, 100, 50),
        "evidence": evidence[:5],
        "risk_flags": risk_flags[:4],
    }


def _computed_news_score(news: dict) -> dict:
    official_context = news.get("official_context") if isinstance(news.get("official_context"), dict) else {}
    official_count = len(official_context.get("announcements") or [])
    media_count = len(official_context.get("market_news") or [])
    verification_risk_count = len(_compact_context_signals(official_context, NEGATIVE_VERIFICATION_KEYWORDS, limit=5))
    value_count = int(news.get("value_signal_count") or 0)
    order_count = int(news.get("order_signal_count") or 0)
    social_count = len([item for item in news.get("items") or [] if item.get("source_confidence") == "social_rumor"])

    score = 45 + min(20, official_count * 5) + min(15, media_count * 4) + min(10, value_count * 3) + min(8, order_count * 4)
    risk_flags: list[str] = []
    if verification_risk_count:
        score -= min(16, verification_risk_count * 8)
        risk_flags.append(f"存在 {verification_risk_count} 条官方/媒体反证或未量产类提示")
    if social_count and not official_count and not media_count:
        score -= 12
        risk_flags.append("消息主要来自 X/社媒小作文，缺少公告或大型媒体验证")
    if social_count:
        risk_flags.append(f"含 {social_count} 条社媒线索，需标注未验证")
    return {
        "score": _clip_int(score, 0, 100, 50),
        "evidence": [
            f"公告/财报线索 {official_count} 条",
            f"大型/财经媒体线索 {media_count} 条",
            f"价值催化线索 {value_count} 条",
        ],
        "risk_flags": risk_flags[:4],
    }


def _compact_official_context(official_context: dict) -> dict:
    verified = official_context.get("verified_facts") if isinstance(official_context.get("verified_facts"), dict) else {}
    announcements = [
        {
            **_compact_dict(item, ("date", "title", "type", "source_confidence", "source_note")),
            "summary": _compact_text(item.get("summary"), 140),
        }
        for item in official_context.get("announcements") or []
    ]
    media = [
        {
            **_compact_dict(item, ("published_at", "title", "source", "source_confidence", "source_note")),
            "summary": _compact_text(item.get("summary"), 140),
        }
        for item in official_context.get("market_news") or []
    ]
    return {
        "verified_facts": {
            "latest_financial_period": _compact_dict(
                verified.get("latest_financial_period"),
                (
                    "period",
                    "compare_period",
                    "revenue_yi",
                    "revenue_yoy_pct",
                    "net_profit_yi",
                    "net_profit_yoy_pct",
                    "deduct_net_profit_yi",
                    "deduct_net_profit_yoy_pct",
                    "operating_cash_flow_yi",
                    "operating_cash_flow_yoy_pct",
                    "gross_margin_pct",
                    "debt_ratio_pct",
                ),
            ),
            "latest_balance_sheet": _compact_dict(
                verified.get("latest_balance_sheet"),
                (
                    "period",
                    "report_type",
                    "contract_liabilities_yi",
                    "contract_liabilities_prev_yi",
                    "contract_liabilities_qoq_pct",
                    "total_assets_yi",
                    "total_liabilities_yi",
                    "debt_ratio_est_pct",
                ),
            ),
        },
        "announcements": _dedupe_rows(announcements, ("date", "title"), 4),
        "major_media": _dedupe_rows(media, ("published_at", "title"), 4),
        "progress_signals": _compact_context_signals(official_context, PROGRESS_SIGNAL_KEYWORDS, limit=4),
        "verification_risks": _compact_context_signals(official_context, NEGATIVE_VERIFICATION_KEYWORDS, limit=4),
    }


def _compact_news(news: dict) -> dict:
    official_context = _compact_official_context(news.get("official_context") or {})
    value_signals = [
        {
            "trade_date": item.get("trade_date"),
            "theme": item.get("theme"),
            "title": _compact_text(item.get("title") or item.get("reason"), 80),
            "content": _compact_text(item.get("content"), 120),
            "matched_keywords": _compact_list(item.get("matched_keywords"), 5),
            "source_confidence": item.get("source_confidence"),
            "source_note": item.get("source_note"),
        }
        for item in news.get("value_signals") or []
    ]
    order_signals = [
        {
            "trade_date": item.get("trade_date"),
            "theme": item.get("theme"),
            "title": _compact_text(item.get("title") or item.get("reason"), 80),
            "matched_keywords": _compact_list(item.get("matched_keywords"), 5),
            "source_confidence": item.get("source_confidence"),
            "source_note": item.get("source_note"),
        }
        for item in news.get("order_signals") or []
    ]
    social_rumors = [
        {
            "trade_date": item.get("trade_date"),
            "theme": item.get("theme"),
            "title": _compact_text(item.get("title") or item.get("reason"), 80),
            "content": _compact_text(item.get("content"), 100),
            "source_note": item.get("source_note"),
        }
        for item in news.get("items") or []
        if item.get("source_confidence") == "social_rumor"
    ]
    return {
        "official_context": official_context,
        "top_value_signals": _dedupe_rows(value_signals, ("trade_date", "title", "theme"), 4),
        "top_order_signals": _dedupe_rows(order_signals, ("trade_date", "title", "theme"), 3),
        "social_rumors": _dedupe_rows(social_rumors, ("trade_date", "title", "theme"), 2),
        "summary_metrics": _compact_dict(
            news.get("summary_metrics"),
            ("message_count", "theme_count", "avg_heat_score", "avg_credibility_score", "latest_trade_date"),
        ),
        "x_collect_meta": _compact_dict(news.get("x_collect_meta"), ("attempted", "status", "raw_count", "created_count", "skipped_count")),
        "graph_context": _compact_graph_context(news.get("graph_context") or {}),
    }


def _compact_graph_context(graph_context: dict) -> dict:
    items = []
    for item in graph_context.get("items") or []:
        items.append(
            {
                "trade_date": item.get("trade_date"),
                "theme": item.get("theme"),
                "grade": item.get("grade"),
                "final_score": item.get("final_score"),
                "evidence_score": item.get("evidence_score"),
                "risk_score": item.get("risk_score"),
                "reason": _compact_text(item.get("reason"), 100),
                "path": item.get("path")[:4] if isinstance(item.get("path"), list) else [],
                "risks": _compact_list(item.get("risks"), 3),
            }
        )
    return {
        "candidate_count": graph_context.get("candidate_count") or 0,
        "items": items[:3],
        "source_policy": graph_context.get("source_policy"),
    }


def _build_llm_snapshot(snapshot: dict) -> dict:
    stock = snapshot.get("stock") or {}
    market = snapshot.get("market") or {}
    technical = snapshot.get("technical") or {}
    fundamental = snapshot.get("fundamental") or {}
    news = snapshot.get("news") or {}
    scale = fundamental.get("scale_liquidity") or {}
    profile = fundamental.get("profile") or {}

    technical_score = _computed_technical_score(technical, market)
    fundamental_score = _computed_fundamental_score(fundamental)
    news_score = _computed_news_score(news)
    risk_flags = []
    for row in (technical_score, fundamental_score, news_score):
        risk_flags.extend(row.get("risk_flags") or [])

    return {
        "stock": _compact_dict(stock, ("ts_code", "name", "industry", "area", "market", "list_date")),
        "market": _compact_dict(market, ("latest_trade_date", "close", "pct_chg", "turnover_rate", "amount")),
        "technical_facts": {
            **_compact_dict(
                technical,
                (
                    "ma5",
                    "ma10",
                    "ma20",
                    "macd_dif",
                    "macd_dea",
                    "macd_hist",
                    "rsi14",
                    "volume_ratio_5d",
                    "low_20d",
                    "high_20d",
                    "position_20d",
                    "support_levels",
                    "pressure_levels",
                ),
            ),
            "recent_bar_count": len(technical.get("recent_kline") or []),
        },
        "fundamental_facts": {
            "profile": _compact_dict(profile, ("industry", "area", "market", "list_date", "listed_years")),
            "scale_liquidity": _compact_dict(
                scale,
                (
                    "float_share_10k_shares",
                    "float_market_cap_yi_est",
                    "float_cap_bucket",
                    "turnover_rate",
                    "latest_amount_yi_est",
                ),
            ),
            "business_summary": {
                **_compact_business_profile(fundamental.get("business") or {}, fundamental.get("related_concepts")),
                "major_change_signals": _compact_major_change_signals(
                    ((fundamental.get("business") or {}).get("official_context") or {})
                ),
                "progress_signals": _compact_context_signals(
                    ((fundamental.get("business") or {}).get("official_context") or {}),
                    PROGRESS_SIGNAL_KEYWORDS,
                ),
                "verification_risks": _compact_context_signals(
                    ((fundamental.get("business") or {}).get("official_context") or {}),
                    NEGATIVE_VERIFICATION_KEYWORDS,
                ),
            },
            **_compact_official_context(((fundamental.get("business") or {}).get("official_context") or {}))["verified_facts"],
        },
        "news_facts": _compact_news(news),
        "user_context": {
            "pool_name": (snapshot.get("user_context") or {}).get("pool_name"),
            "note": _compact_text((snapshot.get("user_context") or {}).get("note"), 100),
            "trade_count": len((snapshot.get("user_context") or {}).get("trades") or []),
        },
        "computed_scores": {
            "technical": technical_score,
            "fundamental": fundamental_score,
            "news": news_score,
            "data_quality": snapshot.get("data_quality"),
        },
        "risk_flags": risk_flags[:8],
        "source_policy": "基本面仅使用财报/公告/正规财务接口；X/社媒仅作未验证小作文线索，必须注明 source_note。",
    }


def _build_snapshot(
    db: Session,
    ts_code: str,
    watch_stock_id: str | None = None,
    pool_id: str | None = None,
    mode: str = "deep",
) -> dict:
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
    news["graph_context"] = get_stock_graph_context(db, ts_code)
    fundamental = _build_fundamental_snapshot(
        basic,
        latest,
        latest_date,
        ts_code=ts_code,
        mode=mode,
        related_concepts=_concepts_from_news(news, basic),
    )
    news["official_context"] = (fundamental.get("business") or {}).get("official_context") or {}
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
    llm_snapshot = _build_llm_snapshot(snapshot)
    return ANALYSIS_PROMPT_TEMPLATE.format(
        disclaimer=DISCLAIMER,
        snapshot_json=json.dumps(llm_snapshot, ensure_ascii=False, separators=(",", ":")),
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
    if not force_refresh:
        cached = _cache_hit_without_refresh(db, ts_code)
        if cached:
            return _record_to_response(cached)

    snapshot = _build_snapshot(db, ts_code, watch_stock_id=watch_stock_id, pool_id=pool_id, mode=mode)
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
