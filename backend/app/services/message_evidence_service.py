from __future__ import annotations

import json
import hashlib
import re
from datetime import datetime
from time import perf_counter

from sqlalchemy.orm import Session

from app.config import MESSAGE_AGENT_MODEL, MESSAGE_AGENT_MODEL_PROVIDER
from app.exceptions import AppError
from app.models.message import (
    MessageAgentRun,
    MessageEvidence,
    MessageOpportunity,
    MessageOpportunityEvidence,
    MessageSourceItem,
)
from app.schemas.message import MessageAgentRunResult
from app.schemas.message import MessageAgentDailyCandidate, MessageAgentDailyOut
from app.services.core_watch_service import toggle_core_watch_star
from app.services.llm_client import call_llm_model

RULE_EVIDENCE_AGENT = "rule_evidence_cleaner"
RULE_EVIDENCE_VERSION = "1.0"
LLM_EVIDENCE_AGENT = "llm_evidence_cleaner"
LLM_EVIDENCE_VERSION = "1.0"
UNSAFE_TERMS = ("必涨", "稳赚", "确定买入", "强烈推荐买入", "无风险", "一定上涨")
LLM_EVIDENCE_PROMPT = """你是 A 股产业舆情证据清洗器。请只基于输入 JSON 提取证据，不要补充外部知识。

硬性规则：
1. 只返回 JSON，不要 Markdown。
2. 不得输出买入、卖出、确定上涨、稳赚、无风险等投资建议。
3. evidence.text 必须是输入 title/content 中存在或高度贴近的短片段。
4. 如果证据不足，confidence 不得高于 50，stance 使用 neutral 或 risk。
5. 只做研究候选证据，不做交易决策。

返回格式：
{
  "is_relevant": true,
  "quality_score": 0-100,
  "theme": "题材或 null",
  "ts_code": "股票代码或 null",
  "entities": [{"type": "company|stock|theme|product|technology|event", "name": "...", "confidence": 0-100}],
  "evidence": [
    {"text": "证据片段", "stance": "support|risk|contradiction|neutral", "confidence": 0-100}
  ],
  "risk_flags": ["single_source|weak_mapping|spam|insufficient_evidence"]
}

输入 JSON：
{payload}
"""
DAILY_REPORT_PROMPT_VERSION = "1.0"
DAILY_REPORT_AGENT = "message_daily_reporter"
DAILY_REPORT_PROMPT = """你是 A 股舆情研究日报助手。请只基于输入 JSON 生成日报摘要。

硬性规则：
1. 只返回 JSON，不要 Markdown。
2. 不得承诺收益，不得输出确定买入/卖出。
3. 如果证据不足，必须写“待验证”。
4. next_actions 只能是观察、补证、加入观察池等待买点雷达确认、风险观察。

返回格式：
{
  "headline": "...",
  "summary": "...",
  "risk_flags": ["..."],
  "next_actions": ["..."]
}

输入 JSON：
{payload}
"""


def _clamp_score(value: int | float) -> int:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = 0
    return max(0, min(100, int(round(numeric))))


def _short_text(item: MessageSourceItem, limit: int = 160) -> str:
    text = (item.title or item.content or "").strip()
    if not text:
        text = item.content.strip()
    return text[:limit]


def _safe_text(value, limit: int = 240) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    for term in UNSAFE_TERMS:
        text = text.replace(term, "待验证")
    return text[:limit]


def _json_from_llm_text(text: str) -> dict:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.S)
        if not match:
            raise
        return json.loads(match.group(0))


def _source_payload(item: MessageSourceItem) -> dict:
    return {
        "id": item.id,
        "trade_date": item.trade_date,
        "channel": item.channel,
        "source_name": item.source_name,
        "title": item.title,
        "content": item.content,
        "theme": item.theme,
        "ts_code": item.ts_code,
        "stock_name": item.stock_name,
        "tags": item.tags or [],
        "sentiment": item.sentiment,
        "heat_score": item.heat_score,
        "credibility_score": item.credibility_score,
        "url": item.url,
    }


