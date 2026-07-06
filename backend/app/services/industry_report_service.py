from __future__ import annotations

import json
import re
from datetime import datetime
from statistics import mean

from sqlalchemy.orm import Session

from app.config import INDUSTRY_REPORT_LLM_ENABLED, INDUSTRY_REPORT_MODEL, INDUSTRY_REPORT_MODEL_PROVIDER
from app.models.message import (
    IndustryDailyReport,
    IndustryReportCandidate,
    MessageEntity,
    MessageEvidence,
    MessageRelation,
    MessageTopic,
)
from app.models.stock import StockBasic
from app.services.core_watch_service import toggle_core_watch_star
from app.services.llm_client import call_llm_model
from app.services.message_graph_service import find_paths, import_seed_graph
from app.services.message_service import today_yyyymmdd

PROMPT_VERSION = "1.0"
DEFAULT_START_ENTITIES = ["Rubin", "AI capex", "HBM", "AI算力", "人形机器人"]
REPORT_PROMPT = """你是A股产业链研究助手。请只基于输入 JSON 生成结构化日报。

硬性规则：
1. 只返回 JSON，不要 Markdown。
2. 不得承诺收益，不得输出确定买入/卖出。
3. 区分强证据、中证据、弱证据和风险观察。
4. 如果证据不足，必须明确写“待验证”。

输出格式：
{
  "headline": "今日主线：...",
  "summary": "不超过160字",
  "core_catalysts": ["..."],
  "industry_paths": [{"theme": "...", "path": ["A", "B"], "evidence_level": "strong|medium|weak"}],
  "candidate_summary": [{"ts_code": "...", "stock_name": "...", "grade": "strong|medium|weak|risk_watch", "reason": "..."}],
  "risk_flags": ["..."],
  "next_actions": ["..."]
}

输入 JSON：
{payload}
"""
UNSAFE_REPORT_TERMS = ("必涨", "稳赚", "确定买入", "强烈推荐买入", "无风险", "一定上涨")


def _clamp(value: float, low: int = 0, high: int = 100) -> int:
    return max(low, min(high, int(round(value))))


def _grade(final_score: float, evidence_score: int, risk_score: int) -> str:
    if risk_score >= 70:
        return "risk_watch"
    if final_score >= 78 and evidence_score >= 70:
        return "strong"
    if final_score >= 62:
        return "medium"
    return "weak"


def _topic_lookup(db: Session, trade_date: str) -> dict[str, MessageTopic]:
    rows = db.query(MessageTopic).filter(MessageTopic.trade_date == trade_date).all()
    return {row.theme: row for row in rows}


def _start_entities(db: Session, trade_date: str) -> list[str]:
    topics = (
        db.query(MessageTopic)
        .filter(MessageTopic.trade_date == trade_date)
        .order_by(MessageTopic.heat_score.desc(), MessageTopic.credibility_score.desc())
        .limit(5)
        .all()
    )
    names = [topic.theme for topic in topics]
    for item in DEFAULT_START_ENTITIES:
        if item not in names:
            names.append(item)
    return names


def _stock_business_relations(db: Session) -> list[tuple[MessageEntity, MessageEntity, MessageRelation]]:
    result: list[tuple[MessageEntity, MessageEntity, MessageRelation]] = []
    relations = db.query(MessageRelation).filter(MessageRelation.relation_type == "maps_to", MessageRelation.status == "active").all()
    for relation in relations:
        stock = db.query(MessageEntity).filter(MessageEntity.id == relation.source_entity_id, MessageEntity.entity_type == "stock").first()
        if not stock:
            continue
        business = db.query(MessageEntity).filter(MessageEntity.id == relation.target_entity_id).first()
        if business:
            result.append((stock, business, relation))
    return result


def _message_evidence_for_candidate(db: Session, trade_date: str, ts_code: str | None, theme: str) -> list[MessageEvidence]:
    if not ts_code:
        return []
    rows = (
        db.query(MessageEvidence)
        .filter(
            MessageEvidence.trade_date == trade_date,
            MessageEvidence.status == "active",
            MessageEvidence.ts_code == ts_code,
        )
        .order_by(MessageEvidence.confidence.desc(), MessageEvidence.credibility_score.desc())
        .limit(5)
        .all()
    )
    exact = [row for row in rows if row.theme == theme]
    return (exact or rows)[:3]


