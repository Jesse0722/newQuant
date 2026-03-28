"""
核心关注（买点雷达加星）：单例股票池「核心关注」
"""
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.pool import WatchPool, WatchStock
from app.utils import normalize_ts_code
from app.services.sync_service import sync_single_stock
from app.tasks.background import submit_task

CORE_WATCH_POOL_NAME = "核心关注"


def get_core_watch_pool(db: Session) -> WatchPool | None:
    return db.query(WatchPool).filter(WatchPool.name == CORE_WATCH_POOL_NAME).first()


def get_or_create_core_watch_pool(db: Session) -> WatchPool:
    pool = get_core_watch_pool(db)
    if pool:
        return pool
    max_order = db.query(func.max(WatchPool.sort_order)).scalar()
    sort_order = (max_order + 1) if max_order is not None else 0
    pool = WatchPool(
        name=CORE_WATCH_POOL_NAME,
        description="买点雷达加星后的特别关注列表",
        sort_order=sort_order,
    )
    db.add(pool)
    db.commit()
    db.refresh(pool)
    return pool


def list_core_watch_ts_codes(db: Session) -> tuple[str | None, list[str]]:
    pool = get_core_watch_pool(db)
    if not pool:
        return None, []
    codes = [
        s.ts_code
        for s in db.query(WatchStock).filter(WatchStock.pool_id == pool.id).order_by(WatchStock.created_at.desc()).all()
    ]
    return pool.id, codes


def toggle_core_watch_star(
    db: Session,
    ts_code: str,
    starred: bool,
    *,
    limit_up_date: str | None = None,
) -> dict:
    """加星加入核心关注 / 取消星标移除"""
    code = normalize_ts_code(ts_code.strip())
    if starred:
        pool = get_or_create_core_watch_pool(db)
    else:
        pool = get_core_watch_pool(db)
        if not pool:
            return {"starred": False, "pool_id": None, "ts_code": code}

    existing = (
        db.query(WatchStock)
        .filter(WatchStock.pool_id == pool.id, WatchStock.ts_code == code)
        .first()
    )

    if starred:
        if existing:
            if limit_up_date:
                existing.limit_up_date = limit_up_date
            db.commit()
            db.refresh(existing)
            return {"starred": True, "pool_id": pool.id, "stock_id": existing.id, "ts_code": code}
        stock = WatchStock(
            pool_id=pool.id,
            ts_code=code,
            source="buy_radar",
            limit_up_date=limit_up_date,
            note="买点雷达特别关注",
        )
        db.add(stock)
        db.commit()
        db.refresh(stock)
        submit_task("sync", sync_single_stock, code)
        return {"starred": True, "pool_id": pool.id, "stock_id": stock.id, "ts_code": code}

    if existing:
        db.delete(existing)
        db.commit()
    return {"starred": False, "pool_id": pool.id, "ts_code": code}
