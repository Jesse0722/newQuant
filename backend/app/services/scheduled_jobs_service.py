from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timedelta

from sqlalchemy import func
from app.database import SessionLocal
from app.models.sector import StockSectorMap
from app.models.pool import WatchStock
from app.models.stock import DailyQuote
from app.models.sync_log import SyncLog
from app.models.intraday_scan import IntradayScanConfig
from app.config import (
    IDLE_KLINE_BACKFILL_BATCH_SIZE,
    IDLE_KLINE_BACKFILL_DAYS,
    IDLE_KLINE_BACKFILL_MAX_SECONDS,
    IDLE_KLINE_BACKFILL_RETRY_COOLDOWN_HOURS,
    IDLE_KLINE_BACKFILL_TARGET_ROWS,
    IDLE_MAIN_WAVE_CONCEPT_BACKFILL_BATCH_SIZE,
    IDLE_MAIN_WAVE_CONCEPT_BACKFILL_MAX_SECONDS,
    IDLE_MAIN_WAVE_CONCEPT_BACKFILL_RETRY_COOLDOWN_HOURS,
)
from app.services.limit_up_service import get_or_create_limit_up_pool, collect_limit_up_stocks
from app.services.trade_date_resolver import resolve_dashboard_trade_date
from app.services.trading_session import is_a_share_trading_session
from app.services.buy_signal_service import scan_pool_buy_signals
from app.services.main_wave_sector_backfill_service import _ensure_stock_f10_sectors, _get_main_wave_pool
from app.services.sync_service import _sync_stock_basic_full, sync_stock_info, sync_daily, sync_daily_backward
from app.services.industry_report_service import generate_industry_report


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


def _has_kline_sync_running() -> bool:
    from app.tasks.background import task_registry

    kline_task_types = (
        "sync",
        "sync_full_market",
        "idle_pool_kline_backfill",
        "main_wave_sector_backfill",
    )
    return any(
        task.status == "running" and task.type in kline_task_types
        for task in task_registry.values()
    )


def _recent_idle_backfill_attempts(db) -> set[str]:
    threshold = datetime.utcnow() - timedelta(hours=max(1, int(IDLE_KLINE_BACKFILL_RETRY_COOLDOWN_HOURS)))
    logs = (
        db.query(SyncLog.result)
        .filter(
            SyncLog.task_type == "idle_pool_kline_backfill",
            SyncLog.started_at >= threshold,
            SyncLog.result.isnot(None),
        )
        .order_by(SyncLog.started_at.desc())
        .limit(50)
        .all()
    )
    attempted: set[str] = set()
    for (raw,) in logs:
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except Exception:
            continue
        for item in payload.get("items") or []:
            ts_code = item.get("ts_code") if isinstance(item, dict) else None
            if ts_code:
                attempted.add(str(ts_code))
    return attempted


def _recent_main_wave_concept_attempts(db) -> set[str]:
    threshold = datetime.utcnow() - timedelta(
        hours=max(1, int(IDLE_MAIN_WAVE_CONCEPT_BACKFILL_RETRY_COOLDOWN_HOURS))
    )
    logs = (
        db.query(SyncLog.result)
        .filter(
            SyncLog.task_type == "idle_main_wave_concept_backfill",
            SyncLog.started_at >= threshold,
            SyncLog.result.isnot(None),
        )
        .order_by(SyncLog.started_at.desc())
        .limit(50)
        .all()
    )
    attempted: set[str] = set()
    for (raw,) in logs:
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except Exception:
            continue
        for item in payload.get("items") or []:
            ts_code = item.get("ts_code") if isinstance(item, dict) else None
            if ts_code:
                attempted.add(str(ts_code))
    return attempted


