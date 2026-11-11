from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import timezone
from pathlib import Path

from sqlalchemy.orm import Session

from app.models.message import MessageEntity, MessageRelation, MessageRelationEvidence, MessageSourceItem
from app.schemas.industry_report import GraphPathOut, GraphPathStep, GraphSeedImportOut
from app.services.message_llm_validation import anchored_quote
from app.services.trading_session import shanghai_datetime

SEED_DIR = Path(__file__).resolve().parent.parent / "seeds"
INDUSTRY_GRAPH_SEED = SEED_DIR / "industry_graph_seed.csv"
STOCK_BUSINESS_SEED = SEED_DIR / "stock_business_seed.csv"
OBJECTIVE_RELATIONS = {
    "uses",
    "supplies",
    "depends_on",
    "maps_to",
    "mentions",
    "triggers",
    "increases_demand_for",
    "competes_with",
    "substitutes",
    "verifies",
    "refutes",
}


@dataclass
class UpsertStats:
    entity_created: int = 0
    entity_updated: int = 0
    relation_created: int = 0
    relation_updated: int = 0
    evidence_created: int = 0

    def out(self) -> GraphSeedImportOut:
        return GraphSeedImportOut(**self.__dict__)


def normalize_entity_name(value: str) -> str:
    return " ".join(value.strip().lower().split())


def _entity_type_for_name(name: str, ts_code: str | None = None) -> str:
    if ts_code:
        return "stock"
    if name.upper() in {"HBM", "PCB", "NVLINK", "ABF"}:
        return "technology"
    if name in {"AI算力", "NVIDIA产业链", "HBM与存储", "光模块", "铜连接", "液冷", "AI电力", "AI服务器", "机器人"}:
        return "theme"
    return "industry_chain"


def upsert_entity(
    db: Session,
    *,
    name: str,
    entity_type: str | None = None,
    ts_code: str | None = None,
    aliases: list[str] | None = None,
    confidence: int = 70,
    stats: UpsertStats | None = None,
) -> MessageEntity:
    normalized_name = normalize_entity_name(ts_code or name)
    resolved_type = entity_type or _entity_type_for_name(name, ts_code)
    entity = (
        db.query(MessageEntity)
        .filter(MessageEntity.entity_type == resolved_type, MessageEntity.normalized_name == normalized_name)
        .first()
    )
    values = {
        "name": name.strip(),
        "ts_code": ts_code or (entity.ts_code if entity else None),
        "aliases": list(dict.fromkeys([*(entity.aliases or [] if entity else []), *(aliases or [])])),
        "confidence": max(0, min(100, max(confidence, entity.confidence if entity else confidence))),
        "status": "active",
    }
    if entity:
        for key, value in values.items():
            setattr(entity, key, value)
        if stats:
            stats.entity_updated += 1
        return entity

    entity = MessageEntity(
        entity_type=resolved_type,
        normalized_name=normalized_name,
        **values,
    )
    db.add(entity)
    db.flush()
    if stats:
        stats.entity_created += 1
    return entity


