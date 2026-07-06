from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Literal

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.pool import WatchPool, WatchStock
from app.models.sector import SectorBasic, SectorQuoteSyncState, StockSectorMap
from app.services.main_wave_service import get_relevant_concept_candidates
from app.services.sector_data_service import (
    SOURCE,
    fetch_sector_daily_quotes,
    fetch_stock_concept_sectors,
    refresh_quote_sync_state,
    sector_quote_coverage,
    upsert_sector_basic,
    upsert_sector_daily_quotes,
    upsert_stock_sector_map,
)
from app.tasks.background import task_registry

BackfillMode = Literal["backfill", "incremental"]

_RETRY_DELAYS = (
    timedelta(minutes=5),
    timedelta(minutes=15),
    timedelta(minutes=30),
    timedelta(hours=2),
)


def _get_main_wave_pool(db: Session, pool_id: str | None) -> WatchPool | None:
    if pool_id:
        return db.query(WatchPool).filter(WatchPool.id == pool_id).first()
    return (
        db.query(WatchPool)
        .filter(WatchPool.name.like("%主升浪%"))
        .order_by(WatchPool.updated_at.desc())
        .first()
    )


def _ensure_stock_f10_sectors(db: Session, ts_code: str) -> int:
    try:
        return upsert_sector_basic(db, fetch_stock_concept_sectors(ts_code))
    except Exception:
        return 0


def _sector_by_code_or_name(db: Session, candidate: dict[str, Any]) -> SectorBasic | None:
    code = candidate.get("sector_code")
    name = candidate.get("sector_name")
    q = db.query(SectorBasic).filter(SectorBasic.source == SOURCE)
    if code:
        sector = q.filter(SectorBasic.sector_code == str(code)).first()
        if sector:
            return sector
    if name:
        return q.filter(SectorBasic.sector_name == str(name), SectorBasic.sector_type == "concept").first()
    return None


def _choose_stock_sector(db: Session, ts_code: str, *, allow_external_sector_fetch: bool = True) -> SectorBasic | None:
    mapped = (
        db.query(StockSectorMap)
        .filter(
            StockSectorMap.ts_code == ts_code,
            StockSectorMap.source == SOURCE,
            StockSectorMap.sector_type == "concept",
        )
        .order_by(StockSectorMap.weight.desc().nullslast(), StockSectorMap.updated_at.desc())
        .first()
    )
    if mapped:
        sector = db.query(SectorBasic).filter(SectorBasic.sector_code == mapped.sector_code).first()
        if sector:
            return sector

    if not allow_external_sector_fetch:
        return None

    candidates = [
        c
        for c in get_relevant_concept_candidates(db, ts_code, limit=8)
        if c.get("sector_type") == "concept" and c.get("sector_name")
    ]
    for candidate in candidates:
        sector = _sector_by_code_or_name(db, candidate)
        if sector:
            return sector
    return None


def collect_main_wave_pool_concepts(
    db: Session,
    *,
    pool_id: str | None = None,
    target_days: int = 250,
    sync_missing_sectors: bool = True,
) -> dict[str, Any]:
    pool = _get_main_wave_pool(db, pool_id)
    if not pool:
        return {"pool": None, "stocks": [], "concepts": []}
    stocks = (
        db.query(WatchStock)
        .filter(WatchStock.pool_id == pool.id)
        .order_by(WatchStock.pinned.desc(), WatchStock.created_at.desc())
        .all()
    )
    concepts: dict[str, dict[str, Any]] = {}
    for stock in stocks:
        if sync_missing_sectors:
            _ensure_stock_f10_sectors(db, stock.ts_code)
        sector = _choose_stock_sector(db, stock.ts_code, allow_external_sector_fetch=sync_missing_sectors)
        if not sector:
            continue
        item = concepts.setdefault(
            sector.sector_code,
            {
                "sector": sector,
                "stocks": [],
            },
        )
        item["stocks"].append(stock.ts_code)
    return {"pool": pool, "stocks": stocks, "concepts": list(concepts.values())}


def _state_json(state: SectorQuoteSyncState, stocks: list[str] | None = None) -> dict[str, Any]:
    return {
        "sector_code": state.sector_code,
        "sector_name": state.sector_name,
        "sector_type": state.sector_type,
        "source": state.source,
        "status": state.status,
        "target_days": state.target_days,
        "quote_count": state.quote_count,
        "first_trade_date": state.first_trade_date,
        "last_trade_date": state.last_trade_date,
        "attempts": state.attempts,
        "last_error": state.last_error,
        "next_retry_at": state.next_retry_at.isoformat() + "Z" if state.next_retry_at else None,
        "last_success_at": state.last_success_at.isoformat() + "Z" if state.last_success_at else None,
        "stocks": stocks or [],
    }