def _quality_from_item(item: MessageSourceItem) -> int:
    quality_tags = [tag for tag in (item.tags or []) if isinstance(tag, str) and tag.startswith("quality:")]
    if quality_tags:
        try:
            return _clamp_score(int(quality_tags[0].split(":", 1)[1]))
        except (IndexError, ValueError):
            pass
    text = " ".join((item.title or "", item.content or "")).strip()
    if len(text) < 24:
        return 35
    if len(text) >= 160:
        return 72
    return 60


def _stance_from_item(item: MessageSourceItem) -> str:
    if item.sentiment == "negative":
        return "risk"
    if item.sentiment == "positive":
        return "support"
    return "support" if item.ts_code or item.theme else "neutral"


def _evidence_raw_json(item: MessageSourceItem, quality_score: int) -> dict:
    return {
        "source_name": item.source_name,
        "external_id": item.external_id,
        "url": item.url,
        "tags": item.tags or [],
        "quality_score": quality_score,
        "method": "source_item_rule_projection",
    }


def upsert_rule_evidence_for_source_item(db: Session, item: MessageSourceItem) -> tuple[MessageEvidence, bool]:
    stance = _stance_from_item(item)
    existing = (
        db.query(MessageEvidence)
        .filter(
            MessageEvidence.source_item_id == item.id,
            MessageEvidence.extractor_name == RULE_EVIDENCE_AGENT,
            MessageEvidence.extractor_version == RULE_EVIDENCE_VERSION,
            MessageEvidence.stance == stance,
        )
        .first()
    )
    quality_score = _quality_from_item(item)
    evidence_text = _short_text(item)
    values = {
        "source_item_id": item.id,
        "trade_date": item.trade_date,
        "channel": item.channel,
        "theme": item.theme,
        "ts_code": item.ts_code,
        "evidence_text": evidence_text,
        "stance": stance,
        "quality_score": quality_score,
        "credibility_score": item.credibility_score,
        "confidence": _clamp_score((quality_score * 0.45) + (item.credibility_score * 0.55)),
        "extraction_method": "rule",
        "extractor_name": RULE_EVIDENCE_AGENT,
        "extractor_version": RULE_EVIDENCE_VERSION,
        "raw_json": _evidence_raw_json(item, quality_score),
        "status": "active" if item.status != "ignored" and quality_score >= 35 else "ignored",
    }
    if existing:
        for key, value in values.items():
            setattr(existing, key, value)
        return existing, False

    evidence = MessageEvidence(**values)
    db.add(evidence)
    db.flush()
    return evidence, True


def _sanitize_llm_evidence_data(data: dict, item: MessageSourceItem) -> dict:
    evidence_items = []
    for evidence in data.get("evidence") or []:
        if not isinstance(evidence, dict):
            continue
        text = _safe_text(evidence.get("text"), 240)
        if not text:
            continue
        stance = str(evidence.get("stance") or "neutral").strip()
        if stance not in {"support", "risk", "contradiction", "neutral"}:
            stance = "neutral"
        evidence_items.append(
            {
                "text": text,
                "stance": stance,
                "confidence": _clamp_score(evidence.get("confidence") or 50),
            }
        )
    if not evidence_items:
        evidence_items.append(
            {
                "text": _short_text(item),
                "stance": _stance_from_item(item),
                "confidence": _clamp_score(item.credibility_score),
            }
        )
    return {
        "is_relevant": bool(data.get("is_relevant", True)),
        "quality_score": _clamp_score(data.get("quality_score") or _quality_from_item(item)),
        "theme": _safe_text(data.get("theme"), 64) or item.theme,
        "ts_code": _safe_text(data.get("ts_code"), 16) or item.ts_code,
        "entities": data.get("entities") if isinstance(data.get("entities"), list) else [],
        "evidence": evidence_items[:3],
        "risk_flags": data.get("risk_flags") if isinstance(data.get("risk_flags"), list) else [],
    }


