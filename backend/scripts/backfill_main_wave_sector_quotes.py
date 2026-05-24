"""补齐主升浪样本库股票最相关东方财富概念板块最近 N 个交易日 K 线。"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.database import SessionLocal
from app.models.pool import WatchPool, WatchStock
from app.models.sector import SectorBasic, StockSectorMap
from app.services.main_wave_service import get_relevant_concept_candidates
from app.services.sector_data_service import (
    SOURCE,
    fetch_sector_constituents,
    fetch_sector_daily_quotes,
    fetch_sector_list,
    fetch_stock_concept_sectors,
    get_or_create_quote_sync_state,
    refresh_quote_sync_state,
    sector_quote_coverage,
    upsert_sector_basic,
    upsert_sector_daily_quotes,
    upsert_stock_sector_map,
)

_RETRY_DELAYS = (
    timedelta(minutes=5),
    timedelta(minutes=15),
    timedelta(minutes=30),
    timedelta(hours=2),
)


def _get_main_wave_pool(db, pool_id: str | None):
    if pool_id:
        return db.query(WatchPool).filter(WatchPool.id == pool_id).first()
    return (
        db.query(WatchPool)
        .filter(WatchPool.name.like("%主升浪%"))
        .order_by(WatchPool.updated_at.desc())
        .first()
    )


def _sector_by_code_or_name(db, candidate: dict) -> SectorBasic | None:
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


def _ensure_stock_f10_sectors(db, ts_code: str) -> int:
    try:
        return upsert_sector_basic(db, fetch_stock_concept_sectors(ts_code))
    except Exception as e:
        print(f"{ts_code}: F10概念失败 {str(e)[:120]}")
        return 0


def _choose_stock_sector(db, ts_code: str) -> SectorBasic | None:
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


def _next_retry_at(attempts: int) -> datetime:
    idx = min(max(attempts - 1, 0), len(_RETRY_DELAYS) - 1)
    return datetime.utcnow() + _RETRY_DELAYS[idx]


def _is_complete(coverage: dict, target_days: int) -> bool:
    return int(coverage.get("quote_count") or 0) >= target_days


def _quote_date_range(db, sector: SectorBasic, *, mode: str, days: int) -> tuple[str, str, int]:
    end_date = datetime.now().strftime("%Y%m%d")
    coverage = sector_quote_coverage(db, sector.sector_code)
    last_trade_date = coverage.get("last_trade_date")
    if mode == "incremental" and last_trade_date:
        start = datetime.strptime(str(last_trade_date), "%Y%m%d") - timedelta(days=10)
        return start.strftime("%Y%m%d"), end_date, 40
    start = datetime.now() - timedelta(days=max(days * 2, 365))
    return start.strftime("%Y%m%d"), end_date, days


def _state_line(state) -> str:
    return (
        f"状态={state.status} 已有={state.quote_count}/{state.target_days or '-'} "
        f"区间={state.first_trade_date or '-'}~{state.last_trade_date or '-'} "
        f"失败={state.attempts}"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pool-id", default=None, help="观察池 ID，默认取名称包含主升浪的最新池")
    parser.add_argument("--days", type=int, default=250, help="需要覆盖的交易日数量，默认 250")
    parser.add_argument("--dry-run", action="store_true", help="只打印候选概念，不写库")
    parser.add_argument("--skip-sector-list", action="store_true", help="跳过概念板块列表同步")
    parser.add_argument("--sync-full-constituents", action="store_true", help="尝试同步概念全量成分，默认只写当前池F10映射")
    parser.add_argument("--mode", choices=("backfill", "incremental"), default="backfill", help="backfill补足存量，incremental只补增量")
    parser.add_argument("--force", action="store_true", help="忽略已完成和冷却状态，强制尝试")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        pool = _get_main_wave_pool(db, args.pool_id)
        if not pool:
            raise SystemExit("找不到主升浪观察池")

        if not args.skip_sector_list:
            print("同步东方财富概念板块列表...")
            try:
                sector_count = upsert_sector_basic(db, fetch_sector_list("concept"))
                print(f"概念板块列表写入/更新 {sector_count} 条")
            except Exception as e:
                print(f"概念板块列表失败，改用个股F10概念补齐当前池: {str(e)[:160]}")

        stocks = (
            db.query(WatchStock)
            .filter(WatchStock.pool_id == pool.id)
            .order_by(WatchStock.pinned.desc(), WatchStock.created_at.desc())
            .all()
        )
        concepts: dict[str, dict] = {}
        for stock in stocks:
            _ensure_stock_f10_sectors(db, stock.ts_code)
            sector = _choose_stock_sector(db, stock.ts_code)
            if not sector:
                print(f"{stock.ts_code}: 无可用东方财富概念候选")
                continue
            item = concepts.setdefault(
                sector.sector_code,
                {
                    "sector": sector,
                    "stocks": [],
                },
            )
            item["stocks"].append(stock.ts_code)

        print(f"观察池: {pool.name} ({pool.id})")
        print(f"股票数: {len(stocks)}，待补概念数: {len(concepts)}")
        for item in concepts.values():
            sector = item["sector"]
            state = get_or_create_quote_sync_state(db, sector, target_days=args.days)
            refresh_quote_sync_state(db, sector, target_days=args.days)
            print(f"- {sector.sector_name}({sector.sector_code}): {', '.join(item['stocks'])} | {_state_line(state)}")
        if args.dry_run:
            return

        total_cons = 0
        total_quotes = 0
        skipped = 0
        for idx, item in enumerate(concepts.values(), start=1):
            sector = item["sector"]
            print(f"[{idx}/{len(concepts)}] {sector.sector_name}({sector.sector_code})")
            state = refresh_quote_sync_state(db, sector, target_days=args.days)
            coverage = sector_quote_coverage(db, sector.sector_code)
            if args.mode == "backfill" and _is_complete(coverage, args.days) and not args.force:
                skipped += 1
                refresh_quote_sync_state(db, sector, status="success", target_days=args.days, reset_attempts=True)
                print(f"  已有 {coverage['quote_count']} 行，满足 {args.days} 日目标，跳过")
                continue
            if state.next_retry_at and state.next_retry_at > datetime.utcnow() and not args.force:
                skipped += 1
                print(f"  冷却中，下次可重试 {state.next_retry_at.strftime('%Y-%m-%d %H:%M:%S')}，跳过")
                continue

            if not args.sync_full_constituents:
                fallback_rows = [
                    {
                        "ts_code": code,
                        "sector_code": sector.sector_code,
                        "sector_name": sector.sector_name,
                        "sector_type": sector.sector_type,
                        "source": sector.source,
                        "weight": 1.0,
                    }
                    for code in item["stocks"]
                ]
                total_cons += upsert_stock_sector_map(db, fallback_rows)
                print(f"  当前池映射写入/更新 {len(fallback_rows)} 条")
            else:
                try:
                    cons_rows = fetch_sector_constituents(sector)
                    total_cons += upsert_stock_sector_map(db, cons_rows)
                    mapped = {row["ts_code"] for row in cons_rows}
                    missing = [code for code in item["stocks"] if code not in mapped]
                    if missing:
                        total_cons += upsert_stock_sector_map(
                            db,
                            [
                                {
                                    "ts_code": code,
                                    "sector_code": sector.sector_code,
                                    "sector_name": sector.sector_name,
                                    "sector_type": sector.sector_type,
                                    "source": sector.source,
                                    "weight": 1.0,
                                }
                                for code in missing
                            ],
                        )
                    print(f"  成分映射写入/更新 {len(cons_rows) + len(missing)} 条")
                except Exception as e:
                    print(f"  成分失败: {str(e)[:180]}")
                    fallback_rows = [
                        {
                            "ts_code": code,
                            "sector_code": sector.sector_code,
                            "sector_name": sector.sector_name,
                            "sector_type": sector.sector_type,
                            "source": sector.source,
                            "weight": 1.0,
                        }
                        for code in item["stocks"]
                    ]
                    total_cons += upsert_stock_sector_map(db, fallback_rows)
                    print(f"  已用F10概念关系兜底写入/更新 {len(fallback_rows)} 条")

            try:
                start_date, end_date, limit = _quote_date_range(db, sector, mode=args.mode, days=args.days)
                quote_rows = fetch_sector_daily_quotes(sector, start_date=start_date, end_date=end_date, limit=limit)
                count = upsert_sector_daily_quotes(db, quote_rows)
                total_quotes += count
                coverage = sector_quote_coverage(db, sector.sector_code)
                status = "success" if _is_complete(coverage, args.days) else "partial"
                refresh_quote_sync_state(
                    db,
                    sector,
                    status=status,
                    target_days=args.days,
                    reset_attempts=True,
                )
                print(f"  K线写入/更新 {count} 行")
            except Exception as e:
                failed_state = refresh_quote_sync_state(
                    db,
                    sector,
                    status="cooldown",
                    target_days=args.days,
                    last_error=str(e)[:500],
                    next_retry_at=_next_retry_at((state.attempts or 0) + 1),
                    increment_attempts=True,
                )
                print(
                    f"  K线失败: {str(e)[:180]}；"
                    f"下次重试 {failed_state.next_retry_at.strftime('%Y-%m-%d %H:%M:%S') if failed_state.next_retry_at else '-'}"
                )
            time.sleep(0.35)

        print(f"完成，成分映射累计 {total_cons} 条，K线累计 {total_quotes} 行，跳过 {skipped} 个概念")
    finally:
        db.close()


if __name__ == "__main__":
    main()
