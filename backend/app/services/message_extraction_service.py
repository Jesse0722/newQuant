from __future__ import annotations

import json
import re
import hashlib
from dataclasses import dataclass
from typing import Literal

from pydantic import Field

from sqlalchemy.orm import Session

from app.models.message import MessageSourceItem, MessageAgentRun
from app.services.llm_client import call_llm_model
from app.services.message_graph_service import UpsertStats, upsert_entity, upsert_relation
from app.services.message_service import today_yyyymmdd
from app.services.message_llm_validation import StrictOutput, anchored_quote
from app.services.message_evidence_service import create_agent_run

EXTRACTION_PROMPT_VERSION = "1.1"
EXTRACTION_AGENT = "graph_relation_extractor"
EXTRACTION_PROMPT = """你是产业链舆情关系抽取器。只能基于输入文本抽取，不得补充外部知识。

硬性规则：
1. 只返回 JSON，不要 Markdown。
2. 如果只是共同出现但没有明确关系，relation_type 必须使用 mentions。
3. 不要把“利好/利空/买入/上涨”抽成事实关系。
4. 每条关系必须带 evidence_text，必须是输入文本中的短片段。
5. 证据不足时 confidence 不得高于 50。

允许的 relation_type：
uses, supplies, depends_on, maps_to, mentions, triggers, increases_demand_for, competes_with, substitutes, verifies, refutes

返回格式：
{
  "entities": [
    {"name": "实体名", "entity_type": "company|stock|theme|product|technology|industry_chain|event|source|person", "confidence": 0-100}
  ],
  "relations": [
    {"source": "实体名", "relation_type": "mentions", "target": "实体名", "confidence": 0-100, "evidence_text": "证据片段"}
  ]
}

输入：
{payload}
"""


@dataclass
class ExtractionResult:
    processed_count: int = 0
    entity_count: int = 0
    relation_count: int = 0
    evidence_count: int = 0
    error_count: int = 0
    skipped_count: int = 0


class ExtractedEntity(StrictOutput):
    name: str = Field(min_length=1, max_length=128)
    entity_type: Literal["company", "stock", "theme", "product", "technology", "industry_chain", "event", "source", "person"]
    confidence: int = Field(ge=0, le=100)


class ExtractedRelation(StrictOutput):
    source: str = Field(min_length=1, max_length=128)
    target: str = Field(min_length=1, max_length=128)
    relation_type: Literal["uses", "supplies", "depends_on", "maps_to", "mentions", "triggers", "increases_demand_for", "competes_with", "substitutes", "verifies", "refutes"]
    confidence: int = Field(ge=0, le=100)
    evidence_text: str = Field(min_length=1, max_length=1000)


class ExtractionOutput(StrictOutput):
    entities: list[ExtractedEntity] = Field(max_length=50)
    relations: list[ExtractedRelation] = Field(max_length=100)


def _json_from_text(text: str) -> dict:
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
        "channel": item.channel,
        "source_name": item.source_name,
        "title": item.title,
        "content": item.content,
        "theme": item.theme,
        "ts_code": item.ts_code,
        "stock_name": item.stock_name,
        "tags": item.tags or [],
        "url": item.url,
    }


