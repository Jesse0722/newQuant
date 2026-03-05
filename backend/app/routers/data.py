from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.database import get_db
from app.models.stock import StockBasic, DailyQuote

router = APIRouter(prefix="/api/data", tags=["data"])


@router.get("/summary")
def get_data_summary(db: Session = Depends(get_db)):
    """数据概览：股票数量、行情日期范围、总条数"""
    stock_count = db.query(func.count(StockBasic.ts_code)).scalar() or 0
    total_quotes = db.query(func.count(DailyQuote.ts_code)).scalar() or 0
    date_range = db.query(
        func.min(DailyQuote.trade_date),
        func.max(DailyQuote.trade_date),
    ).first()
    min_date, max_date = date_range[0] if date_range else (None, None)
    return {
        "stock_count": stock_count,
        "total_quotes": total_quotes,
        "quote_date_range": {"min": min_date, "max": max_date},
        "last_sync_at": max_date,
    }