def _message_evidence_json(rows: list[MessageEvidence]) -> list[dict]:
    return [
        {
            "source": row.channel,
            "relation": "message_evidence",
            "target": row.ts_code or row.theme,
            "confidence": row.confidence,
            "evidence_id": row.id,
            "source_item_id": row.source_item_id,
            "theme": row.theme,
            "evidence_text": row.evidence_text,
            "stance": row.stance,
        }
        for row in rows
    ]


def _build_candidate_rows(db: Session, trade_date: str) -> list[dict]:
    topic_by_theme = _topic_lookup(db, trade_date)
    paths_by_end: dict[str, list] = {}
    for start in _start_entities(db, trade_date):
        for path in find_paths(db, start, max_depth=3):
            paths_by_end.setdefault(path.end, []).append(path)

    candidates: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for stock, business, stock_relation in _stock_business_relations(db):
        paths = paths_by_end.get(business.name) or []
        if not paths:
            continue
        best_path = sorted(paths, key=lambda item: (-item.score, item.depth))[0]
        theme = business.name if business.name in topic_by_theme else _infer_theme(best_path, business.name)
        key = (stock.ts_code or stock.name, theme)
        if key in seen:
            continue
        seen.add(key)

        topic = topic_by_theme.get(theme)
        path_score = _clamp((best_path.score * 0.75) + (stock_relation.confidence * 0.25))
        message_evidence_rows = _message_evidence_for_candidate(db, trade_date, stock.ts_code, theme)
        graph_evidence_score = _clamp(mean([step.confidence for step in best_path.steps] + [stock_relation.confidence]))
        message_evidence_score = (
            _clamp(mean([row.confidence for row in message_evidence_rows]))
            if message_evidence_rows
            else 0
        )
        evidence_score = (
            _clamp(graph_evidence_score * 0.65 + message_evidence_score * 0.35)
            if message_evidence_rows
            else graph_evidence_score
        )
        heat_score = topic.heat_score if topic else _clamp(55 + path_score * 0.25)
        crowding_score = topic.crowding_score if topic else 35
        risk_score = _clamp(30 + max(0, crowding_score - 65) * 0.6 + (10 if evidence_score < 65 else 0))
        resonance_score = 70 if topic else 45
        final_score = round(
            path_score * 0.30
            + evidence_score * 0.25
            + heat_score * 0.20
            + resonance_score * 0.15
            - crowding_score * 0.05
            - risk_score * 0.05,
            1,
        )
        grade = _grade(final_score, evidence_score, risk_score)
        stock_basic = db.query(StockBasic).filter(StockBasic.ts_code == stock.ts_code).first() if stock.ts_code else None
        path_json = [step.model_dump() for step in best_path.steps] + [
            {
                "source": business.name,
                "relation": stock_relation.relation_type,
                "target": stock.name,
                "confidence": stock_relation.confidence,
                "strength": stock_relation.strength,
            }
        ]
        evidence_json = [
            {
                "source": step.source,
                "relation": step.relation,
                "target": step.target,
                "confidence": step.confidence,
            }
            for step in best_path.steps
        ]
        evidence_json.append(
            {
                "source": business.name,
                "relation": stock_relation.relation_type,
                "target": stock.name,
                "confidence": stock_relation.confidence,
            }
        )
        evidence_json.extend(_message_evidence_json(message_evidence_rows))
        message_evidence_note = (
            f"，并匹配到 {len(message_evidence_rows)} 条当日舆情证据"
            if message_evidence_rows
            else ""
        )
        candidates.append(
            {
                "trade_date": trade_date,
                "ts_code": stock.ts_code,
                "stock_name": stock_basic.name if stock_basic else stock.name,
                "theme": theme,
                "path_json": path_json,
                "evidence_json": evidence_json,
                "path_score": path_score,
                "evidence_score": evidence_score,
                "heat_score": heat_score,
                "crowding_score": crowding_score,
                "risk_score": risk_score,
                "final_score": final_score,
                "grade": grade,
                "reason": f"{stock_basic.name if stock_basic else stock.name} 通过 {business.name} 映射到 {theme}，路径证据分 {evidence_score}{message_evidence_note}。",
                "risks": _candidate_risks(grade, evidence_score, crowding_score),
            }
        )
    return sorted(candidates, key=lambda row: (-row["final_score"], row["risk_score"], row["ts_code"]))[:20]


def _infer_theme(path, fallback: str) -> str:
    for step in path.steps:
        if step.source in {"AI算力", "NVIDIA产业链", "HBM与存储", "光模块", "铜连接", "PCB", "液冷", "AI电力", "AI服务器", "机器人"}:
            return step.source
        if step.target in {"AI算力", "NVIDIA产业链", "HBM与存储", "光模块", "铜连接", "PCB", "液冷", "AI电力", "AI服务器", "机器人"}:
            return step.target
    return fallback