def get_main_wave_sector_backfill_status(db: Session, *, pool_id: str | None = None, target_days: int = 250) -> dict[str, Any]:
    collected = collect_main_wave_pool_concepts(
        db,
        pool_id=pool_id,
        target_days=target_days,
        sync_missing_sectors=False,
    )
    pool = collected["pool"]
    concepts = collected["concepts"]
    items: list[dict[str, Any]] = []
    for item in concepts:
        sector: SectorBasic = item["sector"]
        state = refresh_quote_sync_state(db, sector, target_days=target_days)
        items.append(_state_json(state, item["stocks"]))
    completed = sum(1 for x in items if (x["quote_count"] or 0) >= target_days)
    partial = sum(1 for x in items if 0 < (x["quote_count"] or 0) < target_days)
    cooldown = sum(1 for x in items if x["status"] == "cooldown")
    return {
        "pool_id": pool.id if pool else None,
        "pool_name": pool.name if pool else None,
        "stock_count": len(collected["stocks"]),
        "concept_count": len(items),
        "completed_count": completed,
        "partial_count": partial,
        "cooldown_count": cooldown,
        "missing_count": max(len(items) - completed - partial, 0),
        "items": items,
    }


def _next_retry_at(attempts: int) -> datetime:
    idx = min(max(attempts - 1, 0), len(_RETRY_DELAYS) - 1)
    return datetime.utcnow() + _RETRY_DELAYS[idx]


def _is_complete(coverage: dict[str, Any], target_days: int) -> bool:
    return int(coverage.get("quote_count") or 0) >= target_days


def _quote_date_range(db: Session, sector: SectorBasic, *, mode: BackfillMode, days: int) -> tuple[str, str, int]:
    end_date = datetime.now().strftime("%Y%m%d")
    coverage = sector_quote_coverage(db, sector.sector_code)
    last_trade_date = coverage.get("last_trade_date")
    if mode == "incremental" and last_trade_date:
        start = datetime.strptime(str(last_trade_date), "%Y%m%d") - timedelta(days=10)
        return start.strftime("%Y%m%d"), end_date, 40
    start = datetime.now() - timedelta(days=max(days * 2, 365))
    return start.strftime("%Y%m%d"), end_date, days


def run_main_wave_sector_backfill(
    task_id: str,
    *,
    pool_id: str | None = None,
    days: int = 250,
    mode: BackfillMode = "backfill",
    force: bool = False,
) -> None:
    task = task_registry.get(task_id)
    db = SessionLocal()
    result = {"quote_count": 0, "map_count": 0, "skipped": 0, "failed": []}
    try:
        collected = collect_main_wave_pool_concepts(db, pool_id=pool_id, target_days=days)
        concepts = collected["concepts"]
        total = len(concepts)
        if task:
            task.message = f"待处理 {total} 个概念板块"
        for idx, item in enumerate(concepts, start=1):
            sector: SectorBasic = item["sector"]
            stocks: list[str] = item["stocks"]
            if task:
                task.progress = (idx - 1) / total if total else 1.0
                task.message = f"{sector.sector_name} K线补齐中 ({idx}/{total})"

            state = refresh_quote_sync_state(db, sector, target_days=days)
            coverage = sector_quote_coverage(db, sector.sector_code)
            if mode == "backfill" and _is_complete(coverage, days) and not force:
                result["skipped"] += 1
                refresh_quote_sync_state(db, sector, status="success", target_days=days, reset_attempts=True)
                continue
            if state.next_retry_at and state.next_retry_at > datetime.utcnow() and not force:
                result["skipped"] += 1
                continue

            map_rows = [
                {
                    "ts_code": code,
                    "sector_code": sector.sector_code,
                    "sector_name": sector.sector_name,
                    "sector_type": sector.sector_type,
                    "source": sector.source,
                    "weight": 1.0,
                }
                for code in stocks
            ]
            result["map_count"] += upsert_stock_sector_map(db, map_rows)

            try:
                start_date, end_date, limit = _quote_date_range(db, sector, mode=mode, days=days)
                quote_rows = fetch_sector_daily_quotes(sector, start_date=start_date, end_date=end_date, limit=limit)
                count = upsert_sector_daily_quotes(db, quote_rows)
                result["quote_count"] += count
                coverage = sector_quote_coverage(db, sector.sector_code)
                status = "success" if _is_complete(coverage, days) else "partial"
                refresh_quote_sync_state(db, sector, status=status, target_days=days, reset_attempts=True)
            except Exception as e:
                failed_state = refresh_quote_sync_state(
                    db,
                    sector,
                    status="cooldown",
                    target_days=days,
                    last_error=str(e)[:500],
                    next_retry_at=_next_retry_at((state.attempts or 0) + 1),
                    increment_attempts=True,
                )
                result["failed"].append(
                    {
                        "sector_code": sector.sector_code,
                        "sector_name": sector.sector_name,
                        "error": failed_state.last_error,
                        "next_retry_at": failed_state.next_retry_at.isoformat() + "Z" if failed_state.next_retry_at else None,
                    }
                )
        if task:
            task.result = result
            task.progress = 1.0
            task.message = f"完成：K线 {result['quote_count']} 行，跳过 {result['skipped']} 个，失败 {len(result['failed'])} 个"
    finally:
        db.close()