def upsert_relation(
    db: Session,
    *,
    source: MessageEntity,
    relation_type: str,
    target: MessageEntity,
    confidence: int = 60,
    strength: int | None = None,
    polarity: str = "neutral",
    source_type: str = "seed",
    evidence_text: str | None = None,
    evidence_url: str | None = None,
    source_channel: str | None = None,
    source_item_id: str | None = None,
    stats: UpsertStats | None = None,
) -> MessageRelation:
    if relation_type not in OBJECTIVE_RELATIONS:
        relation_type = "mentions"
        confidence = min(confidence, 50)
    confidence = max(0, min(100, confidence))
    if relation_type == "mentions":
        confidence = min(confidence, 50)
    if relation_type == "refutes":
        polarity = "negative"

    relation = (
        db.query(MessageRelation)
        .filter(
            MessageRelation.source_entity_id == source.id,
            MessageRelation.relation_type == relation_type,
            MessageRelation.target_entity_id == target.id,
            MessageRelation.source_type == source_type,
        )
        .first()
    )
    resolved_strength = max(0, min(100, strength if strength is not None else confidence))
    if relation_type == "mentions":
        resolved_strength = min(resolved_strength, 50)
    if relation:
        relation.confidence = max(relation.confidence, confidence)
        relation.strength = max(relation.strength, resolved_strength)
        relation.polarity = polarity
        relation.status = "active"
        if stats:
            stats.relation_updated += 1
    else:
        relation = MessageRelation(
            source_entity_id=source.id,
            relation_type=relation_type,
            target_entity_id=target.id,
            confidence=confidence,
            strength=resolved_strength,
            polarity=polarity,
            source_type=source_type,
            status="active",
        )
        db.add(relation)
        db.flush()
        if stats:
            stats.relation_created += 1

    if evidence_text:
        existing = (
            db.query(MessageRelationEvidence)
            .filter(
                MessageRelationEvidence.relation_id == relation.id,
                MessageRelationEvidence.extraction_method == source_type,
                MessageRelationEvidence.evidence_text == evidence_text,
                MessageRelationEvidence.source_item_id == source_item_id,
            )
            .first()
        )
        if not existing:
            db.add(
                MessageRelationEvidence(
                    relation_id=relation.id,
                    source_item_id=source_item_id,
                    evidence_text=evidence_text,
                    evidence_url=evidence_url,
                    source_channel=source_channel,
                    extraction_method=source_type,
                    confidence=confidence,
                )
            )
            relation.evidence_count += 1
            if stats:
                stats.evidence_created += 1
    return relation


def import_seed_graph(db: Session) -> GraphSeedImportOut:
    stats = UpsertStats()
    with INDUSTRY_GRAPH_SEED.open("r", encoding="utf-8", newline="") as fp:
        for row in csv.DictReader(fp):
            source = upsert_entity(db, name=row["source"], confidence=int(row["confidence"]), stats=stats)
            target = upsert_entity(db, name=row["target"], confidence=int(row["confidence"]), stats=stats)
            upsert_relation(
                db,
                source=source,
                relation_type=row["relation"],
                target=target,
                confidence=int(row["confidence"]),
                source_type="seed",
                evidence_text=row.get("note") or f"{row['source']} {row['relation']} {row['target']}",
                source_channel="seed:industry_graph",
                stats=stats,
            )

    with STOCK_BUSINESS_SEED.open("r", encoding="utf-8", newline="") as fp:
        for row in csv.DictReader(fp):
            stock = upsert_entity(
                db,
                name=row["stock_name"],
                entity_type="stock",
                ts_code=row["ts_code"],
                aliases=[row["stock_name"], row["ts_code"]],
                confidence=int(row["confidence"]),
                stats=stats,
            )
            business = upsert_entity(
                db,
                name=row["business_node"],
                entity_type=_entity_type_for_name(row["business_node"]),
                confidence=int(row["confidence"]),
                stats=stats,
            )
            upsert_relation(
                db,
                source=stock,
                relation_type=row["relation"],
                target=business,
                confidence=int(row["confidence"]),
                source_type="seed",
                evidence_text=row.get("evidence_note") or f"{row['stock_name']} maps to {row['business_node']}",
                source_channel="seed:stock_business",
                stats=stats,
            )
    db.commit()
    return stats.out()


def find_entity(db: Session, name: str) -> MessageEntity | None:
    normalized = normalize_entity_name(name)
    return (
        db.query(MessageEntity)
        .filter(
            MessageEntity.status == "active",
            (MessageEntity.normalized_name == normalized) | (MessageEntity.name == name),
        )
        .first()
    )


def relation_is_effective(relation: MessageRelation, as_of: str | None) -> bool:
    return relation.status == "active" and (
        as_of is None or ((not relation.valid_from or relation.valid_from <= as_of)
                          and (not relation.valid_to or relation.valid_to >= as_of))
    )


def source_item_available_on(item: MessageSourceItem | None, as_of: str | None) -> bool:
    if item is None or item.status not in {"new", "processed"}:
        return False
    if as_of is None:
        return True
    if item.trade_date > as_of:
        return False
    if item.published_at:
        published = item.published_at
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)
        if shanghai_datetime(published).strftime("%Y%m%d") > as_of:
            return False
    return True


