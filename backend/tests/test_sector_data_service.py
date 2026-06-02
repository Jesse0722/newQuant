from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.sector import SectorBasic, SectorDailyQuote, SectorQuoteSyncState, StockSectorMap
from app.services import sector_data_service as svc


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    return Session()


def test_sync_sector_data_upserts_basic_constituents_and_quotes(monkeypatch):
    db = _session()

    monkeypatch.setattr(
        svc,
        "fetch_sector_list",
        lambda sector_type: [
            {
                "sector_code": f"em_{sector_type}_BK_TEST",
                "sector_name": "AI算力" if sector_type == "concept" else "通信设备",
                "sector_type": sector_type,
                "source": svc.SOURCE,
                "raw_code": "BK_TEST",
                "rank": 1,
                "latest_pct_chg": 2.5,
                "latest_hot": None,
            }
        ],
    )
    monkeypatch.setattr(
        svc,
        "fetch_sector_constituents",
        lambda sector: [
            {
                "ts_code": "000001.SZ",
                "sector_code": sector.sector_code,
                "sector_name": sector.sector_name,
                "sector_type": sector.sector_type,
                "source": sector.source,
            }
        ],
    )
    monkeypatch.setattr(
        svc,
        "fetch_sector_daily_quotes",
        lambda sector, start_date, end_date: [
            {
                "sector_code": sector.sector_code,
                "trade_date": "20260522",
                "sector_name": sector.sector_name,
                "sector_type": sector.sector_type,
                "source": sector.source,
                "open": 100.0,
                "high": 103.0,
                "low": 99.0,
                "close": 102.0,
                "pct_chg": 2.0,
                "change": 2.0,
                "vol": 100000.0,
                "amount": 200000000.0,
                "turnover_rate": None,
            }
        ],
    )

    result = svc.sync_sector_data(db, sector_types=["concept"], limit=10)

    assert result["sector_count"] == 1
    assert result["constituent_count"] == 1
    assert result["quote_count"] == 1
    assert db.query(SectorBasic).count() == 1
    assert db.query(StockSectorMap).count() == 1
    assert db.query(SectorDailyQuote).count() == 1


def test_upsert_sector_daily_quotes_updates_existing_row():
    db = _session()
    row = {
        "sector_code": "em_concept_BK_TEST",
        "trade_date": "20260522",
        "sector_name": "AI算力",
        "sector_type": "concept",
        "source": svc.SOURCE,
        "open": 100.0,
        "high": 103.0,
        "low": 99.0,
        "close": 102.0,
        "pct_chg": 2.0,
        "change": 2.0,
        "vol": 100000.0,
        "amount": 200000000.0,
        "turnover_rate": None,
    }

    svc.upsert_sector_daily_quotes(db, [row])
    svc.upsert_sector_daily_quotes(db, [{**row, "close": 105.0, "pct_chg": 5.0}])

    saved = db.query(SectorDailyQuote).first()
    assert db.query(SectorDailyQuote).count() == 1
    assert saved.close == 105.0
    assert saved.pct_chg == 5.0


def test_upsert_stock_sector_map_ignores_extra_source_fields():
    db = _session()

    svc.upsert_stock_sector_map(
        db,
        [
            {
                "ts_code": "000001.SZ",
                "sector_code": "BK1024",
                "sector_name": "绿色电力",
                "sector_type": "concept",
                "source": svc.SOURCE,
                "raw_code": "BK1024",
                "rank": 3,
                "weight": 1.0,
            }
        ],
    )

    saved = db.query(StockSectorMap).one()
    assert saved.ts_code == "000001.SZ"
    assert saved.sector_code == "BK1024"
    assert saved.sector_name == "绿色电力"


def test_refresh_quote_sync_state_tracks_coverage():
    db = _session()
    sector = SectorBasic(
        sector_code="BK_TEST",
        sector_name="AI算力",
        sector_type="concept",
        source=svc.SOURCE,
        raw_code="BK_TEST",
    )
    db.add(sector)
    db.commit()

    svc.upsert_sector_daily_quotes(
        db,
        [
            {
                "sector_code": "BK_TEST",
                "trade_date": "20260521",
                "sector_name": "AI算力",
                "sector_type": "concept",
                "source": svc.SOURCE,
                "close": 100.0,
            },
            {
                "sector_code": "BK_TEST",
                "trade_date": "20260522",
                "sector_name": "AI算力",
                "sector_type": "concept",
                "source": svc.SOURCE,
                "close": 102.0,
            },
        ],
    )

    state = svc.refresh_quote_sync_state(db, sector, status="partial", target_days=250)

    assert db.query(SectorQuoteSyncState).count() == 1
    assert state.status == "partial"
    assert state.quote_count == 2
    assert state.first_trade_date == "20260521"
    assert state.last_trade_date == "20260522"