def upsert_llm_evidence_for_source_item(
    db: Session,
    item: MessageSourceItem,
    *,
    provider: str,
    model: str,
) -> tuple[list[MessageEvidence], int, int]:
    prompt = LLM_EVIDENCE_PROMPT.replace("{payload}", json.dumps(_source_payload(item), ensure_ascii=False))
    raw = call_llm_model(prompt, provider=provider, model=model, temperature=0.1)
    data = _sanitize_llm_evidence_data(_json_from_llm_text(raw), item)
    if not data["is_relevant"]:
        return [], 0, 0

    created_count = 0
    updated_count = 0
    rows: list[MessageEvidence] = []
    for evidence_item in data["evidence"]:
        stance = evidence_item["stance"]
        existing = (
            db.query(MessageEvidence)
            .filter(
                MessageEvidence.source_item_id == item.id,
                MessageEvidence.extractor_name == LLM_EVIDENCE_AGENT,
                MessageEvidence.extractor_version == LLM_EVIDENCE_VERSION,
                MessageEvidence.stance == stance,
            )
            .first()
        )
        quality_score = data["quality_score"]
        values = {
            "source_item_id": item.id,
            "trade_date": item.trade_date,
            "channel": item.channel,
            "theme": data["theme"],
            "ts_code": data["ts_code"],
            "evidence_text": evidence_item["text"],
            "stance": stance,
            "quality_score": quality_score,
            "credibility_score": item.credibility_score,
            "confidence": evidence_item["confidence"],
            "extraction_method": "llm",
            "extractor_name": LLM_EVIDENCE_AGENT,
            "extractor_version": LLM_EVIDENCE_VERSION,
            "raw_json": {
                "provider": provider,
                "model": model,
                "entities": data["entities"],
                "risk_flags": data["risk_flags"],
                "source_url": item.url,
            },
            "status": "active" if quality_score >= 35 else "ignored",
        }
        if existing:
            for key, value in values.items():
                setattr(existing, key, value)
            rows.append(existing)
            updated_count += 1
            continue
        row = MessageEvidence(**values)
        db.add(row)
        db.flush()
        rows.append(row)
        created_count += 1
    return rows, created_count, updated_count


def ensure_rule_evidence_for_source_items(db: Session, items: list[MessageSourceItem]) -> list[MessageEvidence]:
    evidence_rows: list[MessageEvidence] = []
    for item in items:
        evidence, _created = upsert_rule_evidence_for_source_item(db, item)
        evidence_rows.append(evidence)
    return evidence_rows


