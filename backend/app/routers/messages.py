from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.message import (
    MessageDailyConclusionOut,
    MessageDailyOut,
    MessageKeywordImportOut,
    MessageKeywordImportRequest,
    MessageOpportunityCreate,
    MessageOpportunityOut,
    MessageSeedKeywordOut,
    MessageSourceImportOut,
    MessageSourceImportRequest,
    MessageXCollectOut,
    MessageXCollectRequest,
    MessageXSeedSummaryOut,
    MessageTopicCreate,
    MessageTopicOut,
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
)

router = APIRouter(prefix="/api/messages", tags=["messages"])


@router.get("/daily", response_model=MessageDailyOut)
def get_daily(
    trade_date: str | None = Query(default=None, pattern=r"^\d{8}$"),
    ensure_seed: bool = Query(default=True),
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


@router.post("/topics", response_model=MessageTopicOut, status_code=201)
def upsert_topic(body: MessageTopicCreate, db: Session = Depends(get_db)):
    return create_or_update_topic(db, body)


@router.post("/opportunities", response_model=MessageOpportunityOut, status_code=201)
def add_opportunity(body: MessageOpportunityCreate, db: Session = Depends(get_db)):
    return create_opportunity(db, body)


@router.post("/source-items/import", response_model=MessageSourceImportOut, status_code=201)
def import_sources(body: MessageSourceImportRequest, db: Session = Depends(get_db)):
    return import_source_items(db, body)


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


@router.post("/keywords/import-default", response_model=MessageKeywordImportOut, status_code=201)
def import_default_keywords(db: Session = Depends(get_db)):
    return import_default_keyword_seeds(db)