def run_idle_main_wave_concept_backfill_job() -> dict:
    """
    空闲时预热主升浪池股票的概念映射。

    主升浪评分需要股票-概念映射和板块 K 线。若在页面扫描时逐股拉 F10，
    会把池内扫描拖到分钟级；这里提前小批量补齐映射，使页面扫描只读本地库。
    """
    result = {
        "job": "idle_main_wave_concept_backfill",
        "ran": False,
        "reason": "",
        "pool_id": None,
        "pool_name": None,
        "total_stocks": 0,
        "missing_candidates": 0,
        "selected_limit": 0,
        "processed": 0,
        "updated": 0,
        "skipped": 0,
        "failed": 0,
        "items": [],
    }
    if is_a_share_trading_session():
        return {**result, "reason": "trading_session"}

    db = SessionLocal()
    log_id = str(uuid.uuid4())
    try:
        if _has_kline_sync_running():
            return {**result, "reason": "kline_or_sector_sync_running"}

        pool = _get_main_wave_pool(db, None)
        if not pool:
            return {**result, "reason": "main_wave_pool_not_found"}
        result["pool_id"] = pool.id
        result["pool_name"] = pool.name

        batch_size = max(1, int(IDLE_MAIN_WAVE_CONCEPT_BACKFILL_BATCH_SIZE))
        max_seconds = max(10, int(IDLE_MAIN_WAVE_CONCEPT_BACKFILL_MAX_SECONDS))
        started = time.monotonic()
        recent_attempts = _recent_main_wave_concept_attempts(db)

        stocks = (
            db.query(WatchStock)
            .filter(WatchStock.pool_id == pool.id)
            .order_by(WatchStock.pinned.desc(), WatchStock.created_at.desc())
            .all()
        )
        result["total_stocks"] = len(stocks)
        candidates = []
        for stock in stocks:
            if stock.ts_code in recent_attempts:
                continue
            mapped_count = (
                db.query(func.count(StockSectorMap.sector_code))
                .filter(StockSectorMap.ts_code == stock.ts_code)
                .scalar()
                or 0
            )
            if int(mapped_count) <= 0:
                candidates.append(stock)

        result["missing_candidates"] = len(candidates)
        selected = candidates[:batch_size]
        result["selected_limit"] = batch_size
        if not selected:
            return {**result, "reason": "no_candidate"}

        db.add(
            SyncLog(
                id=log_id,
                task_type="idle_main_wave_concept_backfill",
                target=pool.id,
                status="running",
            )
        )
        db.commit()

        for stock in selected:
            if time.monotonic() - started >= max_seconds:
                result["reason"] = "time_budget_exhausted"
                break
            before = (
                db.query(func.count(StockSectorMap.sector_code))
                .filter(StockSectorMap.ts_code == stock.ts_code)
                .scalar()
                or 0
            )
            try:
                changed = _ensure_stock_f10_sectors(db, stock.ts_code)
                after = (
                    db.query(func.count(StockSectorMap.sector_code))
                    .filter(StockSectorMap.ts_code == stock.ts_code)
                    .scalar()
                    or 0
                )
                result["processed"] += 1
                if int(after) > int(before):
                    result["updated"] += 1
                else:
                    result["skipped"] += 1
                result["items"].append(
                    {
                        "ts_code": stock.ts_code,
                        "before_count": int(before or 0),
                        "after_count": int(after or 0),
                        "changed": int(changed or 0),
                    }
                )
            except Exception as e:
                result["processed"] += 1
                result["failed"] += 1
                result["items"].append({"ts_code": stock.ts_code, "error": str(e)[:120]})

        result["ran"] = True
        if not result["reason"]:
            result["reason"] = "processed"
        log = db.query(SyncLog).filter(SyncLog.id == log_id).first()
        if log:
            log.status = "completed"
            log.completed_at = datetime.utcnow()
            log.result = json.dumps(
                {
                    "success_count": result["processed"] - result["failed"],
                    "failed_count": result["failed"],
                    "skipped_count": result["skipped"],
                    "days_synced": 0,
                    "message": f"主升浪概念映射预热：处理 {result['processed']}，更新 {result['updated']}，失败 {result['failed']}",
                    **result,
                },
                ensure_ascii=False,
            )
            db.commit()
        return result
    except Exception as e:
        log = db.query(SyncLog).filter(SyncLog.id == log_id).first()
        if log:
            log.status = "failed"
            log.completed_at = datetime.utcnow()
            log.result = json.dumps(
                {
                    "success_count": result["processed"] - result["failed"],
                    "failed_count": result["failed"] + 1,
                    "skipped_count": result["skipped"],
                    "days_synced": 0,
                    "message": str(e),
                    **result,
                },
                ensure_ascii=False,
            )
            db.commit()
        raise
    finally:
        db.close()