def run_rule_evidence_cleaner(
    db: Session,
    *,
    trade_date: str | None = None,
    source_item_ids: list[str] | None = None,
    dry_run: bool = False,
) -> MessageAgentRunResult:
    started_at = datetime.utcnow()
    elapsed_start = perf_counter()
    query = db.query(MessageSourceItem)
    if source_item_ids:
        query = query.filter(MessageSourceItem.id.in_(source_item_ids))
    elif trade_date:
        query = query.filter(MessageSourceItem.trade_date == trade_date)
    else:
        raise AppError(
            code=5107,
            message="缺少 Agent 输入范围",
            detail="请提供 trade_date 或 source_item_ids。",
            status_code=400,
        )
    items = query.filter(MessageSourceItem.status != "ignored").all()
    existing_keys = {
        (
            row.source_item_id,
            row.extractor_name,
            row.extractor_version,
            row.stance,
        )
        for row in db.query(MessageEvidence)
        .filter(MessageEvidence.source_item_id.in_([item.id for item in items]))
        .all()
    } if items else set()
    candidate_keys = []
    for item in items:
        candidate_keys.append((item.id, RULE_EVIDENCE_AGENT, RULE_EVIDENCE_VERSION, _stance_from_item(item)))

    if dry_run:
        created_count = len([key for key in candidate_keys if key not in existing_keys])
        updated_count = len(candidate_keys) - created_count
        return MessageAgentRunResult(
            agent_name=RULE_EVIDENCE_AGENT,
            trade_date=trade_date,
            dry_run=True,
            source_item_count=len(items),
            created_count=created_count,
            updated_count=updated_count,
            skipped_count=0,
            evidence_count=len(candidate_keys),
            run=None,
        )

    created_count = 0
    updated_count = 0
    evidence_rows: list[MessageEvidence] = []
    for item in items:
        evidence, created = upsert_rule_evidence_for_source_item(db, item)
        evidence_rows.append(evidence)
        if created:
            created_count += 1
        else:
            updated_count += 1
    run = create_agent_run(
        db,
        agent_name=RULE_EVIDENCE_AGENT,
        agent_version=RULE_EVIDENCE_VERSION,
        trade_date=trade_date,
        input_ref_type="source_item_batch" if not source_item_ids else "source_item_ids",
        input_ref_id=",".join(source_item_ids or []),
        output_json={
            "source_item_count": len(items),
            "created_count": created_count,
            "updated_count": updated_count,
            "skipped_count": 0,
            "evidence_count": len(evidence_rows),
        },
        started_at=started_at,
        finished_at=datetime.utcnow(),
        duration_ms=int((perf_counter() - elapsed_start) * 1000),
    )
    db.commit()
    db.refresh(run)
    return MessageAgentRunResult(
        agent_name=RULE_EVIDENCE_AGENT,
        trade_date=trade_date,
        dry_run=False,
        source_item_count=len(items),
        created_count=created_count,
        updated_count=updated_count,
        skipped_count=0,
        evidence_count=len(evidence_rows),
        fallback_count=0,
        error_count=0,
        run=run,
    )


def run_llm_evidence_cleaner(
    db: Session,
    *,
    trade_date: str | None = None,
    source_item_ids: list[str] | None = None,
    limit: int = 20,
    provider: str | None = None,
    model: str | None = None,
    dry_run: bool = False,
) -> MessageAgentRunResult:
    resolved_provider = provider or MESSAGE_AGENT_MODEL_PROVIDER
    resolved_model = model or MESSAGE_AGENT_MODEL
    started_at = datetime.utcnow()
    elapsed_start = perf_counter()
    query = db.query(MessageSourceItem)
    if source_item_ids:
        query = query.filter(MessageSourceItem.id.in_(source_item_ids))
    elif trade_date:
        query = query.filter(MessageSourceItem.trade_date == trade_date)
    else:
        raise AppError(
            code=5107,
            message="缺少 Agent 输入范围",
            detail="请提供 trade_date 或 source_item_ids。",
            status_code=400,
        )
    items = (
        query.filter(MessageSourceItem.status != "ignored")
        .order_by(MessageSourceItem.heat_score.desc(), MessageSourceItem.captured_at.desc())
        .limit(limit)
        .all()
    )
    if dry_run:
        return MessageAgentRunResult(
            agent_name=LLM_EVIDENCE_AGENT,
            trade_date=trade_date,
            dry_run=True,
            source_item_count=len(items),
            created_count=0,
            updated_count=0,
            skipped_count=0,
            evidence_count=0,
            fallback_count=0,
            error_count=0,
            run=None,
        )

    created_count = 0
    updated_count = 0
    fallback_count = 0
    error_count = 0
    evidence_count = 0
    for item in items:
        try:
            rows, created, updated = upsert_llm_evidence_for_source_item(
                db,
                item,
                provider=resolved_provider,
                model=resolved_model,
            )
            evidence_count += len(rows)
            created_count += created
            updated_count += updated
        except Exception as exc:
            db.rollback()
            error_count += 1
            fallback_count += 1
            evidence, created = upsert_rule_evidence_for_source_item(db, item)
            evidence_count += 1
            created_count += 1 if created else 0
            updated_count += 0 if created else 1
            create_agent_run(
                db,
                agent_name=LLM_EVIDENCE_AGENT,
                agent_version=LLM_EVIDENCE_VERSION,
                trade_date=item.trade_date,
                input_ref_type="source_item",
                input_ref_id=item.id,
                output_json={"fallback_evidence_id": evidence.id},
                model_provider=resolved_provider,
                model_name=resolved_model,
                status="failed",
                error_message=str(exc)[:300],
                started_at=started_at,
                finished_at=datetime.utcnow(),
                duration_ms=int((perf_counter() - elapsed_start) * 1000),
            )

    run = create_agent_run(
        db,
        agent_name=LLM_EVIDENCE_AGENT,
        agent_version=LLM_EVIDENCE_VERSION,
        trade_date=trade_date,
        input_ref_type="source_item_batch" if not source_item_ids else "source_item_ids",
        input_ref_id=",".join(source_item_ids or []),
        output_json={
            "source_item_count": len(items),
            "created_count": created_count,
            "updated_count": updated_count,
            "skipped_count": 0,
            "evidence_count": evidence_count,
            "fallback_count": fallback_count,
            "error_count": error_count,
        },
        model_provider=resolved_provider,
        model_name=resolved_model,
        status="success" if error_count == 0 else "success_with_fallback",
        started_at=started_at,
        finished_at=datetime.utcnow(),
        duration_ms=int((perf_counter() - elapsed_start) * 1000),
    )
    db.commit()
    db.refresh(run)
    return MessageAgentRunResult(
        agent_name=LLM_EVIDENCE_AGENT,
        trade_date=trade_date,
        dry_run=False,
        source_item_count=len(items),
        created_count=created_count,
        updated_count=updated_count,
        skipped_count=0,
        evidence_count=evidence_count,
        fallback_count=fallback_count,
        error_count=error_count,
        run=run,
    )


