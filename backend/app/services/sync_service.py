import json
import time
import uuid
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError
from app.database import SessionLocal
from app.models.stock import StockBasic, DailyQuote
from app.models.pool import WatchStock
from app.models.sync_log import SyncLog
from app.services.tushare_adapter import tushare_adapter
from app.tasks.background import task_registry


def _commit_with_retry(db: Session, retries: int = 3, wait_s: float = 0.6):
    """针对 sqlite database is locked 做有限重试。"""
    for i in range(retries):
        try:
            db.commit()
            return
        except OperationalError as e:
            db.rollback()
            msg = str(e).lower()
            if "database is locked" not in msg or i == retries - 1:
                raise
            time.sleep(wait_s * (i + 1))


def _diagnose_empty_daily(trade_date: str, basic_ok: bool) -> str:
    """当日线接口返回空时，尝试诊断原因"""
    try:
        if not basic_ok:
            return "stock_basic 也为空，请检查 TUSHARE_TOKEN 是否有效及网络/代理"
        # 尝试单只股票 daily 接口，验证 daily 权限
        df = tushare_adapter.get_daily(ts_code="000001.SZ", start_date=trade_date, end_date=trade_date)
        if df.empty:
            return "daily 接口返回空，可能需 120 积分或接口权限不足，请登录 tushare.pro 查看"
        return "trade_date 全市场接口返回空，但单股接口正常，可能是代理或限流导致"
    except Exception as e:
        return f"诊断异常: {str(e)[:80]}"


def _get_trade_dates(days: int = 60) -> list[str]:
    """获取最近 N 个交易日日期（YYYYMMDD），从昨天开始（今日数据可能未就绪）"""
    dates = []
    d = datetime.now() - timedelta(days=1)
    while len(dates) < days:
        s = d.strftime("%Y%m%d")
        if d.weekday() < 5:
            dates.append(s)
        d -= timedelta(days=1)
    return dates


def _sync_stock_basic_full(db: Session) -> tuple[int, bool]:
    """同步全市场 stock_basic，返回 (新增数量, API 是否有返回数据)"""
    df = tushare_adapter.get_stock_basic()
    if df.empty:
        return 0, False
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
    _commit_with_retry(db)
    return count, True


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
    _commit_with_retry(db)


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
        return 0

    df = tushare_adapter.get_daily(ts_code=ts_code, start_date=start_date, end_date=end_date)
    if df.empty:
        return 0

    added_count = 0
    for _, row in df.iterrows():
        existing = db.query(DailyQuote).filter(
            DailyQuote.ts_code == row["ts_code"],
            DailyQuote.trade_date == row["trade_date"],
        ).first()
        if not existing:
            db.add(DailyQuote(**row.to_dict()))
            added_count += 1
    _commit_with_retry(db)
    return added_count


def sync_pool(task_id: str, pool_id: str, days: int = 250):
    """同步整个池子（后台线程调用）"""
    db = SessionLocal()
    success_count = 0
    failed_count = 0
    skipped_count = 0
    failed_items: list[dict] = []
    try:
        # 持久化：创建同步记录
        log = SyncLog(
            id=task_id,
            task_type="pool",
            target=pool_id,
            status="running",
        )
        db.add(log)
        db.commit()

        stocks = db.query(WatchStock).filter(WatchStock.pool_id == pool_id).all()
        total = len(stocks)
        for i, ws in enumerate(stocks):
            try:
                sync_stock_info(db, ws.ts_code)
                added = sync_daily(db, ws.ts_code, days)
                success_count += 1
                if added == 0:
                    skipped_count += 1
            except Exception as e:
                failed_count += 1
                failed_items.append({"ts_code": ws.ts_code, "message": str(e)[:120]})
            task_registry[task_id].progress = (i + 1) / total if total else 1.0
            task_registry[task_id].message = f"已同步 {i+1}/{total}"

        task_registry[task_id].result = {
            "success_count": success_count,
            "failed_count": failed_count,
            "skipped_count": skipped_count,
            "days_synced": days,
            "failed_items": failed_items[:50],
            "message": f"池同步完成：成功 {success_count}，失败 {failed_count}，无新增 {skipped_count}",
        }

        # 持久化：更新同步记录
        log = db.query(SyncLog).filter(SyncLog.id == task_id).first()
        if log:
            log.status = "completed"
            log.completed_at = datetime.utcnow()
            log.result = json.dumps(task_registry[task_id].result, ensure_ascii=False)
            db.commit()

        # 同步完成后自动触发监控扫描
        from app.services.monitor_engine import scan_pool as _scan_pool
        from app.tasks.background import submit_task as _submit
        _submit("scan", _scan_pool, pool_id)
    except Exception as e:
        task_registry[task_id].result = {
            "success_count": success_count,
            "failed_count": failed_count + 1,
            "skipped_count": skipped_count,
            "days_synced": days,
            "failed_items": failed_items[:50],
            "message": str(e),
        }
        log = db.query(SyncLog).filter(SyncLog.id == task_id).first()
        if log:
            log.status = "failed"
            log.completed_at = datetime.utcnow()
            log.result = json.dumps(task_registry[task_id].result, ensure_ascii=False)
            db.commit()
        raise
    finally:
        db.close()


