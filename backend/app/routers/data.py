from __future__ import annotations

import json
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.database import get_db
from app.models.stock import StockBasic, DailyQuote
from app.models.sync_log import SyncLog
from app.config import (
    TUSHARE_TOKEN,
    TUSHARE_API_URL,
    COMPOSITE_ORDER,
)
from app.services.tushare_adapter import get_current_provider_name, switch_provider

router = APIRouter(prefix="/api/data", tags=["data"])


class ProviderSwitchBody(BaseModel):
    provider: str


@router.get("/provider")
def get_provider():
    return {
        "provider": get_current_provider_name(),
        "options": ["tushare", "akshare", "composite"],
        "composite_order": COMPOSITE_ORDER,
    }


@router.put("/provider")
def set_provider(body: ProviderSwitchBody):
    p = switch_provider(body.provider)
    return {"provider": p}


@router.get("/tushare-check")
def check_tushare():
    """诊断行情数据源：配置 + 日线探测 + 交易日历探测（随当前 DATA_PROVIDER 走 composite 回退）。"""
    from datetime import datetime

    from app.services.tushare_adapter import tushare_adapter

    provider = get_current_provider_name()
    token_ok = bool(TUSHARE_TOKEN and len(TUSHARE_TOKEN) > 10)
    cal_day = datetime.now().strftime("%Y%m%d")
    result = {
        "token_configured": token_ok,
        "token_length": len(TUSHARE_TOKEN) if TUSHARE_TOKEN else 0,
        "proxy_configured": bool(TUSHARE_API_URL),
        "proxy_url": TUSHARE_API_URL[:80] + "..." if TUSHARE_API_URL and len(TUSHARE_API_URL) > 80 else (TUSHARE_API_URL or "(未配置，走官方 api.waditu.com/dataapi)"),
        "data_provider": provider,
        "composite_order": COMPOSITE_ORDER,
        "hint": "akshare / composite 不要求 token；仅 data_provider=tushare 时必须先配置 TUSHARE_TOKEN。",
        "api_test": None,
        "rows_returned": None,
        "calendar_test": None,
        "calendar_days": None,
    }
    if provider == "tushare" and not token_ok:
        result["api_test"] = "token 未配置或过短，请在 backend/.env 设置 TUSHARE_TOKEN"
        return result
    if provider in ("akshare", "composite") and not token_ok:
        result["token_note"] = "未配置 TUSHARE_TOKEN：若仅用 AkShare 可忽略；composite 回退到 Tushare 时需要 token。"

    try:
        df = tushare_adapter.get_daily("000001.SZ", start_date="20240101", end_date="20240105")
        n = len(df) if df is not None and not df.empty else 0
        result["rows_returned"] = n
        if n == 0:
            result["api_test"] = "个股日线返回空（请查网络、积分/权限或换数据源）"
        else:
            result["api_test"] = "ok"
    except Exception as e:
        result["api_test"] = f"daily 调用失败: {str(e)[:160]}"

    try:
        dates = tushare_adapter.get_sse_open_dates(cal_day, lookback_calendar_days=30)
        result["calendar_days"] = len(dates)
        if len(dates) >= 5:
            result["calendar_test"] = "ok"
        elif len(dates) > 0:
            result["calendar_test"] = f"交易日历偏少({len(dates)} 条)，可能截断或网络不稳"
        else:
            result["calendar_test"] = "交易日历为空，请检查网络或上游限流"
    except Exception as e:
        result["calendar_test"] = f"日历失败: {str(e)[:120]}"

    return result


@router.get("/sync-history")
def get_sync_history(task_type: str = "all", limit: int = 20, db: Session = Depends(get_db)):
    """获取同步记录列表，用于页面展示上次同步结果"""
    q = db.query(SyncLog)
    if task_type != "all":
        q = q.filter(SyncLog.task_type == task_type)
    rows = q.order_by(SyncLog.started_at.desc()).limit(limit).all()
    out = []
    for r in rows:
        item = {
            "id": r.id,
            "task_type": r.task_type,
            "status": r.status,
            "started_at": r.started_at.isoformat() + "Z" if r.started_at else None,
            "completed_at": r.completed_at.isoformat() + "Z" if r.completed_at else None,
        }
        if r.result:
            try:
                item["result"] = json.loads(r.result)
            except Exception:
                item["result"] = {}
        else:
            item["result"] = {}
        out.append(item)
    return out


@router.get("/sync-overview")
def get_sync_overview(days: int = 7, db: Session = Depends(get_db)):
    """同步任务总览：最近 N 天成功/失败/跳过聚合"""
    rows = (
        db.query(SyncLog)
        .order_by(SyncLog.started_at.desc())
        .limit(500)
        .all()
    )

    task_type_stats: dict[str, dict] = {}
    total = {"success": 0, "failed": 0, "skipped": 0, "tasks": 0}

    for r in rows:
        result = {}
        if r.result:
            try:
                result = json.loads(r.result)
            except Exception:
                result = {}
        success = int(result.get("success_count", 0) or 0)
        failed = int(result.get("failed_count", 0) or 0)
        skipped = int(result.get("skipped_count", 0) or 0)

        if r.task_type not in task_type_stats:
            task_type_stats[r.task_type] = {"task_type": r.task_type, "tasks": 0, "success": 0, "failed": 0, "skipped": 0}
        task_type_stats[r.task_type]["tasks"] += 1
        task_type_stats[r.task_type]["success"] += success
        task_type_stats[r.task_type]["failed"] += failed
        task_type_stats[r.task_type]["skipped"] += skipped

        total["tasks"] += 1
        total["success"] += success
        total["failed"] += failed
        total["skipped"] += skipped

    return {
        "days": days,
        "total": total,
        "by_task_type": list(task_type_stats.values()),
    }


@router.get("/summary")
def get_data_summary(db: Session = Depends(get_db)):
    """数据概览：股票数量、行情日期范围、总条数"""
    stock_count = db.query(func.count(StockBasic.ts_code)).scalar() or 0
    total_quotes = db.query(func.count(DailyQuote.ts_code)).scalar() or 0
    date_range = db.query(
        func.min(DailyQuote.trade_date),
        func.max(DailyQuote.trade_date),
    ).first()
    min_date, max_date = (date_range[0], date_range[1]) if date_range else (None, None)
    return {
        "stock_count": stock_count,
        "total_quotes": total_quotes,
        "quote_date_range": {"min": min_date, "max": max_date},
        "last_sync_at": max_date,
    }
