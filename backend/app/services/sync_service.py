from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models.stock import StockBasic, DailyQuote
from app.models.pool import WatchStock
from app.services.tushare_adapter import tushare_adapter
from app.tasks.background import task_registry


def sync_stock_info(db: Session, ts_code: str):
    """同步单只股票基础信息（upsert）"""
    df = tushare_adapter.get_stock_basic(ts_code=ts_code)
    if df.empty:
        return
    row = df.iloc[0]
    existing = db.query(StockBasic).filter(StockBasic.ts_code == ts_code).first()
    if existing:
        for col in df.columns:
            setattr(existing, col, row[col])
    else:
        db.add(StockBasic(**row.to_dict()))
    db.commit()


def sync_daily(db: Session, ts_code: str, days: int = 250):
    """增量同步日线行情"""
    latest = db.query(DailyQuote.trade_date).filter(
        DailyQuote.ts_code == ts_code
    ).order_by(DailyQuote.trade_date.desc()).first()

    if latest:
        start_date = (datetime.strptime(latest[0], "%Y%m%d") + timedelta(days=1)).strftime("%Y%m%d")
    else:
        start_date = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")

    end_date = datetime.now().strftime("%Y%m%d")
    if start_date > end_date:
        return

    df = tushare_adapter.get_daily(ts_code=ts_code, start_date=start_date, end_date=end_date)
    if df.empty:
        return

    for _, row in df.iterrows():
        existing = db.query(DailyQuote).filter(
            DailyQuote.ts_code == row["ts_code"],
            DailyQuote.trade_date == row["trade_date"],
        ).first()
        if not existing:
            db.add(DailyQuote(**row.to_dict()))
    db.commit()


def sync_pool(task_id: str, pool_id: str, days: int = 250):
    """同步整个池子（后台线程调用）"""
    db = SessionLocal()
    try:
        stocks = db.query(WatchStock).filter(WatchStock.pool_id == pool_id).all()
        total = len(stocks)
        for i, ws in enumerate(stocks):
            try:
                sync_stock_info(db, ws.ts_code)
                sync_daily(db, ws.ts_code, days)
            except Exception:
                pass
            task_registry[task_id].progress = (i + 1) / total if total else 1.0
            task_registry[task_id].message = f"已同步 {i+1}/{total}"
        # 同步完成后自动触发监控扫描
        from app.services.monitor_engine import scan_pool as _scan_pool
        from app.tasks.background import submit_task as _submit
        _submit("scan", _scan_pool, pool_id)
    finally:
        db.close()


def sync_single_stock(task_id: str, ts_code: str, days: int = 250):
    """同步单只股票（后台线程调用）"""
    db = SessionLocal()
    try:
        sync_stock_info(db, ts_code)
        sync_daily(db, ts_code, days)
        task_registry[task_id].progress = 1.0
        task_registry[task_id].message = f"{ts_code} 同步完成"
    finally:
        db.close()