def run_idle_pool_kline_backfill_job() -> dict:
    """
    空闲时小批量补齐观察池股票 K 线。

    目标是把用户可能点开的池内股票提前补到可画图的深度，避免详情页或列表预览
    临时触发同步。任务只在非交易时段由 scheduler 调用，并且每次只处理少量股票。
    """
    result = {
        "job": "idle_pool_kline_backfill",
        "ran": False,
        "reason": "",
        "total_candidates": 0,
        "stale_candidates": 0,
        "shallow_candidates": 0,
        "selected_limit": 0,
        "processed": 0,
        "updated": 0,
        "skipped": 0,
        "failed": 0,
        "items": [],
    }
    if is_a_share_trading_session():
        return {**result, "reason": "trading_session"}

    db = SessionLocal()
    log_id = str(uuid.uuid4())
    try:
        if _has_kline_sync_running():
            return {**result, "reason": "recent_kline_sync_running"}

        latest_trade_date = resolve_dashboard_trade_date()
        target_rows = max(60, int(IDLE_KLINE_BACKFILL_TARGET_ROWS))
        batch_size = max(1, int(IDLE_KLINE_BACKFILL_BATCH_SIZE))
        days = max(60, int(IDLE_KLINE_BACKFILL_DAYS))
        max_seconds = max(15, int(IDLE_KLINE_BACKFILL_MAX_SECONDS))
        started = time.monotonic()
        recent_attempts = _recent_idle_backfill_attempts(db)
        abandoned_before = datetime.utcnow() - timedelta(seconds=max_seconds * 3)
        abandoned_logs = (
            db.query(SyncLog)
            .filter(
                SyncLog.task_type == "idle_pool_kline_backfill",
                SyncLog.status == "running",
                SyncLog.started_at < abandoned_before,
            )
            .all()
        )
        for log in abandoned_logs:
            log.status = "failed"
            log.completed_at = datetime.utcnow()
            log.result = json.dumps(
                {
                    "success_count": 0,
                    "failed_count": 1,
                    "skipped_count": 0,
                    "days_synced": days,
                    "message": "空闲K线补齐任务未正常收尾，已标记为中断",
                    "job": "idle_pool_kline_backfill",
                    "ran": False,
                    "reason": "abandoned",
                },
                ensure_ascii=False,
            )
        if abandoned_logs:
            db.commit()

        grouped = (
            db.query(
                WatchStock.ts_code,
                func.count(DailyQuote.trade_date).label("quote_count"),
                func.max(DailyQuote.trade_date).label("latest_trade_date"),
            )
            .outerjoin(DailyQuote, DailyQuote.ts_code == WatchStock.ts_code)
            .group_by(WatchStock.ts_code)
            .all()
        )
        candidates = []
        for ts_code, quote_count, latest in grouped:
            if not ts_code:
                continue
            if ts_code in recent_attempts:
                continue
            count = int(quote_count or 0)
            stale = not latest or str(latest) < latest_trade_date
            shallow = count < target_rows
            if stale or shallow:
                candidates.append(
                    {
                        "ts_code": ts_code,
                        "quote_count": count,
                        "latest_trade_date": latest,
                        "stale": stale,
                        "shallow": shallow,
                    }
                )
        def market_priority(ts_code: str) -> int:
            code = str(ts_code or "").upper()
            if code.endswith(".SZ") or code.endswith(".SH"):
                return 0
            if code.endswith(".BJ"):
                return 1
            return 2

        stale_candidates = [item for item in candidates if item["stale"]]
        shallow_candidates = [item for item in candidates if not item["stale"] and item["shallow"]]
        stale_candidates.sort(
            key=lambda item: (
                market_priority(item["ts_code"]),
                item["latest_trade_date"] or "",
                item["quote_count"],
                item["ts_code"],
            )
        )
        shallow_candidates.sort(
            key=lambda item: (
                market_priority(item["ts_code"]),
                item["quote_count"],
                item["latest_trade_date"] or "",
                item["ts_code"],
            )
        )
        selected_limit = min(max(batch_size, batch_size * 5 if stale_candidates else batch_size), 20)
        selected = (stale_candidates + shallow_candidates)[:selected_limit]
        result["total_candidates"] = len(candidates)
        result["stale_candidates"] = len(stale_candidates)
        result["shallow_candidates"] = len(shallow_candidates)
        result["selected_limit"] = selected_limit

        if not selected:
            return {**result, "reason": "no_candidate"}

        db.add(
            SyncLog(
                id=log_id,
                task_type="idle_pool_kline_backfill",
                target=None,
                status="running",
            )
        )
        db.commit()

        for item in selected:
            if time.monotonic() - started >= max_seconds:
                result["reason"] = "time_budget_exhausted"
                break
            ts_code = item["ts_code"]
            try:
                sync_stock_info(db, ts_code)
                added_recent = sync_daily(db, ts_code, days)
                count_after = (
                    db.query(func.count(DailyQuote.trade_date))
                    .filter(DailyQuote.ts_code == ts_code)
                    .scalar()
                    or 0
                )
                latest_after_row = (
                    db.query(func.max(DailyQuote.trade_date))
                    .filter(DailyQuote.ts_code == ts_code)
                    .first()
                )
                latest_after = latest_after_row[0] if latest_after_row else None
                added_backward = 0
                if not item["stale"] and int(count_after) < target_rows:
                    added_backward = sync_daily_backward(db, ts_code, target_rows)
                    count_after = (
                        db.query(func.count(DailyQuote.trade_date))
                        .filter(DailyQuote.ts_code == ts_code)
                        .scalar()
                        or 0
                    )
                    latest_after_row = (
                        db.query(func.max(DailyQuote.trade_date))
                        .filter(DailyQuote.ts_code == ts_code)
                        .first()
                    )
                    latest_after = latest_after_row[0] if latest_after_row else latest_after
                added_total = int(added_recent or 0) + int(added_backward or 0)
                latest_improved = str(latest_after or "") > str(item["latest_trade_date"] or "")
                result["processed"] += 1
                if added_total > 0 or latest_improved:
                    result["updated"] += 1
                else:
                    result["skipped"] += 1
                result["items"].append(
                    {
                        "ts_code": ts_code,
                        "before_count": item["quote_count"],
                        "after_count": int(count_after or 0),
                        "before_latest_trade_date": item["latest_trade_date"],
                        "after_latest_trade_date": latest_after,
                        "stale": item["stale"],
                        "shallow": item["shallow"],
                        "added_recent": int(added_recent or 0),
                        "added_backward": int(added_backward or 0),
                    }
                )
            except Exception as e:
                result["processed"] += 1
                result["failed"] += 1
                result["items"].append({"ts_code": ts_code, "error": str(e)[:120]})

        result["ran"] = True
        if not result["reason"] or result["reason"] == "":
            result["reason"] = "processed"
        log = db.query(SyncLog).filter(SyncLog.id == log_id).first()
        if log:
            log.status = "completed"
            log.completed_at = datetime.utcnow()
            log.result = json.dumps(
                {
                    "success_count": result["processed"] - result["failed"],
                    "failed_count": result["failed"],
                    "skipped_count": result["skipped"],
                    "days_synced": days,
                    "message": f"空闲K线补齐：处理 {result['processed']}，更新 {result['updated']}，失败 {result['failed']}",
                    **result,
                },
                ensure_ascii=False,
            )
            db.commit()
        return result
    except Exception as e:
        log = db.query(SyncLog).filter(SyncLog.id == log_id).first()
        if log:
            log.status = "failed"
            log.completed_at = datetime.utcnow()
            log.result = json.dumps(
                {
                    "success_count": result["processed"] - result["failed"],
                    "failed_count": result["failed"] + 1,
                    "skipped_count": result["skipped"],
                    "days_synced": IDLE_KLINE_BACKFILL_DAYS,
                    "message": str(e),
                    **result,
                },
                ensure_ascii=False,
            )
            db.commit()
        raise
    finally:
        db.close()