def relation_evidence_as_of(db: Session, *, as_of: str | None = None) -> dict[str, list[dict]]:
    """Apply one evidence cutoff to every hop, including stock/business mapping.

    as_of is the Shanghai source/publication day, not an ingestion replay clock.
    Source-free versioned seed notes are static mappings; their import timestamp
    does not establish a contemporary catalyst or suppress historical fixtures.
    """
    source_by_id = {row.id: row for row in db.query(MessageSourceItem).filter(
        MessageSourceItem.status.in_(["new", "processed"])
    ).all()}
    evidence_by_relation: dict[str, list[dict]] = {}
    for evidence in db.query(MessageRelationEvidence).all():
        item = source_by_id.get(evidence.source_item_id)
        static_seed = evidence.extraction_method == "seed" and evidence.source_item_id is None
        if not static_seed and not source_item_available_on(item, as_of):
            continue
        if not static_seed:
            try:
                anchored_quote(evidence.evidence_text, item.title, item.content)
            except ValueError:
                continue
        evidence_by_relation.setdefault(evidence.relation_id, []).append({
            "evidence_id": evidence.id, "relation_id": evidence.relation_id,
            "source_item_id": evidence.source_item_id, "evidence_text": evidence.evidence_text,
            "evidence_kind": "seed_note" if static_seed else "quote",
            "url": evidence.evidence_url, "channel": evidence.source_channel,
            "source_name": item.source_name if item else "versioned_seed",
            "source_trade_date": item.trade_date if item else None,
            "source_published_at": item.published_at.isoformat() if item and item.published_at else None,
            "static_mapping": static_seed,
            "confidence": evidence.confidence, "extraction_method": evidence.extraction_method,
            "stance": "neutral",
        })
    return evidence_by_relation


def find_paths(db: Session, start_name: str, max_depth: int = 3, *, as_of: str | None = None) -> list[GraphPathOut]:
    start = find_entity(db, start_name)
    if not start:
        return []
    relations = [row for row in db.query(MessageRelation).filter(MessageRelation.status == "active").all()
                 if relation_is_effective(row, as_of)]
    evidence_by_relation = relation_evidence_as_of(db, as_of=as_of)
    entity_by_id = {row.id: row for row in db.query(MessageEntity).filter(MessageEntity.status == "active").all()}
    outgoing: dict[str, list[MessageRelation]] = {}
    for relation in relations:
        if not evidence_by_relation.get(relation.id):
            continue
        outgoing.setdefault(relation.source_entity_id, []).append(relation)

    results: list[GraphPathOut] = []
    queue: list[tuple[str, list[MessageRelation]]] = [(start.id, [])]
    while queue:
        entity_id, path = queue.pop(0)
        if len(path) >= max_depth:
            continue
        for relation in outgoing.get(entity_id, []):
            if any(step.target_entity_id == relation.target_entity_id for step in path):
                continue
            next_path = [*path, relation]
            target = entity_by_id.get(relation.target_entity_id)
            if not target:
                continue
            confidence_by_relation = {
                step.id: min(step.confidence, max(row["confidence"] for row in evidence_by_relation[step.id]))
                for step in next_path
            }
            score = min(confidence_by_relation.values())
            if any(step.relation_type in {"mentions", "refutes"} for step in next_path):
                score = min(score, 40)
            results.append(
                GraphPathOut(
                    start=start.name,
                    end=target.name,
                    depth=len(next_path),
                    score=score,
                    steps=[
                        GraphPathStep(
                            source=entity_by_id[step.source_entity_id].name,
                            relation=step.relation_type,
                            target=entity_by_id[step.target_entity_id].name,
                            confidence=confidence_by_relation[step.id],
                            strength=min(step.strength, confidence_by_relation[step.id]),
                            relation_id=step.id,
                            source_type=step.source_type,
                            evidence=[dict(row, stance="contradiction" if step.relation_type == "refutes" else "neutral")
                                      for row in evidence_by_relation.get(step.id, [])],
                        )
                        for step in next_path
                    ],
                )
            )
            queue.append((relation.target_entity_id, next_path))
    return sorted(results, key=lambda item: (-item.score, item.depth, item.end))[:50]
