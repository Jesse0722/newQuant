import json
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.database import get_db
from app.models.stock import StockBasic, DailyQuote
from app.models.sync_log import SyncLog

router = APIRouter(prefix="/api/data", tags=["data"])


@router.get("/sync-history")
def get_sync_history(task_type: str = "full_market", limit: int = 5, db: Session = Depends(get_db)):
    """获取同步记录列表，用于页面展示上次同步结果"""
    rows = (
        db.query(SyncLog)
        .filter(SyncLog.task_type == task_type)
        .order_by(SyncLog.started_at.desc())
        .limit(limit)
        .all()
    )
    out = []
    for r in rows:
        item = {
            "id": r.id,
            "task_type": r.task_type,
            "status": r.status,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "completed_at": r.completed_at.isoformat() if r.completed_at else None,
        }
        if r.result:
            try:
                item["result"] = json.loads(r.result)
            except Exception:
                item["result"] = {}
        else:
            item["result"] = {}
        out.append(item)
    return out


@router.get("/summary")
def get_data_summary(db: Session = Depends(get_db)):
    """数据概览：股票数量、行情日期范围、总条数"""
    stock_count = db.query(func.count(StockBasic.ts_code)).scalar() or 0
    total_quotes = db.query(func.count(DailyQuote.ts_code)).scalar() or 0
    date_range = db.query(
        func.min(DailyQuote.trade_date),
        func.max(DailyQuote.trade_date),
    ).first()
    min_date, max_date = (date_range[0], date_range[1]) if date_range else (None, None)
    return {
        "stock_count": stock_count,
        "total_quotes": total_quotes,
        "quote_date_range": {"min": min_date, "max": max_date},
        "last_sync_at": max_date,
    }