def link_opportunity_evidence(
    db: Session,
    opportunity: MessageOpportunity,
    evidence_rows: list[MessageEvidence],
    role: str = "support",
) -> list[MessageOpportunityEvidence]:
    links: list[MessageOpportunityEvidence] = []
    for evidence in evidence_rows:
        if evidence.status == "ignored":
            continue
        existing = (
            db.query(MessageOpportunityEvidence)
            .filter(
                MessageOpportunityEvidence.opportunity_id == opportunity.id,
                MessageOpportunityEvidence.evidence_id == evidence.id,
                MessageOpportunityEvidence.role == role,
            )
            .first()
        )
        weight = _clamp_score((evidence.confidence * 0.7) + (evidence.credibility_score * 0.3))
        if existing:
            existing.weight = weight
            links.append(existing)
            continue
        link = MessageOpportunityEvidence(
            opportunity_id=opportunity.id,
            evidence_id=evidence.id,
            role=role,
            weight=weight,
        )
        db.add(link)
        links.append(link)
    return links


def attach_evidence_source_items(db: Session, evidence_rows: list[MessageEvidence]) -> list[MessageEvidence]:
    source_ids = {row.source_item_id for row in evidence_rows}
    if not source_ids:
        return evidence_rows
    items = db.query(MessageSourceItem).filter(MessageSourceItem.id.in_(source_ids)).all()
    item_by_id = {item.id: item for item in items}
    for row in evidence_rows:
        row.source_item = item_by_id.get(row.source_item_id)
    return evidence_rows


def list_evidence(
    db: Session,
    *,
    trade_date: str | None = None,
    theme: str | None = None,
    ts_code: str | None = None,
    stance: str | None = None,
    status: str | None = None,
    source_item_id: str | None = None,
    limit: int = 100,
) -> list[MessageEvidence]:
    query = db.query(MessageEvidence)
    if trade_date:
        query = query.filter(MessageEvidence.trade_date == trade_date)
    if theme:
        query = query.filter(MessageEvidence.theme == theme)
    if ts_code:
        query = query.filter(MessageEvidence.ts_code == ts_code)
    if stance:
        query = query.filter(MessageEvidence.stance == stance)
    if status:
        query = query.filter(MessageEvidence.status == status)
    if source_item_id:
        query = query.filter(MessageEvidence.source_item_id == source_item_id)
    rows = (
        query.order_by(MessageEvidence.created_at.desc(), MessageEvidence.confidence.desc())
        .limit(limit)
        .all()
    )
    return attach_evidence_source_items(db, rows)


