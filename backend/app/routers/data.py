import json
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.database import get_db
from app.models.stock import StockBasic, DailyQuote
from app.models.sync_log import SyncLog
from app.config import TUSHARE_TOKEN, TUSHARE_API_URL

router = APIRouter(prefix="/api/data", tags=["data"])


@router.get("/tushare-check")
def check_tushare():
    """诊断 Tushare 连接：检查 token 配置并尝试 stock_basic 接口"""
    token_ok = bool(TUSHARE_TOKEN and len(TUSHARE_TOKEN) > 10)
    result = {
        "token_configured": token_ok,
        "token_length": len(TUSHARE_TOKEN) if TUSHARE_TOKEN else 0,
        "proxy_configured": bool(TUSHARE_API_URL),
        "proxy_url": TUSHARE_API_URL[:80] + "..." if TUSHARE_API_URL and len(TUSHARE_API_URL) > 80 else (TUSHARE_API_URL or "(未配置，走官方 api.waditu.com/dataapi)"),
        "hint": "若 Token 在官网正确但仍报 token 错误，请确认代理地址含 /dataapi（见 .env.example）；仅填 IP 时会自动补全。",
        "api_test": None,
    }
    if not token_ok:
        result["api_test"] = "token 未配置或过短，请在 backend/.env 设置 TUSHARE_TOKEN"
        return result
    try:
        from app.services.tushare_adapter import tushare_adapter
        df = tushare_adapter.get_stock_basic()
        result["api_test"] = "ok"
        result["rows_returned"] = len(df) if df is not None and not df.empty else 0
        if result["rows_returned"] == 0:
            result["api_test"] = "接口返回空数据，请检查 token 是否有效、积分是否足够、代理是否正常"
    except Exception as e:
        result["api_test"] = f"调用失败: {str(e)[:120]}"
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
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "completed_at": r.completed_at.isoformat() if r.completed_at else None,
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
