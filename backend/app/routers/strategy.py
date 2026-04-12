from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from app.database import get_db
from app.services.backtest_service import run_single_strategy_backtest
from app.schemas.strategy import (
    IndicatorScreenRequest,
    AiScreenRequest,
    AiAnalyzeRequest,
    LimitUpBuyPointRequest,
    BacktestRequest,
    BacktestResult,
    StrategyBacktestRequest,
    ScreenResult,
)
from app.services.strategy_service import run_indicator_screen, run_limit_up_buy_point_screen, SCREEN_TEMPLATES, LIMIT_UP_BUY_POINT_TEMPLATES
from app.services.ai_screen_service import run_ai_screen
from app.services.ai_analysis_service import analyze_stock
from app.services.limit_up_service import (
    get_or_create_limit_up_pool,
    collect_limit_up_stocks,
    _get_trade_dates,
)
from app.services.buy_signal_service import scan_pool_buy_signals, list_buy_strategies
from app.services.sync_service import sync_single_stock, _sync_stock_basic_full
from app.models.sync_log import SyncLog
from app.models.intraday_scan import IntradayScanConfig
from app.tasks.background import submit_task, get_task_status
from app.services.strategy_backtest import run_strategy_backtest_task
from app.exceptions import AppError


class ScanBuySignalsRequest(BaseModel):
    pool_id: Optional[str] = Field(None, description="观察池 ID，不传则自动使用涨停池")
    strategy_id: str = Field("two_phase", description="策略 ID，默认二阶段买点")
    min_confirm_hits: int = Field(2, ge=1, le=5, description="盘中确证阈值：连续命中次数")


class IntradayConfigItem(BaseModel):
    pool_id: str
    strategy_id: str
    enabled: bool = False
    interval_minutes: int = Field(5, ge=1, le=30)
    min_confirm_hits: int = Field(2, ge=1, le=5)


class IntradayConfigPatch(BaseModel):
    pool_id: str
    strategy_id: str
    enabled: Optional[bool] = None
    interval_minutes: Optional[int] = Field(None, ge=1, le=30)
    min_confirm_hits: Optional[int] = Field(None, ge=1, le=5)

router = APIRouter(prefix="/api/strategy", tags=["strategy"])


@router.get("/templates")
def list_screen_templates():
    """获取指标选股模板列表"""
    return [
        {"id": k, "name": v["name"], "default_params": v["params"]}
        for k, v in SCREEN_TEMPLATES.items()
    ]