def get_opportunity_evidence(db: Session, opportunity_id: str) -> list[MessageOpportunityEvidence]:
    opportunity = db.query(MessageOpportunity).filter(MessageOpportunity.id == opportunity_id).first()
    if not opportunity:
        raise AppError(code=5105, message="机会不存在", detail=opportunity_id, status_code=404)
    links = (
        db.query(MessageOpportunityEvidence)
        .filter(MessageOpportunityEvidence.opportunity_id == opportunity_id)
        .order_by(MessageOpportunityEvidence.weight.desc(), MessageOpportunityEvidence.created_at.desc())
        .all()
    )
    evidence_ids = [link.evidence_id for link in links]
    evidence_rows = db.query(MessageEvidence).filter(MessageEvidence.id.in_(evidence_ids)).all() if evidence_ids else []
    attach_evidence_source_items(db, evidence_rows)
    evidence_by_id = {row.id: row for row in evidence_rows}
    for link in links:
        link.evidence = evidence_by_id.get(link.evidence_id)
    return links


def _get_opportunity_or_error(db: Session, opportunity_id: str) -> MessageOpportunity:
    opportunity = db.query(MessageOpportunity).filter(MessageOpportunity.id == opportunity_id).first()
    if not opportunity:
        raise AppError(code=5105, message="机会不存在", detail=opportunity_id, status_code=404)
    return opportunity


def review_opportunity(db: Session, opportunity_id: str, review_status: str, review_reason: str | None = None) -> MessageOpportunity:
    opportunity = _get_opportunity_or_error(db, opportunity_id)
    allowed = {"draft", "needs_review", "reviewed", "accepted", "dismissed", "archived"}
    if review_status not in allowed:
        raise AppError(
            code=5109,
            message="不支持的复核状态",
            detail=f"允许状态：{', '.join(sorted(allowed))}",
            status_code=400,
        )
    opportunity.review_status = review_status
    opportunity.review_reason = review_reason
    if review_status == "dismissed":
        opportunity.status = "dismissed"
        opportunity.dismissed_at = datetime.utcnow()
    db.commit()
    db.refresh(opportunity)
    return opportunity


def accept_opportunity(db: Session, opportunity_id: str) -> MessageOpportunity:
    opportunity = _get_opportunity_or_error(db, opportunity_id)
    if not opportunity.ts_code:
        raise AppError(code=5110, message="机会没有股票代码", detail=opportunity_id, status_code=400)
    toggle_core_watch_star(db, opportunity.ts_code, True, source="message_agent")
    opportunity.review_status = "accepted"
    opportunity.status = "active"
    opportunity.accepted_at = datetime.utcnow()
    db.commit()
    db.refresh(opportunity)
    return opportunity


def dismiss_opportunity(db: Session, opportunity_id: str, review_reason: str | None = None) -> MessageOpportunity:
    opportunity = _get_opportunity_or_error(db, opportunity_id)
    opportunity.review_status = "dismissed"
    opportunity.review_reason = review_reason
    opportunity.status = "dismissed"
    opportunity.dismissed_at = datetime.utcnow()
    db.commit()
    db.refresh(opportunity)
    return opportunity


def create_agent_run(
    db: Session,
    *,
    agent_name: str,
    agent_version: str = "1.0",
    trade_date: str | None = None,
    input_ref_type: str | None = None,
    input_ref_id: str | None = None,
    output_json: dict | None = None,
    status: str = "success",
    error_message: str | None = None,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
    duration_ms: int | None = None,
    model_provider: str = "rules",
    model_name: str = "deterministic-rule",
    prompt_version: str | None = None,
) -> MessageAgentRun:
    started = started_at or datetime.utcnow()
    finished = finished_at or datetime.utcnow()
    digest_source = f"{agent_name}|{agent_version}|{trade_date or ''}|{input_ref_type or ''}|{input_ref_id or ''}|{output_json or {}}"
    run = MessageAgentRun(
        agent_name=agent_name,
        agent_version=agent_version,
        trade_date=trade_date,
        input_ref_type=input_ref_type,
        input_ref_id=input_ref_id,
        input_digest=hashlib.sha256(digest_source.encode("utf-8")).hexdigest(),
        output_json=output_json or {},
        model_provider=model_provider,
        model_name=model_name,
        prompt_version=prompt_version,
        status=status,
        error_message=error_message,
        started_at=started,
        finished_at=finished,
        duration_ms=duration_ms if duration_ms is not None else int((finished - started).total_seconds() * 1000),
    )
    db.add(run)
    db.flush()
    return run


