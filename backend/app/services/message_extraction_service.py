from __future__ import annotations

import json
import re
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.message import MessageSourceItem
from app.services.llm_client import call_llm_model
from app.services.message_graph_service import UpsertStats, upsert_entity, upsert_relation
from app.services.message_service import today_yyyymmdd

EXTRACTION_PROMPT_VERSION = "1.0"
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
) -> ExtractionResult:
    payload = _source_payload(item)
    prompt = EXTRACTION_PROMPT.replace("{payload}", json.dumps(payload, ensure_ascii=False))
    raw = call_llm_model(prompt, provider=provider, model=model, temperature=0.1)
    data = _json_from_text(raw)
    stats = UpsertStats()
    entities_by_name = {}

    for entity in data.get("entities") or []:
        name = str(entity.get("name") or "").strip()
        if not name:
            continue
        row = upsert_entity(
            db,
            name=name,
            entity_type=entity.get("entity_type") or None,
            confidence=int(entity.get("confidence") or 50),
            stats=stats,
        )
        entities_by_name[name] = row

    for relation in data.get("relations") or []:
        source_name = str(relation.get("source") or "").strip()
        target_name = str(relation.get("target") or "").strip()
        evidence_text = str(relation.get("evidence_text") or "").strip()
        if not source_name or not target_name or not evidence_text:
            continue
        source = entities_by_name.get(source_name) or upsert_entity(db, name=source_name, confidence=45, stats=stats)
        target = entities_by_name.get(target_name) or upsert_entity(db, name=target_name, confidence=45, stats=stats)
        confidence = int(relation.get("confidence") or 50)
        upsert_relation(
            db,
            source=source,
            relation_type=relation.get("relation_type") or "mentions",
            target=target,
            confidence=confidence,
            source_type="llm",
            evidence_text=evidence_text,
            evidence_url=item.url,
            source_channel=item.channel,
            source_item_id=item.id,
            stats=stats,
        )

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
) -> ExtractionResult:
    resolved_date = trade_date or today_yyyymmdd()
    rows = (
        db.query(MessageSourceItem)
        .filter(MessageSourceItem.trade_date == resolved_date, MessageSourceItem.status != "ignored")
        .order_by(MessageSourceItem.heat_score.desc(), MessageSourceItem.captured_at.desc())
        .limit(limit)
        .all()
    )
    total = ExtractionResult()
    for item in rows:
        try:
            result = extract_source_item(db, item, provider=provider, model=model)
        except Exception:
            db.rollback()
            total.error_count += 1
            continue
        total.processed_count += result.processed_count
        total.entity_count += result.entity_count
        total.relation_count += result.relation_count
        total.evidence_count += result.evidence_count
    return total
