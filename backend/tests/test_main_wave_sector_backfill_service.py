from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.pool import WatchPool, WatchStock
from app.models.sector import SectorBasic, SectorDailyQuote, StockSectorMap
from app.models.stock import DailyQuote, StockBasic
from app.services import main_wave_sector_backfill_service as svc
from app.services.sector_data_service import SOURCE


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    return Session()


def _date_range(start: str, count: int) -> list[str]:
    base = datetime.strptime(start, "%Y%m%d")
    return [(base + timedelta(days=i)).strftime("%Y%m%d") for i in range(count)]


def test_backfill_status_marks_enough_but_stale_sector_quotes_not_completed():
    db = _session()
    pool = WatchPool(id="pool-main-wave", name="主升浪样本池")
    db.add(pool)
    db.add_all(
        [
            WatchStock(pool_id=pool.id, ts_code="000001.SZ"),
            StockBasic(ts_code="000001.SZ", symbol="000001", name="新鲜股份", industry="AI算力"),
            SectorBasic(
                sector_code="BKAI",
                sector_name="AI算力",
                sector_type="concept",
                source=SOURCE,
                raw_code="BKAI",
            ),
            StockSectorMap(
                ts_code="000001.SZ",
                sector_code="BKAI",
                sector_name="AI算力",
                sector_type="concept",
                source=SOURCE,
                weight=1.0,
            ),
        ]
    )
    for trade_date in _date_range("20260409", 90):
        db.add(
            DailyQuote(
                ts_code="000001.SZ",
                trade_date=trade_date,
                close=10.0,
                pct_chg=0.5,
                vol=100000.0,
                amount=1000000.0,
            )
        )
    for trade_date in _date_range("20250915", 250):
        db.add(
            SectorDailyQuote(
                sector_code="BKAI",
                trade_date=trade_date,
                sector_name="AI算力",
                sector_type="concept",
                source=SOURCE,
                close=100.0,
                pct_chg=0.2,
            )
        )
    db.commit()

    status = svc.get_main_wave_sector_backfill_status(db, pool_id=pool.id, target_days=250)

    assert status["required_trade_date"] == "20260707"
    assert status["completed_count"] == 0
    assert status["stale_count"] == 1
    item = status["items"][0]
    assert item["status"] == "stale"
    assert item["quote_count"] == 250
    assert item["is_fresh"] is False
    assert item["freshness_lag_days"] > 10
    assert "落后股票最新K线" in item["freshness_warning"]


def test_is_complete_requires_quote_count_and_freshness():
    stale_coverage = {
        "quote_count": 250,
        "first_trade_date": "20250915",
        "last_trade_date": "20260522",
    }
    fresh_coverage = {
        "quote_count": 250,
        "first_trade_date": "20250915",
        "last_trade_date": "20260707",
    }

    assert svc._is_complete(stale_coverage, 250, "20260707") is False
    assert svc._coverage_status(stale_coverage, 250, "20260707") == "stale"
    assert svc._is_complete(fresh_coverage, 250, "20260707") is True