def record_rule_evidence_batch_run(
    db: Session,
    *,
    trade_date: str,
    source_item_count: int,
    evidence_count: int,
    started_at: datetime,
    elapsed_start: float,
) -> MessageAgentRun:
    finished = datetime.utcnow()
    return create_agent_run(
        db,
        agent_name=RULE_EVIDENCE_AGENT,
        agent_version=RULE_EVIDENCE_VERSION,
        trade_date=trade_date,
        input_ref_type="source_item_batch",
        output_json={
            "source_item_count": source_item_count,
            "evidence_count": evidence_count,
        },
        started_at=started_at,
        finished_at=finished,
        duration_ms=int((perf_counter() - elapsed_start) * 1000),
    )


def list_agent_runs(
    db: Session,
    *,
    agent_name: str | None = None,
    trade_date: str | None = None,
    status: str | None = None,
    limit: int = 50,
) -> list[MessageAgentRun]:
    query = db.query(MessageAgentRun)
    if agent_name:
        query = query.filter(MessageAgentRun.agent_name == agent_name)
    if trade_date:
        query = query.filter(MessageAgentRun.trade_date == trade_date)
    if status:
        query = query.filter(MessageAgentRun.status == status)
    return query.order_by(MessageAgentRun.started_at.desc()).limit(limit).all()


def get_agent_run(db: Session, run_id: str) -> MessageAgentRun:
    run = db.query(MessageAgentRun).filter(MessageAgentRun.id == run_id).first()
    if not run:
        raise AppError(code=5106, message="Agent 运行记录不存在", detail=run_id, status_code=404)
    return run


def _candidate_conclusion(opportunity: MessageOpportunity, evidence_count: int) -> str:
    target = opportunity.stock_name or opportunity.ts_code or "主题机会"
    if opportunity.review_status == "accepted":
        action = "已采纳，继续等待买点雷达确认"
    elif opportunity.risk_score >= 70:
        action = "风险偏高，先做风险观察"
    elif evidence_count <= 1:
        action = "证据仍偏单一，待验证"
    else:
        action = "可作为观察候选"
    return f"{target} 关联 {opportunity.theme}，证据{evidence_count}条，{action}。"


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


def _sanitize_daily_report_json(data: dict) -> dict:
    if not isinstance(data, dict):
        return {}
    return {
        "headline": _safe_text(data.get("headline"), 120),
        "summary": _safe_text(data.get("summary"), 220),
        "risk_flags": _safe_list(data.get("risk_flags"), 8),
        "next_actions": _safe_list(data.get("next_actions"), 8),
    }


