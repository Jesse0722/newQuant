"""Deterministic entity mapping, sharing the existing versioned X seed map.

Seed mappings describe an industry connection, never a verified company event.
The full candidate list is retained for review instead of hiding ambiguity.
"""
from __future__ import annotations

import re
from sqlalchemy.orm import Session

from app.models.message import MessageSourceItem
from app.models.stock import StockBasic
from app.exceptions import AppError
from app.schemas.message import MessageAgentRunResult

MAPPING_AGENT = "entity_mapping"
MAPPING_VERSION = "1.0"
STOCK_CODE = re.compile(r"^\d{6}\.(SH|SZ|BJ)$")


def _term_matches(term: str, text: str) -> bool:
    # Short Latin tickers must not match arbitrary substrings (MU in demand).
    if term.isascii() and term.replace(" ", "").isalnum():
        return re.search(r"(?<![A-Za-z0-9])" + re.escape(term) + r"(?![A-Za-z0-9])", text, re.I) is not None
    return term.casefold() in text.casefold()


def mapping_candidates(db: Session, item: MessageSourceItem) -> list[dict]:
    # Lazy import avoids the existing x -> message -> evidence dependency cycle.
    from app.services.x_message_service import load_x_stock_mappings

    text = " ".join([item.title or "", item.content or ""])
    candidates: dict[str, dict] = {}
    for stock in db.query(StockBasic).all():
        terms = [term for term in (stock.ts_code, stock.name) if term and _term_matches(term, text)]
        if terms:
            candidates[stock.ts_code] = {
                "ts_code": stock.ts_code, "stock_name": stock.name, "theme": item.theme,
                "confidence": 95, "strength": "strong", "review_status": "reviewed",
                "matched_terms": terms, "mapping_path": ["source_quote", "stock_basic", stock.ts_code],
            }
    for seed in load_x_stock_mappings():
        if not _term_matches(seed.trigger, text):
            continue
        if seed.ts_code in candidates:
            candidates[seed.ts_code]["matched_terms"].append(seed.trigger)
            continue
        candidates[seed.ts_code] = {
            "ts_code": seed.ts_code, "stock_name": seed.stock_name, "theme": seed.theme,
            "confidence": min(65, int(seed.weight * 100)), "strength": "weak",
            "review_status": "needs_review", "matched_terms": [seed.trigger],
            "mapping_path": [seed.trigger, seed.theme, "seed_business_mapping", seed.ts_code],
        }
    if item.ts_code and STOCK_CODE.fullmatch(item.ts_code) and item.ts_code not in candidates:
        candidates[item.ts_code] = {
            "ts_code": item.ts_code, "stock_name": item.stock_name, "theme": item.theme,
            "confidence": 45, "strength": "weak", "review_status": "needs_review",
            "matched_terms": [], "mapping_path": ["imported_metadata", item.ts_code],
        }
    result = sorted(candidates.values(), key=lambda row: (-row["confidence"], row["ts_code"]))
    if len([row for row in result if row["strength"] == "strong"]) > 1:
        for row in result:
            row["review_status"] = "needs_review"
    return result


def supported_stock_code(db: Session, item: MessageSourceItem, requested: str | None) -> str | None:
    if requested is None:
        return item.ts_code
    if not STOCK_CODE.fullmatch(requested):
        raise ValueError("Invalid stock code in LLM output")
    if requested == item.ts_code or any(row["ts_code"] == requested for row in mapping_candidates(db, item)):
        return requested
    raise ValueError("LLM stock code has no source or seed mapping support")


def run_entity_mapping_agent(
    db: Session, *, trade_date: str | None = None, source_item_ids: list[str] | None = None,
    limit: int = 20, dry_run: bool = False,
) -> MessageAgentRunResult:
    from app.services.message_evidence_service import create_agent_run

    query = db.query(MessageSourceItem).filter(MessageSourceItem.status.in_(["new", "processed"]))
    if source_item_ids:
        query = query.filter(MessageSourceItem.id.in_(source_item_ids))
    elif trade_date:
        query = query.filter(MessageSourceItem.trade_date == trade_date)
    else:
        raise AppError(code=5107, message="缺少 Agent 输入范围", detail="请提供 trade_date 或 source_item_ids。", status_code=400)
    items = query.order_by(MessageSourceItem.heat_score.desc(), MessageSourceItem.id).limit(max(1, min(limit, 100))).all()
    outputs = []
    updated = 0
    for item in items:
        candidates = mapping_candidates(db, item)
        output = {"source_item_id": item.id, "version": MAPPING_VERSION, "candidates": candidates,
                  "review_status": candidates[0]["review_status"] if candidates else "needs_review"}
        outputs.append(output)
        if dry_run:
            continue
        payload = dict(item.raw_payload or {})
        if payload.get("entity_mapping") != output:
            payload["entity_mapping"] = output
            item.raw_payload = payload
            updated += 1
        if candidates and not item.ts_code:
            item.ts_code = candidates[0]["ts_code"]
            item.stock_name = candidates[0]["stock_name"]
            item.theme = item.theme or candidates[0]["theme"]
    run = None
    if not dry_run:
        run = create_agent_run(db, agent_name=MAPPING_AGENT, agent_version=MAPPING_VERSION,
                               trade_date=trade_date, output_json={"mappings": outputs},
                               input_ref_type="source_item_batch", prompt_version=MAPPING_VERSION)
        db.commit()
        db.refresh(run)
    return MessageAgentRunResult(agent_name=MAPPING_AGENT, trade_date=trade_date, dry_run=dry_run,
                                 source_item_count=len(items), created_count=0, updated_count=updated,
                                 skipped_count=len(items)-updated, evidence_count=0, run=run)
