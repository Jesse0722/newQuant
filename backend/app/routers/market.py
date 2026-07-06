from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.sector import SectorBasic, SectorDailyQuote, StockSectorMap
from app.exceptions import AppError
from app.services.main_wave_service import analyze_main_wave_stock, scan_main_wave_pool
from app.services.main_wave_sector_backfill_service import (
    get_main_wave_sector_backfill_status,
    run_main_wave_sector_backfill,
)
from app.services.sector_data_service import sync_sector_data
from app.tasks.background import get_task_status, submit_task
from app.services.trading_session import is_a_share_trading_session

router = APIRouter(prefix="/api/market", tags=["market"])


class SectorSyncRequest(BaseModel):
    sector_types: list[Literal["concept", "industry"]] = Field(default_factory=lambda: ["concept", "industry"])
    sync_constituents: bool = True
    sync_quotes: bool = True
    days: int = Field(180, ge=1, le=1200)
    limit: int | None = Field(30, ge=1, le=500)


class MainWaveSectorBackfillRequest(BaseModel):
    pool_id: str | None = None
    days: int = Field(250, ge=1, le=1200)
    mode: Literal["backfill", "incremental"] = "backfill"
    force: bool = False


class MainWaveBatchRequest(BaseModel):
    ts_codes: list[str] = Field(default_factory=list, max_length=100)


@router.get("/trading-session")
def get_trading_session():
    """与扫描服务同源的交易时段判定，供前端轻量轮询。"""
    return {"in_session": is_a_share_trading_session()}


@router.post("/sectors/sync")
def sync_sectors(body: SectorSyncRequest, db: Session = Depends(get_db)):
    """同步板块基础、成分和日线数据。limit 用于控制本次处理的板块数量。"""
    return sync_sector_data(
        db,
        sector_types=body.sector_types,
        sync_constituents=body.sync_constituents,
        sync_quotes=body.sync_quotes,
        days=body.days,
        limit=body.limit,
    )


@router.get("/sectors")
def list_sectors(
    sector_type: Literal["concept", "industry"] | None = Query(None),
    keyword: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    q = db.query(SectorBasic)
    if sector_type:
        q = q.filter(SectorBasic.sector_type == sector_type)
    if keyword:
        q = q.filter(SectorBasic.sector_name.like(f"%{keyword}%"))
    rows = q.order_by(SectorBasic.rank.asc().nullslast(), SectorBasic.sector_name.asc()).limit(limit).all()
    return [
        {
            "sector_code": r.sector_code,
            "sector_name": r.sector_name,
            "sector_type": r.sector_type,
            "source": r.source,
            "raw_code": r.raw_code,
            "rank": r.rank,
            "latest_pct_chg": r.latest_pct_chg,
            "latest_hot": r.latest_hot,
            "updated_at": r.updated_at.isoformat() + "Z" if r.updated_at else None,
        }
        for r in rows
    ]


@router.get("/sectors/{sector_code}/quotes")
def list_sector_quotes(
    sector_code: str,
    limit: int = Query(120, ge=1, le=1200),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(SectorDailyQuote)
        .filter(SectorDailyQuote.sector_code == sector_code)
        .order_by(SectorDailyQuote.trade_date.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "sector_code": r.sector_code,
            "trade_date": r.trade_date,
            "sector_name": r.sector_name,
            "sector_type": r.sector_type,
            "open": r.open,
            "high": r.high,
            "low": r.low,
            "close": r.close,
            "pct_chg": r.pct_chg,
            "change": r.change,
            "vol": r.vol,
            "amount": r.amount,
            "turnover_rate": r.turnover_rate,
        }
        for r in rows
    ]


@router.get("/stocks/{ts_code}/sectors")
def list_stock_sectors(
    ts_code: str,
    sector_type: Literal["concept", "industry"] | None = Query(None),
    db: Session = Depends(get_db),
):
    q = db.query(StockSectorMap).filter(StockSectorMap.ts_code == ts_code.upper())
    if sector_type:
        q = q.filter(StockSectorMap.sector_type == sector_type)
    rows = q.order_by(StockSectorMap.sector_type.asc(), StockSectorMap.sector_name.asc()).all()
    return [
        {
            "ts_code": r.ts_code,
            "sector_code": r.sector_code,
            "sector_name": r.sector_name,
            "sector_type": r.sector_type,
            "source": r.source,
            "weight": r.weight,
            "updated_at": r.updated_at.isoformat() + "Z" if r.updated_at else None,
        }
        for r in rows
    ]


@router.get("/stocks/{ts_code}/main-wave")
def analyze_stock_main_wave(ts_code: str, db: Session = Depends(get_db)):
    """单只股票主升浪趋势评分：个股趋势 + MA20 修复状态 + 板块共振。"""
    return analyze_main_wave_stock(db, ts_code)


@router.post("/main-wave/analyze-batch")
def analyze_main_wave_batch(body: MainWaveBatchRequest, db: Session = Depends(get_db)):
    """按前端当前列表批量评分，避免大池子打开时触发全池扫描。"""
    items = []
    seen: set[str] = set()
    for raw_code in body.ts_codes:
        ts_code = str(raw_code or "").strip().upper()
        if not ts_code or ts_code in seen:
            continue
        seen.add(ts_code)
        try:
            items.append(analyze_main_wave_stock(db, ts_code, allow_external_sector_fetch=False))
        except Exception:
            items.append(
                {
                    "ts_code": ts_code,
                    "name": ts_code,
                    "status": "insufficient_data",
                    "total_score": 0,
                    "message": "主升浪评分失败",
                }
            )
    return {"total": len(items), "items": items}


@router.get("/main-wave/scan")
def scan_main_wave(
    pool_id: str | None = Query(None),
    min_score: int | None = Query(None, ge=0, le=100),
    status: list[str] | None = Query(None),
    db: Session = Depends(get_db),
):
    """批量扫描主升浪评分，可按观察池、最低分和阶段过滤。"""
    return scan_main_wave_pool(db, pool_id=pool_id, min_score=min_score, statuses=status)


@router.get("/main-wave/sectors/backfill/status")
def get_main_wave_sector_status(
    pool_id: str | None = Query(None),
    days: int = Query(250, ge=1, le=1200),
    db: Session = Depends(get_db),
):
    """查看当前主升浪池相关概念板块 K 线补齐状态。"""
    return get_main_wave_sector_backfill_status(db, pool_id=pool_id, target_days=days)


@router.post("/main-wave/sectors/backfill")
def start_main_wave_sector_backfill(body: MainWaveSectorBackfillRequest):
    """后台补齐当前主升浪池相关概念板块 K 线，支持断点续跑和增量同步。"""
    task_id = submit_task(
        "main_wave_sector_backfill",
        run_main_wave_sector_backfill,
        pool_id=body.pool_id,
        days=body.days,
        mode=body.mode,
        force=body.force,
    )
    return {"task_id": task_id}


@router.get("/main-wave/sectors/backfill/tasks/{task_id}")
def get_main_wave_sector_backfill_task(task_id: str):
    status = get_task_status(task_id)
    if not status:
        raise AppError(code=1004, message="任务不存在", status_code=404)
    return {
        "task_id": status.id,
        "type": status.type,
        "status": status.status,
        "progress": status.progress,
        "message": status.message,
        "result": status.result,
        "created_at": status.created_at.isoformat() + "Z",
    }