def sync_single_stock(task_id: str, ts_code: str, days: int = 250):
    """同步单只股票（后台线程调用）"""
    db = SessionLocal()
    try:
        # 持久化：创建同步记录
        log = SyncLog(
            id=task_id,
            task_type="stock",
            target=ts_code,
            status="running",
        )
        db.add(log)
        db.commit()

        sync_stock_info(db, ts_code)
        added = sync_daily(db, ts_code, days)
        task_registry[task_id].progress = 1.0
        task_registry[task_id].message = f"{ts_code} 同步完成"
        task_registry[task_id].result = {
            "success_count": 1,
            "failed_count": 0,
            "skipped_count": 1 if added == 0 else 0,
            "days_synced": days,
            "message": f"{ts_code} 同步完成，新增 {added} 条",
        }

        log = db.query(SyncLog).filter(SyncLog.id == task_id).first()
        if log:
            log.status = "completed"
            log.completed_at = datetime.utcnow()
            log.result = json.dumps(task_registry[task_id].result, ensure_ascii=False)
            db.commit()
    except Exception as e:
        task_registry[task_id].result = {
            "success_count": 0,
            "failed_count": 1,
            "skipped_count": 0,
            "days_synced": days,
            "message": str(e),
        }
        log = db.query(SyncLog).filter(SyncLog.id == task_id).first()
        if log:
            log.status = "failed"
            log.completed_at = datetime.utcnow()
            log.result = json.dumps(task_registry[task_id].result, ensure_ascii=False)
            db.commit()
        raise
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
        # 持久化：创建同步记录
        log = SyncLog(
            id=task_id,
            task_type="full_market",
            target=None,
            status="running",
        )
        db.add(log)
        db.commit()

        task.message = "正在同步股票基础信息..."
        _, basic_ok = _sync_stock_basic_full(db)
        dates = _get_trade_dates(days)
        total_days = len(dates)
        first_empty_reason = None
        for i, trade_date in enumerate(dates):
            task.progress = (i + 1) / total_days if total_days else 1.0
            task.message = f"同步 {trade_date} ({i+1}/{total_days})"
            try:
                df = tushare_adapter.get_daily_by_date(trade_date)
                if df.empty:
                    if first_empty_reason is None:
                        first_empty_reason = _diagnose_empty_daily(trade_date, basic_ok)
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
        result = {
            "success_count": success_count,
            "failed_count": failed_count,
            "skipped_count": skipped_count,
            "days_synced": total_days,
            "failed_dates": failed_dates,
            "message": msg,
        }
        if success_count == 0 and failed_count == 0 and first_empty_reason:
            result["diagnostic"] = first_empty_reason
            msg += f" | {first_empty_reason}"
        task.result = result
        task.status = "completed"
        task.progress = 1.0
        task.message = msg

        # 持久化：更新同步记录
        log = db.query(SyncLog).filter(SyncLog.id == task_id).first()
        if log:
            log.status = "completed"
            log.completed_at = datetime.utcnow()
            log.result = json.dumps(task.result, ensure_ascii=False)
            db.commit()
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
        # 持久化：更新为失败
        log = db.query(SyncLog).filter(SyncLog.id == task_id).first()
        if log:
            log.status = "failed"
            log.completed_at = datetime.utcnow()
            log.result = json.dumps(task.result, ensure_ascii=False)
            db.commit()
    finally:
        db.close()