def _candidate_risks(grade: str, evidence_score: int, crowding_score: int) -> list[str]:
    risks = ["仅作为研究候选，需等待买点雷达和人工复核"]
    if evidence_score < 70:
        risks.append("证据强度仍需公告或权威媒体进一步验证")
    if crowding_score >= 70:
        risks.append("题材拥挤度偏高，注意短线追高风险")
    if grade == "weak":
        risks.append("当前主要是产业链映射，不能视作确定业务增量")
    return risks


def _json_from_llm(text: str) -> dict:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.S)
        if not match:
            raise
        return json.loads(match.group(0))


def _rule_report_json(candidates: list[dict]) -> dict:
    return {
        "core_catalysts": sorted({row["theme"] for row in candidates})[:6],
        "candidate_count": len(candidates),
        "grade_counts": {
            grade: len([row for row in candidates if row["grade"] == grade])
            for grade in ["strong", "medium", "weak", "risk_watch"]
        },
        "risk_flags": sorted({risk for row in candidates for risk in row["risks"]})[:8],
        "next_actions": ["优先查看 strong/medium 候选", "加入观察池后等待买点雷达确认", "弱证据候选需补充公告或权威媒体证据"],
    }


def _build_llm_payload(trade_date: str, candidates: list[dict]) -> dict:
    return {
        "trade_date": trade_date,
        "candidates": [
            {
                "ts_code": row["ts_code"],
                "stock_name": row["stock_name"],
                "theme": row["theme"],
                "grade": row["grade"],
                "final_score": row["final_score"],
                "path_score": row["path_score"],
                "evidence_score": row["evidence_score"],
                "risk_score": row["risk_score"],
                "path": row["path_json"][:4],
                "risks": row["risks"][:4],
                "reason": row["reason"],
            }
            for row in candidates[:12]
        ],
        "source_policy": "候选仅用于研究观察，必须等待买点雷达与人工复核，不构成投资建议。",
    }


def _generate_llm_report_json(trade_date: str, candidates: list[dict]) -> tuple[dict, str | None]:
    prompt = REPORT_PROMPT.replace("{payload}", json.dumps(_build_llm_payload(trade_date, candidates), ensure_ascii=False))
    raw = call_llm_model(
        prompt,
        provider=INDUSTRY_REPORT_MODEL_PROVIDER,
        model=INDUSTRY_REPORT_MODEL,
        temperature=0.1,
    )
    data = _json_from_llm(raw)
    return _sanitize_llm_report_json(data, len(candidates)), raw


def _safe_text(value, limit: int = 200) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    for term in UNSAFE_REPORT_TERMS:
        text = text.replace(term, "待验证")
    return text[:limit]


def _safe_list(value, limit: int = 8) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        text = _safe_text(item, 80)
        if text and text not in result:
            result.append(text)
        if len(result) >= limit:
            break
    return result


def _sanitize_llm_report_json(data: dict, candidate_count: int) -> dict:
    if not isinstance(data, dict):
        raise ValueError("LLM report must be a JSON object")
    candidate_summary = []
    for item in data.get("candidate_summary") or []:
        if not isinstance(item, dict):
            continue
        candidate_summary.append(
            {
                "ts_code": _safe_text(item.get("ts_code"), 16),
                "stock_name": _safe_text(item.get("stock_name"), 32),
                "grade": _safe_text(item.get("grade"), 16),
                "reason": _safe_text(item.get("reason"), 120),
            }
        )
    industry_paths = []
    for item in data.get("industry_paths") or []:
        if not isinstance(item, dict):
            continue
        path = item.get("path")
        industry_paths.append(
            {
                "theme": _safe_text(item.get("theme"), 64),
                "path": _safe_list(path, 6),
                "evidence_level": _safe_text(item.get("evidence_level"), 16),
            }
        )
    return {
        "headline": _safe_text(data.get("headline"), 120),
        "summary": _safe_text(data.get("summary"), 220),
        "core_catalysts": _safe_list(data.get("core_catalysts"), 8),
        "industry_paths": industry_paths[:8],
        "candidate_summary": candidate_summary[:12],
        "risk_flags": _safe_list(data.get("risk_flags"), 8),
        "next_actions": _safe_list(data.get("next_actions"), 8),
        "candidate_count": candidate_count,
    }


