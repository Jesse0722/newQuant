import time
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models.stock import StockBasic, DailyQuote
from app.models.pool import WatchStock
from app.services.tushare_adapter import tushare_adapter
from app.tasks.background import task_registry


def _get_trade_dates(days: int = 60) -> list[str]:
    """获取最近 N 个交易日日期（YYYYMMDD）"""
    dates = []
    d = datetime.now()
    while len(dates) < days:
        s = d.strftime("%Y%m%d")
        if d.weekday() < 5:
            dates.append(s)
        d -= timedelta(days=1)
    return dates


def _sync_stock_basic_full(db: Session) -> int:
    """同步全市场 stock_basic，返回同步数量"""
    df = tushare_adapter.get_stock_basic()
    if df.empty:
        return 0
    count = 0
    for _, row in df.iterrows():
        existing = db.query(StockBasic).filter(StockBasic.ts_code == row["ts_code"]).first()
        if existing:
            for col in df.columns:
                if hasattr(existing, col):
                    setattr(existing, col, row[col])
        else:
            db.add(StockBasic(**row.to_dict()))
            count += 1
    db.commit()
    return count


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


def sync_full_market(task_id: str, days: int = 60):
    """全市场 60 日 K 线增量同步（后台线程调用）"""
    task = task_registry.get(task_id)
    if not task:
        return
    db = SessionLocal()
    success_count = 0
    failed_count = 0
    skipped_count = 0
    failed_dates: list[dict] = []
    try:
        task.message = "正在同步股票基础信息..."
        _sync_stock_basic_full(db)
        dates = _get_trade_dates(days)
        total_days = len(dates)
        for i, trade_date in enumerate(dates):
            task.progress = (i + 1) / total_days if total_days else 1.0
            task.message = f"同步 {trade_date} ({i+1}/{total_days})"
            try:
                df = tushare_adapter.get_daily_by_date(trade_date)
                if df.empty:
                    continue
                day_success, day_skipped = 0, 0
                for _, row in df.iterrows():
                    existing = db.query(DailyQuote).filter(
                        DailyQuote.ts_code == row["ts_code"],
                        DailyQuote.trade_date == row["trade_date"],
                    ).first()
                    if existing:
                        day_skipped += 1
                    else:
                        db.add(DailyQuote(**row.to_dict()))
                        day_success += 1
                db.commit()
                success_count += day_success
                skipped_count += day_skipped
            except Exception as e:
                failed_count += 1
                failed_dates.append({"date": trade_date, "message": str(e)})
            time.sleep(0.15)
        msg = f"同步完成：成功 {success_count} 条，跳过 {skipped_count} 条，失败 {failed_count} 天"
        task.result = {
            "success_count": success_count,
            "failed_count": failed_count,
            "skipped_count": skipped_count,
            "days_synced": total_days,
            "failed_dates": failed_dates,
            "message": msg,
        }
        task.status = "completed"
        task.progress = 1.0
        task.message = msg
    except Exception as e:
        task.status = "failed"
        task.message = str(e)
        task.result = {
            "success_count": success_count,
            "failed_count": failed_count,
            "skipped_count": skipped_count,
            "days_synced": 0,
            "failed_dates": failed_dates,
            "message": str(e),
        }
    finally:
        db.close()