def run_industry_report_job(session: str = "scheduled") -> dict:
    """
    产业链日报任务：
    - 盘前生成当日观察主线
    - 盘后刷新当日候选与风险
    """
    db = SessionLocal()
    log_id = str(uuid.uuid4())
    try:
        db.add(
            SyncLog(
                id=log_id,
                task_type=f"industry_report_{session}",
                target=None,
                status="running",
            )
        )
        db.commit()
        report = generate_industry_report(db, refresh_seeds=True)
        candidate_count = int((report.report_json or {}).get("candidate_count") or 0) if isinstance(report.report_json, dict) else 0
        resp = {
            "job": "industry_report",
            "session": session,
            "trade_date": report.trade_date,
            "report_id": report.id,
            "candidate_count": candidate_count,
            "headline": report.headline,
        }
        log = db.query(SyncLog).filter(SyncLog.id == log_id).first()
        if log:
            log.status = "completed"
            log.completed_at = datetime.utcnow()
            log.result = json.dumps(
                {
                    "success_count": candidate_count,
                    "failed_count": 0,
                    "skipped_count": 0,
                    "days_synced": 0,
                    "message": f"产业链日报生成完成：{candidate_count} 个候选",
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
                    "days_synced": 0,
                    "message": str(e),
                },
                ensure_ascii=False,
            )
            db.commit()
        raise
    finally:
        db.close()


