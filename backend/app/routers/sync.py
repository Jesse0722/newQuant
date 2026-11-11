from __future__ import annotations

import json
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.sync_log import SyncLog
from app.models.task import BackgroundTask, ScheduledJobRun
from app.services.sync_service import sync_pool, sync_single_stock, sync_full_market
from app.tasks.background import submit_task, get_task_status
from app.exceptions import AppError

router = APIRouter(prefix="/api/sync", tags=["sync"])


def _result_link(task_type: str, result: dict | None = None) -> str:
    if "message" in task_type or "industry_report" in task_type:
        return "/messages"
    if "intraday" in task_type or "buy_signal" in task_type or task_type == "strategy_backtest":
        return "/buy-radar"
    if "strategy" in task_type or "screen" in task_type or "main_wave" in task_type:
        return "/strategy"
    if result and result.get("ts_code"):
        return f"/stocks/{result['ts_code']}"
    return "/data"


@router.get("/tasks/recent")
def recent_tasks(size: int = Query(50, ge=1, le=100), db: Session = Depends(get_db)):
    """Read-only history for the task inbox, including independent scheduler jobs."""
    from app.tasks import background
    background.recover_interrupted_tasks()
    records = {}

    def add(identifier, kind, status, message, created, updated, result, source):
        records[identifier] = {"id": identifier, "task_id": identifier,
            "type": kind, "status": status, "message": message or "",
            "created_at": created.isoformat() + "Z", "updated_at": updated.isoformat() + "Z",
            "result": result, "source": source, "link": _result_link(kind, result)}

    for row in db.query(SyncLog).order_by(SyncLog.started_at.desc()).limit(size).all():
        try:
            result = json.loads(row.result) if row.result else None
        except (ValueError, TypeError):
            result = {"message": row.result}
        if not isinstance(result, dict):
            result = {"value": result}
        add(row.id, row.task_type, row.status, result.get("message", ""), row.started_at,
            row.completed_at or row.started_at, result, "sync_log")
    with background.SessionLocal() as storage:
        for row in storage.query(BackgroundTask).order_by(BackgroundTask.updated_at.desc()).limit(size).all():
            add(row.id, row.type, row.status, row.message, row.created_at, row.updated_at,
                row.result, "background")
        for row in storage.query(ScheduledJobRun).order_by(ScheduledJobRun.started_at.desc()).limit(size).all():
            add("scheduled:" + row.id, row.job_key, row.status, row.error or "", row.started_at,
                row.completed_at or row.started_at, {"slot": row.slot, "error": row.error}, "scheduler")
    return {"items": sorted(records.values(), key=lambda item: item["updated_at"], reverse=True)[:size]}


@router.post("/pool/{pool_id}")
def sync_pool_route(pool_id: str, days: int = 250):
    task_id = submit_task("sync", sync_pool, pool_id, days)
    return {"task_id": task_id}


@router.post("/stock/{ts_code}")
def sync_stock_route(ts_code: str, days: int = 250):
    task_id = submit_task("sync", sync_single_stock, ts_code, days)
    return {"task_id": task_id}


@router.post("/full-market")
def sync_full_market_route(days: int = Query(60, ge=1, le=250, description="同步最近 N 个交易日"),
                           end_date: str | None = Query(None, pattern=r"^\d{8}$")):
    """全市场 K 线增量同步"""
    task_id = submit_task("sync_full_market", sync_full_market, days, end_date)
    return {"task_id": task_id}


@router.get("/full-market/capabilities")
def full_market_capabilities():
    from app.services.market_data_capabilities import capability_report
    from app.services.tushare_adapter import tushare_adapter
    return {"providers": capability_report(tushare_adapter), "write_policy": "insert_missing_only",
            "universe_basis": "local_current_master_proxy", "market_coverage_ratio": None}


@router.get("/status/{task_id}")
def get_status(task_id: str):
    status = get_task_status(task_id)
    if not status:
        raise AppError(code=1004, message="任务不存在", status_code=404)
    resp = {
        "task_id": status.id,
        "status": status.status,
        "progress": status.progress,
        "message": status.message,
    }
    if status.result:
        resp["result"] = status.result
    return resp
