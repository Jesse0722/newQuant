from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.industry_report import (
    IndustryDailyReportOut,
    IndustryReportCandidateOut,
    IndustryReportGenerateRequest,
)
from app.services.industry_report_service import (
    add_candidate_to_core_watch,
    generate_industry_report,
    get_industry_report,
)
from app.services.message_service import today_yyyymmdd

router = APIRouter(prefix="/api/industry-reports", tags=["industry-reports"])


def _report_out(report, candidates) -> IndustryDailyReportOut:
    data = IndustryDailyReportOut.model_validate(report)
    data.candidates = [IndustryReportCandidateOut.model_validate(row) for row in candidates]
    return data


@router.get("/daily", response_model=Optional[IndustryDailyReportOut])
def get_daily_report(
    trade_date: str | None = Query(default=None, pattern=r"^\d{8}$"),
    db: Session = Depends(get_db),
):
    report, candidates = get_industry_report(db, trade_date or today_yyyymmdd())
    if not report:
        return None
    return _report_out(report, candidates)


@router.post("/generate", response_model=IndustryDailyReportOut)
def generate_report(body: IndustryReportGenerateRequest, db: Session = Depends(get_db)):
    report = generate_industry_report(
        db,
        trade_date=body.trade_date,
        refresh_seeds=body.refresh_seeds,
        use_llm=body.use_llm,
    )
    _, candidates = get_industry_report(db, report.trade_date)
    return _report_out(report, candidates)


@router.get("/candidates", response_model=list[IndustryReportCandidateOut])
def list_candidates(
    trade_date: str | None = Query(default=None, pattern=r"^\d{8}$"),
    db: Session = Depends(get_db),
):
    _, candidates = get_industry_report(db, trade_date or today_yyyymmdd())
    return candidates


@router.post("/candidates/{candidate_id}/add-to-pool")
def add_to_pool(candidate_id: str, db: Session = Depends(get_db)):
    try:
        return add_candidate_to_core_watch(db, candidate_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
