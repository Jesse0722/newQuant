from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.exceptions import AppError
from app.schemas.message import MessageAgentRunOut, MessageAgentRunRequest, MessageAgentRunResult
from app.services.message_evidence_service import (
    LLM_EVIDENCE_AGENT,
    RULE_EVIDENCE_AGENT,
    get_agent_run,
    list_agent_runs,
    run_llm_evidence_cleaner,
    run_rule_evidence_cleaner,
)

router = APIRouter(prefix="/api/message-agents", tags=["message-agents"])


@router.post("/run", response_model=MessageAgentRunResult, status_code=201)
def run_agent(body: MessageAgentRunRequest, db: Session = Depends(get_db)):
    if body.agent_name == RULE_EVIDENCE_AGENT:
        return run_rule_evidence_cleaner(
            db,
            trade_date=body.trade_date,
            source_item_ids=body.source_item_ids,
            dry_run=body.dry_run,
        )
    if body.agent_name == LLM_EVIDENCE_AGENT:
        return run_llm_evidence_cleaner(
            db,
            trade_date=body.trade_date,
            source_item_ids=body.source_item_ids,
            limit=body.limit,
            provider=body.provider,
            model=body.model,
            dry_run=body.dry_run,
        )
    else:
        raise AppError(
            code=5108,
            message="暂不支持的 Agent",
            detail=f"当前支持 {RULE_EVIDENCE_AGENT}、{LLM_EVIDENCE_AGENT}。",
            status_code=400,
        )


@router.get("/runs", response_model=list[MessageAgentRunOut])
def get_runs(
    agent_name: str | None = Query(default=None),
    trade_date: str | None = Query(default=None, pattern=r"^\d{8}$"),
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    return list_agent_runs(
        db,
        agent_name=agent_name,
        trade_date=trade_date,
        status=status,
        limit=limit,
    )


@router.get("/runs/{run_id}", response_model=MessageAgentRunOut)
def get_run(run_id: str, db: Session = Depends(get_db)):
    return get_agent_run(db, run_id)