def run_intraday_scan_job() -> dict:
    """
    盘中轮询扫描任务：
    - 仅在交易时段执行
    - 按每个配置的 interval_minutes 触发
    """
    db = SessionLocal()
    now = datetime.now()
    result = {
        "job": "intraday_scan",
        "ran": 0,
        "skipped": 0,
        "errors": [],
        "time": now.isoformat(),
    }
    if not is_a_share_trading_session():
        db.close()
        return {**result, "reason": "out_of_session"}

    log_id = str(uuid.uuid4())
    try:
        db.add(
            SyncLog(
                id=log_id,
                task_type="scheduled_intraday_scan",
                target=None,
                status="running",
            )
        )
        db.commit()

        cfgs = (
            db.query(IntradayScanConfig)
            .filter(IntradayScanConfig.enabled.is_(True))
            .all()
        )
        for cfg in cfgs:
            interval = max(1, int(cfg.interval_minutes or 5))
            if now.minute % interval != 0:
                result["skipped"] += 1
                continue
            try:
                out = scan_pool_buy_signals(
                    db,
                    cfg.pool_id,
                    cfg.strategy_id,
                    min_confirm_hits=int(cfg.min_confirm_hits or 2),
                )
                result["ran"] += 1
                if out.get("realtime", {}).get("error"):
                    result["errors"].append(
                        f"{cfg.pool_id}/{cfg.strategy_id}: {out['realtime']['error'][:100]}"
                    )
            except Exception as e:
                result["errors"].append(f"{cfg.pool_id}/{cfg.strategy_id}: {str(e)[:120]}")

        log = db.query(SyncLog).filter(SyncLog.id == log_id).first()
        if log:
            log.status = "completed"
            log.completed_at = datetime.utcnow()
            log.result = json.dumps(
                {
                    "success_count": result["ran"],
                    "failed_count": len(result["errors"]),
                    "skipped_count": result["skipped"],
                    "days_synced": 0,
                    "message": f"盘中扫描：执行 {result['ran']}，跳过 {result['skipped']}",
                    **result,
                },
                ensure_ascii=False,
            )
            db.commit()
        return result
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
                    "days_synced": 0,
                    "message": str(e),
                },
                ensure_ascii=False,
            )
            db.commit()
        raise
    finally:
        db.close()