def build_agent_daily_report(
    db: Session,
    *,
    trade_date: str,
    use_llm: bool = False,
    provider: str | None = None,
    model: str | None = None,
    limit: int = 5,
) -> MessageAgentDailyOut:
    opportunities = (
        db.query(MessageOpportunity)
        .filter(MessageOpportunity.trade_date == trade_date, MessageOpportunity.status == "active")
        .order_by(MessageOpportunity.opportunity_score.desc(), MessageOpportunity.evidence_score.desc())
        .limit(limit)
        .all()
    )
    evidence_rows = (
        db.query(MessageEvidence)
        .filter(MessageEvidence.trade_date == trade_date, MessageEvidence.status == "active")
        .all()
    )
    links = (
        db.query(MessageOpportunityEvidence)
        .filter(MessageOpportunityEvidence.opportunity_id.in_([opp.id for opp in opportunities]))
        .all()
        if opportunities
        else []
    )
    evidence_count_by_opp: dict[str, int] = {}
    for link in links:
        evidence_count_by_opp[link.opportunity_id] = evidence_count_by_opp.get(link.opportunity_id, 0) + 1

    candidates = [
        MessageAgentDailyCandidate(
            theme=opp.theme,
            ts_code=opp.ts_code,
            stock_name=opp.stock_name,
            opportunity_score=opp.opportunity_score,
            evidence_score=opp.evidence_score,
            risk_score=opp.risk_score,
            review_status=opp.review_status,
            evidence_count=evidence_count_by_opp.get(opp.id, 0),
            conclusion=_candidate_conclusion(opp, evidence_count_by_opp.get(opp.id, 0)),
        )
        for opp in opportunities
    ]
    themes = sorted({row.theme for row in evidence_rows if row.theme})
    risk_flags = []
    if any(candidate.risk_score >= 70 for candidate in candidates):
        risk_flags.append("存在高风险候选，适合风险观察")
    if any(candidate.evidence_count <= 1 for candidate in candidates):
        risk_flags.append("部分候选证据偏单一，待验证")
    if not evidence_rows:
        risk_flags.append("当前缺少可追溯证据")

    headline = f"今日证据主题：{themes[0]}" if themes else "暂无可追溯舆情证据"
    summary = (
        f"今日沉淀 {len(evidence_rows)} 条证据，形成 {len(candidates)} 个候选。所有候选仍需结合买点雷达与人工复核。"
        if evidence_rows
        else "当前日期尚无 agent 证据，请先运行证据清洗或导入原始消息。"
    )
    next_actions = ["优先查看有多条证据的候选", "弱证据候选需补充公告或权威媒体证据", "加入观察池后等待买点雷达确认"]
    model_provider = "rules"
    model_name = "deterministic-evidence-report"
    if use_llm and evidence_rows:
        resolved_provider = provider or MESSAGE_AGENT_MODEL_PROVIDER
        resolved_model = model or MESSAGE_AGENT_MODEL
        payload = {
            "trade_date": trade_date,
            "evidence_count": len(evidence_rows),
            "candidate_count": len(candidates),
            "themes": themes[:8],
            "candidates": [candidate.model_dump() for candidate in candidates],
            "risk_flags": risk_flags,
            "source_policy": "仅用于研究观察，不构成投资建议。",
        }
        try:
            raw = call_llm_model(
                DAILY_REPORT_PROMPT.replace("{payload}", json.dumps(payload, ensure_ascii=False)),
                provider=resolved_provider,
                model=resolved_model,
                temperature=0.1,
            )
            llm_json = _sanitize_daily_report_json(_json_from_llm_text(raw))
            headline = llm_json.get("headline") or headline
            summary = llm_json.get("summary") or summary
            risk_flags = llm_json.get("risk_flags") or risk_flags
            next_actions = llm_json.get("next_actions") or next_actions
            model_provider = resolved_provider
            model_name = resolved_model
        except Exception as exc:
            create_agent_run(
                db,
                agent_name=DAILY_REPORT_AGENT,
                agent_version=DAILY_REPORT_PROMPT_VERSION,
                trade_date=trade_date,
                output_json={"fallback": True},
                model_provider=resolved_provider,
                model_name=resolved_model,
                status="failed",
                error_message=str(exc)[:300],
            )
            db.commit()

    return MessageAgentDailyOut(
        trade_date=trade_date,
        generated_at=datetime.utcnow(),
        model_provider=model_provider,
        model_name=model_name,
        headline=headline,
        summary=summary,
        evidence_coverage={
            "evidence_count": len(evidence_rows),
            "candidate_count": len(candidates),
            "theme_count": len(themes),
        },
        risk_flags=risk_flags,
        next_actions=next_actions,
        candidates=candidates,
    )