def extract_source_item(
    db: Session,
    item: MessageSourceItem,
    *,
    provider: str = "deepseek",
    model: str = "deepseek-v4-flash",
    force: bool = False,
) -> ExtractionResult:
    payload = _source_payload(item)
    audit_input = {"source": payload, "provider": provider, "model": model, "prompt_version": EXTRACTION_PROMPT_VERSION}
    digest = hashlib.sha256(json.dumps(audit_input, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    previous_runs = db.query(MessageAgentRun).filter(
        MessageAgentRun.agent_name == EXTRACTION_AGENT, MessageAgentRun.input_ref_id == item.id,
        MessageAgentRun.input_digest == digest,
    )
    already_done = previous_runs.filter(MessageAgentRun.status == "success").first() is not None
    retry_limit_reached = previous_runs.filter(MessageAgentRun.status == "failed").count() >= 3
    if not force and (already_done or retry_limit_reached):
        return ExtractionResult(skipped_count=1)
    prompt = EXTRACTION_PROMPT.replace("{payload}", json.dumps(payload, ensure_ascii=False))
    raw = None
    stats = UpsertStats()
    entities_by_name = {}
    try:
        raw = call_llm_model(prompt, provider=provider, model=model, temperature=0.1)
        data = ExtractionOutput.model_validate(_json_from_text(raw))
        for entity in data.entities:
            anchored_quote(entity.name, item.title, item.content)
        for relation in data.relations:
            anchored_quote(relation.evidence_text, item.title, item.content)
            anchored_quote(relation.source, None, relation.evidence_text)
            anchored_quote(relation.target, None, relation.evidence_text)
        with db.begin_nested():
            for entity in data.entities:
                ts_code = None
                if entity.entity_type == "stock":
                    from app.services.message_mapping_service import mapping_candidates
                    matches = [row for row in mapping_candidates(db, item)
                               if entity.name in {row["ts_code"], row["stock_name"]}]
                    if not matches:
                        raise ValueError("Extracted stock has no validated source mapping")
                    ts_code = matches[0]["ts_code"]
                row = upsert_entity(db, name=entity.name, entity_type=entity.entity_type,
                                    ts_code=ts_code, confidence=entity.confidence, stats=stats)
                entities_by_name[entity.name] = row
            for relation in data.relations:
                source = entities_by_name.get(relation.source) or upsert_entity(db, name=relation.source, confidence=45, stats=stats)
                target = entities_by_name.get(relation.target) or upsert_entity(db, name=relation.target, confidence=45, stats=stats)
                upsert_relation(db, source=source, relation_type=relation.relation_type, target=target,
                                confidence=relation.confidence, source_type="llm", evidence_text=relation.evidence_text,
                                evidence_url=item.url, source_channel=item.channel, source_item_id=item.id, stats=stats)
            db.flush()
    except Exception as exc:
        create_agent_run(db, agent_name=EXTRACTION_AGENT, agent_version=EXTRACTION_PROMPT_VERSION,
                         input_ref_type="source_item", input_ref_id=item.id, trade_date=item.trade_date,
                         input_snapshot=audit_input, raw_response=raw, model_provider=provider, model_name=model,
                         prompt_version=EXTRACTION_PROMPT_VERSION, status="failed", error_message=str(exc)[:500])
        db.commit()
        raise
    create_agent_run(db, agent_name=EXTRACTION_AGENT, agent_version=EXTRACTION_PROMPT_VERSION,
                     input_ref_type="source_item", input_ref_id=item.id, trade_date=item.trade_date,
                     input_snapshot=audit_input, raw_response=raw, model_provider=provider, model_name=model,
                     prompt_version=EXTRACTION_PROMPT_VERSION, output_json=data.model_dump())
    db.commit()
    return ExtractionResult(
        processed_count=1,
        entity_count=stats.entity_created + stats.entity_updated,
        relation_count=stats.relation_created + stats.relation_updated,
        evidence_count=stats.evidence_created,
        error_count=0,
    )


def extract_source_items_for_date(
    db: Session,
    *,
    trade_date: str | None = None,
    limit: int = 20,
    provider: str = "deepseek",
    model: str = "deepseek-v4-flash",
    force: bool = False,
) -> ExtractionResult:
    resolved_date = trade_date or today_yyyymmdd()
    rows = (
        db.query(MessageSourceItem)
        .filter(MessageSourceItem.trade_date == resolved_date, MessageSourceItem.status.in_(["new", "processed"]))
        .order_by(MessageSourceItem.heat_score.desc(), MessageSourceItem.captured_at.desc())
        .all()
    )
    total = ExtractionResult()
    for item in rows:
        if total.processed_count + total.error_count >= max(1, min(limit, 100)):
            break
        try:
            result = extract_source_item(db, item, provider=provider, model=model, force=force)
        except Exception:
            db.rollback()
            total.error_count += 1
            continue
        total.processed_count += result.processed_count
        total.entity_count += result.entity_count
        total.relation_count += result.relation_count
        total.evidence_count += result.evidence_count
        total.skipped_count += result.skipped_count
    return total
