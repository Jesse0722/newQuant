from fastapi import APIRouter
from app.services.sync_service import sync_pool, sync_single_stock, sync_full_market
from app.tasks.background import submit_task, get_task_status
from app.exceptions import AppError

router = APIRouter(prefix="/api/sync", tags=["sync"])


@router.post("/pool/{pool_id}")
def sync_pool_route(pool_id: str, days: int = 250):
    task_id = submit_task("sync", sync_pool, pool_id, days)
    return {"task_id": task_id}


@router.post("/stock/{ts_code}")
def sync_stock_route(ts_code: str, days: int = 250):
    task_id = submit_task("sync", sync_single_stock, ts_code, days)
    return {"task_id": task_id}


@router.post("/full-market")
def sync_full_market_route(days: int = 60):
    """全市场 60 日 K 线增量同步"""
    task_id = submit_task("sync_full_market", sync_full_market, days)
    return {"task_id": task_id}


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
