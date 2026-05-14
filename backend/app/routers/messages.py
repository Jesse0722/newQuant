from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.message import (
    MessageDailyOut,
    MessageOpportunityCreate,
    MessageOpportunityOut,
    MessageTopicCreate,
    MessageTopicOut,
)
from app.services.message_service import (
    create_opportunity,
    create_or_update_topic,
    get_daily_messages,
    today_yyyymmdd,
)

router = APIRouter(prefix="/api/messages", tags=["messages"])


@router.get("/daily", response_model=MessageDailyOut)
def get_daily(
    trade_date: str | None = Query(default=None, pattern=r"^\d{8}$"),
    ensure_seed: bool = Query(default=True),
    db: Session = Depends(get_db),
):
    return get_daily_messages(db, trade_date or today_yyyymmdd(), ensure_seed=ensure_seed)


@router.post("/topics", response_model=MessageTopicOut, status_code=201)
def upsert_topic(body: MessageTopicCreate, db: Session = Depends(get_db)):
    return create_or_update_topic(db, body)


@router.post("/opportunities", response_model=MessageOpportunityOut, status_code=201)
def add_opportunity(body: MessageOpportunityCreate, db: Session = Depends(get_db)):
    return create_opportunity(db, body)