def generate_industry_report(
    db: Session,
    trade_date: str | None = None,
    refresh_seeds: bool = True,
    use_llm: bool | None = None,
) -> IndustryDailyReport:
    resolved_date = trade_date or today_yyyymmdd()
    if refresh_seeds:
        import_seed_graph(db)

    candidates = _build_candidate_rows(db, resolved_date)
    top = candidates[0] if candidates else None
    headline = f"今日主线：{top['theme']}" if top else "暂无可归档的产业链主线"
    summary = (
        f"系统基于产业链种子图谱和当日消息热度生成 {len(candidates)} 个候选标的，所有候选仍需结合买点雷达确认。"
        if candidates
        else "当前图谱路径和消息数据不足，暂未生成候选标的。"
    )
    report_json = _rule_report_json(candidates)
    model_provider = "rules"
    model_name = "deterministic-graphrag-lite"
    error_message = None
    should_use_llm = INDUSTRY_REPORT_LLM_ENABLED if use_llm is None else use_llm
    if should_use_llm and candidates:
        try:
            llm_json, _raw = _generate_llm_report_json(resolved_date, candidates)
            report_json = {**report_json, **llm_json}
            headline = llm_json.get("headline") or headline
            summary = llm_json.get("summary") or summary
            model_provider = INDUSTRY_REPORT_MODEL_PROVIDER
            model_name = INDUSTRY_REPORT_MODEL
        except Exception as exc:
            error_message = f"LLM日报生成失败，已回退规则版：{str(exc)[:200]}"

    report = db.query(IndustryDailyReport).filter(IndustryDailyReport.trade_date == resolved_date).first()
    values = {
        "trade_date": resolved_date,
        "title": f"{resolved_date} 产业链机会日报",
        "headline": headline,
        "summary": summary,
        "report_json": report_json,
        "model_provider": model_provider,
        "model_name": model_name,
        "prompt_version": PROMPT_VERSION,
        "status": "success",
        "error_message": error_message,
    }
    if report:
        for key, value in values.items():
            setattr(report, key, value)
        db.query(IndustryReportCandidate).filter(IndustryReportCandidate.report_id == report.id).delete()
    else:
        report = IndustryDailyReport(**values)
        db.add(report)
        db.flush()

    for row in candidates:
        db.add(IndustryReportCandidate(report_id=report.id, **row))
    db.commit()
    db.refresh(report)
    return report


def get_industry_report(db: Session, trade_date: str | None = None) -> tuple[IndustryDailyReport | None, list[IndustryReportCandidate]]:
    resolved_date = trade_date or today_yyyymmdd()
    report = db.query(IndustryDailyReport).filter(IndustryDailyReport.trade_date == resolved_date).first()
    if not report:
        return None, []
    candidates = (
        db.query(IndustryReportCandidate)
        .filter(IndustryReportCandidate.report_id == report.id)
        .order_by(IndustryReportCandidate.final_score.desc(), IndustryReportCandidate.risk_score.asc())
        .all()
    )
    return report, candidates


def add_candidate_to_core_watch(db: Session, candidate_id: str) -> dict:
    candidate = db.query(IndustryReportCandidate).filter(IndustryReportCandidate.id == candidate_id).first()
    if not candidate:
        raise ValueError("candidate not found")
    return toggle_core_watch_star(db, candidate.ts_code, True, source="industry_report")


def get_stock_graph_context(db: Session, ts_code: str, limit: int = 3) -> dict:
    rows = (
        db.query(IndustryReportCandidate, IndustryDailyReport)
        .join(IndustryDailyReport, IndustryReportCandidate.report_id == IndustryDailyReport.id)
        .filter(IndustryReportCandidate.ts_code == ts_code)
        .order_by(IndustryReportCandidate.trade_date.desc(), IndustryReportCandidate.final_score.desc())
        .limit(limit)
        .all()
    )
    candidates = []
    for candidate, report in rows:
        candidates.append(
            {
                "trade_date": candidate.trade_date,
                "report_headline": report.headline,
                "theme": candidate.theme,
                "grade": candidate.grade,
                "final_score": candidate.final_score,
                "path_score": candidate.path_score,
                "evidence_score": candidate.evidence_score,
                "risk_score": candidate.risk_score,
                "path": (candidate.path_json or [])[:5],
                "risks": candidate.risks or [],
                "reason": candidate.reason,
            }
        )
    return {
        "candidate_count": len(candidates),
        "items": candidates,
        "source_policy": "产业链日报候选仅代表图谱映射和当日证据强度，不构成交易建议。",
    }
