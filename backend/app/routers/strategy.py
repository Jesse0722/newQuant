from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.schemas.strategy import IndicatorScreenRequest, AiScreenRequest, ScreenResult
from app.services.strategy_service import run_indicator_screen, SCREEN_TEMPLATES
from app.services.ai_screen_service import run_ai_screen
from app.services.limit_up_service import (
    get_or_create_limit_up_pool,
    collect_limit_up_stocks,
    _get_trade_dates,
)
from app.services.sync_service import sync_single_stock
from app.tasks.background import submit_task
from app.tasks.background import submit_task, get_task_status
from app.exceptions import AppError

router = APIRouter(prefix="/api/strategy", tags=["strategy"])


@router.get("/templates")
def list_screen_templates():
    """获取指标选股模板列表"""
    return [
        {"id": k, "name": v["name"], "default_params": v["params"]}
        for k, v in SCREEN_TEMPLATES.items()
    ]


@router.post("/screen")
def run_screen(body: IndicatorScreenRequest):
    """提交指标组合选股任务"""
    conditions = [c.model_dump() for c in body.conditions]
    task_id = submit_task("strategy", run_indicator_screen, body.scope, conditions, body.logic)
    return {"task_id": task_id}


@router.post("/ai-screen")
def run_ai_screen_task(body: AiScreenRequest):
    """提交 AI 智能选股任务"""
    task_id = submit_task("ai_screen", run_ai_screen, body.description, body.scope or "full")
    return {"task_id": task_id}


@router.post("/limit-up/collect")
def collect_limit_up(
    trade_date: str = Query(None, description="交易日期 YYYYMMDD，默认最近交易日"),
    window_days: int = Query(1, ge=1, le=60, description="处理最近 N 个交易日，默认 1"),
    db: Session = Depends(get_db),
):
    """涨停筛选：将指定日期的涨停股加入涨停股票观察池，打涨停日期标签"""
    pool = get_or_create_limit_up_pool(db)
    dates = [trade_date] if trade_date else _get_trade_dates(window_days)
    total_added, total_updated, total_skipped = 0, 0, 0
    errors = []
    added_codes = []
    for d in dates:
        r = collect_limit_up_stocks(db, d, pool.id)
        total_added += r["added"]
        total_updated += r["updated"]
        total_skipped += r["skipped"]
        errors.extend(r["errors"])
        added_codes.extend(r.get("added_codes", []))
    for code in added_codes:
        submit_task("sync", sync_single_stock, code)
    return {
        "pool_id": pool.id,
        "pool_name": pool.name,
        "dates_processed": dates,
        "added": total_added,
        "updated": total_updated,
        "skipped": total_skipped,
        "errors": errors[:20],
    }


@router.get("/result/{task_id}", response_model=ScreenResult)
def get_screen_result(task_id: str):
    """轮询选股任务结果（指标选股与 AI 选股共用）"""
    status = get_task_status(task_id)
    if not status:
        raise AppError(code=1004, message="任务不存在", status_code=404)
    result = status.result or {}
    return ScreenResult(
        task_id=status.id,
        status=status.status,
        progress=status.progress,
        message=status.message,
        ts_codes=result.get("ts_codes", []),
        stock_names=result.get("stock_names", {}),
        total=result.get("total", 0),
    )
