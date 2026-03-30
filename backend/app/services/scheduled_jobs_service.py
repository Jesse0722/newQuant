import json
import uuid
from datetime import datetime

from app.database import SessionLocal
from app.models.pool import WatchStock
from app.models.stock import DailyQuote
from app.models.sync_log import SyncLog
from app.services.limit_up_service import get_or_create_limit_up_pool, collect_limit_up_stocks
from app.services.trade_date_resolver import resolve_dashboard_trade_date
from app.services.sync_service import _sync_stock_basic_full, sync_stock_info, sync_daily


def run_4pm_collect_limit_up_job() -> dict:
    """
    每日 16:00 任务：
    拉取当日涨停股票（排除 ST，包含一字板）。
    """
    db = SessionLocal()
    log_id = str(uuid.uuid4())
    try:
        db.add(
            SyncLog(
                id=log_id,
                task_type="scheduled_limit_up_collect",
                target=None,
                status="running",
            )
        )
        db.commit()

        try:
            _sync_stock_basic_full(db)
        except Exception:
            pass
        pool = get_or_create_limit_up_pool(db)
        trade_date = resolve_dashboard_trade_date()
        result = collect_limit_up_stocks(
            db=db,
            trade_date=trade_date,
            pool_id=pool.id,
            exclude_one_word_limit=False,  # 定时任务要求：包含一字板
        )
        resp = {
            "job": "collect_limit_up",
            "trade_date": trade_date,
            "pool_id": pool.id,
            "pool_name": pool.name,
            **result,
        }
        log = db.query(SyncLog).filter(SyncLog.id == log_id).first()
        if log:
            log.status = "completed"
            log.completed_at = datetime.utcnow()
            log.result = json.dumps(
                {
                    "success_count": result.get("added", 0) + result.get("updated", 0),
                    "failed_count": len(result.get("errors", [])),
                    "skipped_count": result.get("skipped", 0),
                    "days_synced": 1,
                    "message": f"16:00 涨停采集完成：新增 {result.get('added', 0)}，更新 {result.get('updated', 0)}",
                    **result,
                },
                ensure_ascii=False,
            )
            db.commit()
        return resp
    except Exception as e:
        log = db.query(SyncLog).filter(SyncLog.id == log_id).first()
        if log:
            log.status = "failed"
            log.completed_at = datetime.utcnow()
            log.result = json.dumps(
                {
                    "success_count": 0,
                    "failed_count": 1,
                    "skipped_count": 0,
                    "days_synced": 1,
                    "message": str(e),
                },
                ensure_ascii=False,
            )
            db.commit()
        raise
    finally:
        db.close()


def run_5pm_sync_latest_kline_job() -> dict:
    """
    每日 17:00 任务：
    同步观察池中所有股票最新日线，尽量补齐到今天。
    """
    db = SessionLocal()
    log_id = str(uuid.uuid4())
    try:
        db.add(
            SyncLog(
                id=log_id,
                task_type="scheduled_latest_kline_sync",
                target=None,
                status="running",
            )
        )
        db.commit()

        today = datetime.now().strftime("%Y%m%d")
        rows = db.query(WatchStock.ts_code).distinct().all()
        ts_codes = [r[0] for r in rows if r and r[0]]

        synced = 0
        up_to_date = 0
        errors: list[str] = []

        for ts_code in ts_codes:
            try:
                latest_before_row = (
                    db.query(DailyQuote.trade_date)
                    .filter(DailyQuote.ts_code == ts_code)
                    .order_by(DailyQuote.trade_date.desc())
                    .first()
                )
                latest_before = latest_before_row[0] if latest_before_row else None

                sync_stock_info(db, ts_code)
                sync_daily(db, ts_code, days=250)

                latest_after_row = (
                    db.query(DailyQuote.trade_date)
                    .filter(DailyQuote.ts_code == ts_code)
                    .order_by(DailyQuote.trade_date.desc())
                    .first()
                )
                latest_after = latest_after_row[0] if latest_after_row else None

                synced += 1
                if latest_after == today:
                    up_to_date += 1
            except Exception as e:
                errors.append(f"{ts_code}: {str(e)[:120]}")
                continue

        resp = {
            "job": "sync_latest_kline",
            "trade_date": today,
            "total_stocks": len(ts_codes),
            "synced_stocks": synced,
            "today_up_to_date": up_to_date,
            "errors": errors[:50],
        }
        log = db.query(SyncLog).filter(SyncLog.id == log_id).first()
        if log:
            log.status = "completed"
            log.completed_at = datetime.utcnow()
            log.result = json.dumps(
                {
                    "success_count": synced,
                    "failed_count": len(errors),
                    "skipped_count": max(0, len(ts_codes) - synced),
                    "days_synced": 1,
                    "message": f"17:00 最新K线补齐完成：成功 {synced}，失败 {len(errors)}",
                    **resp,
                },
                ensure_ascii=False,
            )
            db.commit()
        return resp
    except Exception as e:
        log = db.query(SyncLog).filter(SyncLog.id == log_id).first()
        if log:
            log.status = "failed"
            log.completed_at = datetime.utcnow()
            log.result = json.dumps(
                {
                    "success_count": 0,
                    "failed_count": 1,
                    "skipped_count": 0,
                    "days_synced": 1,
                    "message": str(e),
                },
                ensure_ascii=False,
            )
            db.commit()
        raise
    finally:
        db.close()

