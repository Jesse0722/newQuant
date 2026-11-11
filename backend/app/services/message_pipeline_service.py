"""Opt-in, bounded research pipeline; no external calls unless enabled.

Each stage has its own transaction/run record. A failed collector does not
prevent processing already stored sources, and dependent stages are skipped.
"""
from __future__ import annotations

import os
from sqlalchemy.orm import Session

from app.config import env_flag
from app.models.message import MessageSourceItem
from app.services.message_service import aggregate_source_items, today_yyyymmdd
from app.services.message_evidence_service import (
    build_agent_daily_report, create_agent_run, run_llm_evidence_cleaner, run_rule_evidence_cleaner,
    llm_cleaner_input_is_cached,
)
from app.services.message_mapping_service import run_entity_mapping_agent
from app.services.industry_report_service import generate_industry_report


def run_message_pipeline(
    db: Session, *, trade_date: str | None = None, enabled: bool | None = None,
    collect_enabled: bool | None = None, use_llm: bool | None = None, limit: int | None = None,
) -> dict:
    active = env_flag("MESSAGE_PIPELINE_ENABLED", False) if enabled is None else enabled
    resolved_date = trade_date or today_yyyymmdd()
    if not active:
        return {"status": "disabled", "trade_date": resolved_date, "stages": {}, "error_count": 0}
    collect = env_flag("MESSAGE_PIPELINE_COLLECT_ENABLED", False) if collect_enabled is None else collect_enabled
    llm = env_flag("MESSAGE_PIPELINE_LLM_ENABLED", False) if use_llm is None else use_llm
    size = max(1, min(100, limit if limit is not None else int(os.getenv("MESSAGE_PIPELINE_LIMIT", "20"))))
    stages: dict[str, dict] = {}

    def stage(name, fn, dependencies=()):
        if any(stages.get(dep, {}).get("status") not in {"success", "success_with_fallback"} for dep in dependencies):
            stages[name] = {"status": "skipped", "reason": "dependency_failed"}
            return
        try:
            value = fn()
            result = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
            if not isinstance(result, dict):
                result = {"report_id": value.id}
                if getattr(value, "error_message", None):
                    result.update(error_count=1, warning=value.error_message)
            if (name == "agent_report" and llm and result.get("model_provider") == "rules"
                    and result.get("evidence_coverage", {}).get("evidence_count", 0)):
                result.update(error_count=1, warning="LLM日报失败，已保留规则报告与失败审计")
            status = "success_with_fallback" if result.get("error_count", 0) else "success"
            stages[name] = {"status": status, "result": result}
        except Exception as exc:
            db.rollback()
            stages[name] = {"status": "failed", "error": str(exc)[:500]}

    if collect:
        def collect_sources():
            from app.schemas.message import MessageXCollectRequest
            from app.services.x_message_service import collect_x_recent_posts
            return collect_x_recent_posts(db, MessageXCollectRequest(
                trade_date=resolved_date, max_results=max(10, size), aggregate=False,
            ))
        stage("collect", collect_sources)
    else:
        stages["collect"] = {"status": "disabled"}
    available_sources = db.query(MessageSourceItem).filter(
        MessageSourceItem.trade_date == resolved_date, MessageSourceItem.status.in_(["new", "processed"])
    ).order_by(MessageSourceItem.heat_score.desc(), MessageSourceItem.id).all()
    pending = [row for row in available_sources if not llm or not llm_cleaner_input_is_cached(db, row)]
    ids = [row.id for row in (pending or available_sources)[:size]]
    if ids:
        cleaner = run_llm_evidence_cleaner if llm else run_rule_evidence_cleaner
        stage("clean", lambda: cleaner(db, source_item_ids=ids, limit=size))
        stage("map", lambda: run_entity_mapping_agent(db, source_item_ids=ids, limit=size), ("clean",))
        stage("score", lambda: aggregate_source_items(db, resolved_date), ("map",))
        stage("agent_report", lambda: build_agent_daily_report(db, trade_date=resolved_date, use_llm=llm), ("score",))
        stage("industry_report", lambda: generate_industry_report(db, trade_date=resolved_date, use_llm=llm), ("score",))
    else:
        stages["clean"] = {"status": "skipped", "reason": "no_sources"}
    failures = sum(1 if stage_result.get("status") == "failed" else stage_result.get("result", {}).get("error_count", 0)
                   for stage_result in stages.values())
    result = {"status": "success_with_errors" if failures else "success", "trade_date": resolved_date,
              "source_item_count": len(ids), "limit": size, "stages": stages, "error_count": failures}
    create_agent_run(db, agent_name="message_pipeline", agent_version="1.0", trade_date=resolved_date,
                     input_snapshot={"trade_date": resolved_date, "source_item_ids": ids, "limit": size,
                                     "collect_enabled": collect, "use_llm": llm},
                     output_json=result, status=result["status"])
    db.commit()
    return result


def run_message_pipeline_job(trade_date: str | None = None) -> dict:
    # Check before opening a session, keeping a disabled scheduler a true no-op.
    if not env_flag("MESSAGE_PIPELINE_ENABLED", False):
        return {"status": "disabled", "stages": {}, "error_count": 0}
    from app.database import SessionLocal
    with SessionLocal() as db:
        return run_message_pipeline(db, trade_date=trade_date)
