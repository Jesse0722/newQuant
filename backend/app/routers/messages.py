from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.message import (
    MessageEvidenceOut,
    MessageAgentDailyGenerateRequest,
    MessageAgentDailyOut,
    MessageDailyConclusionOut,
    MessageDailyOut,
    MessageKeywordImportOut,
    MessageKeywordImportRequest,
    MessageOpportunityCreate,
    MessageOpportunityEvidenceOut,
    MessageOpportunityDismissRequest,
    MessageOpportunityOut,
    MessageOpportunityReviewRequest,
    MessageSeedKeywordCreate,
    MessageSeedKeywordOut,
    MessageSourceImportOut,
    MessageSourceImportRequest,
    MessageXCollectOut,
    MessageXCollectRequest,
    MessageXSeedSummaryOut,
    MessageTopicCreate,
    MessageTopicOut,
)
from app.services.message_evidence_service import (
    accept_opportunity,
    dismiss_opportunity,
    get_opportunity_evidence,
    list_evidence,
    review_opportunity,
    build_agent_daily_report,
)
from app.services.message_service import (
    create_opportunity,
    create_or_update_topic,
    get_daily_conclusion,
    get_daily_messages,
    import_source_items,
    today_yyyymmdd,
)
from app.services.x_message_service import (
    collect_x_recent_posts,
    get_x_seed_summary,
    import_default_keyword_seeds,
    import_keyword_seeds,
    list_keyword_seed_rows,
    save_keyword_seed,
)

router = APIRouter(prefix="/api/messages", tags=["messages"])


@router.get("/daily", response_model=MessageDailyOut)
def get_daily(
    trade_date: str | None = Query(default=None, pattern=r"^\d{8}$"),
    ensure_seed: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    return get_daily_messages(db, trade_date or today_yyyymmdd(), ensure_seed=ensure_seed)


@router.get("/daily-conclusion", response_model=MessageDailyConclusionOut)
def get_conclusion(
    trade_date: str | None = Query(default=None, pattern=r"^\d{8}$"),
    ensure_seed: bool = Query(default=False),
    limit: int = Query(default=5, ge=1, le=10),
    db: Session = Depends(get_db),
):
    return get_daily_conclusion(db, trade_date or today_yyyymmdd(), ensure_seed=ensure_seed, limit=limit)


@router.get("/agent-daily", response_model=MessageAgentDailyOut)
def get_agent_daily(
    trade_date: str | None = Query(default=None, pattern=r"^\d{8}$"),
    limit: int = Query(default=5, ge=1, le=10),
    db: Session = Depends(get_db),
):
    return build_agent_daily_report(db, trade_date=trade_date or today_yyyymmdd(), limit=limit)


@router.post("/agent-daily/generate", response_model=MessageAgentDailyOut)
def generate_agent_daily(body: MessageAgentDailyGenerateRequest, db: Session = Depends(get_db)):
    return build_agent_daily_report(
        db,
        trade_date=body.trade_date or today_yyyymmdd(),
        use_llm=body.use_llm,
        provider=body.provider,
        model=body.model,
        limit=body.limit,
    )


@router.post("/topics", response_model=MessageTopicOut, status_code=201)
def upsert_topic(body: MessageTopicCreate, db: Session = Depends(get_db)):
    return create_or_update_topic(db, body)


@router.post("/opportunities", response_model=MessageOpportunityOut, status_code=201)
def add_opportunity(body: MessageOpportunityCreate, db: Session = Depends(get_db)):
    return create_opportunity(db, body)


@router.post("/source-items/import", response_model=MessageSourceImportOut, status_code=201)
def import_sources(body: MessageSourceImportRequest, db: Session = Depends(get_db)):
    return import_source_items(db, body)


@router.get("/evidence", response_model=list[MessageEvidenceOut])
def get_evidence(
    trade_date: str | None = Query(default=None, pattern=r"^\d{8}$"),
    theme: str | None = Query(default=None),
    ts_code: str | None = Query(default=None),
    stance: str | None = Query(default=None),
    status: str | None = Query(default=None),
    source_item_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    return list_evidence(
        db,
        trade_date=trade_date,
        theme=theme,
        ts_code=ts_code,
        stance=stance,
        status=status,
        source_item_id=source_item_id,
        limit=limit,
    )


@router.get("/opportunities/{opportunity_id}/evidence", response_model=list[MessageOpportunityEvidenceOut])
def get_opportunity_evidence_items(opportunity_id: str, db: Session = Depends(get_db)):
    return get_opportunity_evidence(db, opportunity_id)


@router.post("/opportunities/{opportunity_id}/review", response_model=MessageOpportunityOut)
def review_message_opportunity(
    opportunity_id: str,
    body: MessageOpportunityReviewRequest,
    db: Session = Depends(get_db),
):
    return review_opportunity(db, opportunity_id, body.review_status, body.review_reason)


@router.post("/opportunities/{opportunity_id}/accept", response_model=MessageOpportunityOut)
def accept_message_opportunity(opportunity_id: str, db: Session = Depends(get_db)):
    return accept_opportunity(db, opportunity_id)


@router.post("/opportunities/{opportunity_id}/dismiss", response_model=MessageOpportunityOut)
def dismiss_message_opportunity(
    opportunity_id: str,
    body: MessageOpportunityDismissRequest | None = None,
    db: Session = Depends(get_db),
):
    return dismiss_opportunity(db, opportunity_id, body.review_reason if body else None)


@router.get("/x/seeds", response_model=MessageXSeedSummaryOut)
def get_x_seeds(db: Session = Depends(get_db)):
    return get_x_seed_summary(db)


@router.post("/x/collect", response_model=MessageXCollectOut, status_code=201)
def collect_x_posts(body: MessageXCollectRequest, db: Session = Depends(get_db)):
    return collect_x_recent_posts(db, body)


@router.get("/keywords", response_model=list[MessageSeedKeywordOut])
def list_keywords(db: Session = Depends(get_db)):
    return list_keyword_seed_rows(db)


@router.post("/keywords/import", response_model=MessageKeywordImportOut, status_code=201)
def import_keywords(body: MessageKeywordImportRequest, db: Session = Depends(get_db)):
    return import_keyword_seeds(db, body)


@router.post("/keywords", response_model=MessageSeedKeywordOut, status_code=201)
def save_keyword(body: MessageSeedKeywordCreate, db: Session = Depends(get_db)):
    return save_keyword_seed(db, body)


@router.post("/keywords/import-default", response_model=MessageKeywordImportOut, status_code=201)
def import_default_keywords(db: Session = Depends(get_db)):
    return import_default_keyword_seeds(db)