@router.get("/limit-up-templates")
def list_limit_up_templates():
    """获取涨停回调买点选股模板列表"""
    return [
        {"id": k, "name": v["name"], "default_params": v["default_params"]}
        for k, v in LIMIT_UP_BUY_POINT_TEMPLATES.items()
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


@router.post("/ai-analyze")
def run_ai_analyze(body: AiAnalyzeRequest, db: Session = Depends(get_db)):
    """单只股票 AI 智能分析，并写入观察池股票 ai_analysis 字段"""
    try:
        return analyze_stock(db, body.ts_code, body.stock_id)
    except ValueError as e:
        raise AppError(code=2003, message=str(e), status_code=400)
    except RuntimeError as e:
        raise AppError(code=2004, message=str(e), status_code=400)


@router.post("/limit-up-buy-point")
def run_limit_up_buy_point(body: LimitUpBuyPointRequest):
    """提交涨停回调买点选股任务"""
    conditions = [c.model_dump() for c in body.conditions]
    task_id = submit_task(
        "limit_up_buy_point",
        run_limit_up_buy_point_screen,
        body.trade_date_from,
        body.trade_date_to,
        conditions,
        body.logic,
    )
    return {"task_id": task_id}


@router.post("/backtest", response_model=BacktestResult)
def run_backtest(body: BacktestRequest, db: Session = Depends(get_db)):
    """涨停回调策略回测：同步执行，返回次日收益均值、胜率、信号列表"""
    conditions = [c.model_dump() for c in body.conditions]
    result = run_single_strategy_backtest(
        db, body.trade_date_from, body.trade_date_to, conditions, body.logic
    )
    return BacktestResult(**result)


@router.get("/buy-strategies")
def get_buy_strategies():
    """获取可用的买点扫描策略列表"""
    return list_buy_strategies()


@router.post("/scan-buy-signals")
def scan_buy_signals(body: ScanBuySignalsRequest, db: Session = Depends(get_db)):
    """扫描观察池买点信号，支持多策略选择"""
    return scan_pool_buy_signals(
        db,
        body.pool_id,
        body.strategy_id,
        min_confirm_hits=body.min_confirm_hits,
    )


@router.get("/intraday-config")
def list_intraday_config(
    pool_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    q = db.query(IntradayScanConfig)
    if pool_id:
        q = q.filter(IntradayScanConfig.pool_id == pool_id)
    rows = q.order_by(IntradayScanConfig.updated_at.desc()).all()
    return [
        IntradayConfigItem(
            pool_id=r.pool_id,
            strategy_id=r.strategy_id,
            enabled=bool(r.enabled),
            interval_minutes=int(r.interval_minutes or 5),
            min_confirm_hits=int(r.min_confirm_hits or 2),
        )
        for r in rows
    ]


@router.put("/intraday-config", response_model=IntradayConfigItem)
def upsert_intraday_config(body: IntradayConfigPatch, db: Session = Depends(get_db)):
    row = (
        db.query(IntradayScanConfig)
        .filter(
            IntradayScanConfig.pool_id == body.pool_id,
            IntradayScanConfig.strategy_id == body.strategy_id,
        )
        .first()
    )
    if not row:
        row = IntradayScanConfig(
            pool_id=body.pool_id,
            strategy_id=body.strategy_id,
            enabled=bool(body.enabled) if body.enabled is not None else False,
            interval_minutes=body.interval_minutes or 5,
            min_confirm_hits=body.min_confirm_hits or 2,
        )
        db.add(row)
    else:
        if body.enabled is not None:
            row.enabled = bool(body.enabled)
        if body.interval_minutes is not None:
            row.interval_minutes = body.interval_minutes
        if body.min_confirm_hits is not None:
            row.min_confirm_hits = body.min_confirm_hits
    db.commit()
    db.refresh(row)
    return IntradayConfigItem(
        pool_id=row.pool_id,
        strategy_id=row.strategy_id,
        enabled=bool(row.enabled),
        interval_minutes=int(row.interval_minutes or 5),
        min_confirm_hits=int(row.min_confirm_hits or 2),
    )


@router.post("/strategy-backtest")
def submit_strategy_backtest(body: StrategyBacktestRequest):
    """提交新买点策略回测任务（异步）"""
    task_id = submit_task(
        "strategy_backtest",
        run_strategy_backtest_task,
        body.strategy_id,
        body.trade_date_from,
        body.trade_date_to,
        body.pool_id,
    )
    return {"task_id": task_id}


@router.get("/strategy-backtest/{task_id}")
def get_strategy_backtest_result(task_id: str):
    """查询新买点策略回测任务状态与结果"""
    status = get_task_status(task_id)
    if not status:
        raise AppError(code=1004, message="任务不存在", status_code=404)
    return {
        "task_id": status.id,
        "status": status.status,
        "progress": status.progress,
        "message": status.message,
        "result": status.result,
    }


@router.post("/limit-up/collect")
def collect_limit_up(
    trade_date: str = Query(None, description="交易日期 YYYYMMDD，默认最近交易日"),
    window_days: int = Query(1, ge=1, le=60, description="处理最近 N 个已完成交易日（SSE 日历，与仪表盘默认日一致），默认 1"),
    db: Session = Depends(get_db),
):
    """涨停筛选：直接调用 Tushare 获取涨停股，加入观察池并自动同步 60 日 K 线。无需全量同步。"""
    log_id = str(uuid.uuid4())
    db.add(
        SyncLog(
            id=log_id,
            task_type="limit_up_collect",
            target=None,
            status="running",
        )
    )
    db.commit()

    try:
        _sync_stock_basic_full(db)
    except Exception:
        pass  # 部分代理不支持 stock_basic，跳过；已有本地数据仍可用于 ST/阈值判断
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
        submit_task("sync", sync_single_stock, code, 60)  # 自动同步 60 日 K 线

    resp = {
        "pool_id": pool.id,
        "pool_name": pool.name,
        "dates_processed": dates,
        "added": total_added,
        "updated": total_updated,
        "skipped": total_skipped,
        "errors": errors[:20],
    }
    log = db.query(SyncLog).filter(SyncLog.id == log_id).first()
    if log:
        log.status = "completed"
        log.completed_at = datetime.utcnow()
        log.result = json.dumps(
            {
                "success_count": total_added + total_updated,
                "failed_count": len(errors),
                "skipped_count": total_skipped,
                "days_synced": len(dates),
                "message": f"涨停筛选完成：新增 {total_added}，更新 {total_updated}，跳过 {total_skipped}",
                "added": total_added,
                "updated": total_updated,
                "errors": errors[:20],
            },
            ensure_ascii=False,
        )
        db.commit()

    return resp


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
