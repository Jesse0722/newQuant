from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.sector import SectorDailyQuote, StockSectorMap
from app.models.pool import WatchPool, WatchStock
from app.models.sector import SectorBasic
from app.models.stock import DailyQuote, StockBasic
from app.services import strategy_service
from app.services.main_wave_service import analyze_main_wave_stock


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    return Session()


def test_analyze_main_wave_stock_scores_uptrend_with_sector_resonance():
    db = _session()
    db.add(StockBasic(ts_code="000001.SZ", symbol="000001", name="测试股份", industry="AI算力"))
    db.add(
        StockSectorMap(
            ts_code="000001.SZ",
            sector_code="em_concept_AI",
            sector_name="AI算力",
            sector_type="concept",
            source="eastmoney",
        )
    )

    price = 10.0
    sector_price = 100.0
    for i in range(90):
        trade_date = f"2026{(i // 30) + 1:02d}{(i % 30) + 1:02d}"
        if i == 70:
            price *= 1.10
        else:
            price *= 1.006
        sector_price *= 1.003
        db.add(
            DailyQuote(
                ts_code="000001.SZ",
                trade_date=trade_date,
                open=price * 0.99,
                high=price * 1.02,
                low=price * 0.98,
                close=price,
                pct_chg=10.0 if i == 70 else 0.6,
                vol=300000.0 if i == 70 else 100000.0,
                amount=price * 100000.0,
            )
        )
        db.add(
            SectorDailyQuote(
                sector_code="em_concept_AI",
                trade_date=trade_date,
                sector_name="AI算力",
                sector_type="concept",
                source="eastmoney",
                open=sector_price * 0.99,
                high=sector_price * 1.01,
                low=sector_price * 0.98,
                close=sector_price,
                pct_chg=0.3,
            )
        )
    db.commit()

    result = analyze_main_wave_stock(db, "000001.SZ")

    assert result["status"] in {"watching", "breakout_tracking", "main_wave_confirmed"}
    assert result["total_score"] >= 60
    assert result["ma20_state"]["state"] == "above"
    assert result["scores"]["sector_resonance"] > 0


def test_main_wave_scope_fetches_missing_sector_constituents_and_intersects_pool(monkeypatch):
    db = _session()
    pool = WatchPool(id="pool-1", name="涨停股票观察池")
    db.add(pool)
    db.add_all(
        [
            WatchStock(pool_id="pool-1", ts_code="000001.SZ"),
            WatchStock(pool_id="pool-1", ts_code="000002.SZ"),
            StockBasic(ts_code="000001.SZ", symbol="000001", name="池内绿色电力"),
            StockBasic(ts_code="000002.SZ", symbol="000002", name="池内非绿色"),
            StockBasic(ts_code="000003.SZ", symbol="000003", name="池外绿色电力"),
            SectorBasic(
                sector_code="BK1024",
                sector_name="绿色电力",
                sector_type="concept",
                source="eastmoney_direct",
                raw_code="BK1024",
            ),
        ]
    )
    db.commit()

    def fake_fetch_sector_constituents(sector):
        assert sector.sector_code == "BK1024"
        return [
            {
                "ts_code": "000001.SZ",
                "sector_code": "BK1024",
                "sector_name": "绿色电力",
                "sector_type": "concept",
                "source": "eastmoney_direct",
            },
            {
                "ts_code": "000003.SZ",
                "sector_code": "BK1024",
                "sector_name": "绿色电力",
                "sector_type": "concept",
                "source": "eastmoney_direct",
            },
        ]

    monkeypatch.setattr(strategy_service, "fetch_sector_constituents", fake_fetch_sector_constituents)

    codes = strategy_service._main_wave_scope_codes(db, "pool-1", ["BK1024"], "any")

    assert codes == ["000001.SZ"]
    assert db.query(StockSectorMap).filter(StockSectorMap.sector_code == "BK1024").count() == 2


def test_main_wave_scope_falls_back_to_pool_stock_f10_when_sector_constituents_fail(monkeypatch):
    db = _session()
    db.add(WatchPool(id="pool-1", name="涨停股票观察池"))
    db.add_all(
        [
            WatchStock(pool_id="pool-1", ts_code="000001.SZ"),
            WatchStock(pool_id="pool-1", ts_code="000002.SZ"),
            SectorBasic(
                sector_code="BK1024",
                sector_name="绿色电力",
                sector_type="concept",
                source="eastmoney_direct",
                raw_code="BK1024",
            ),
        ]
    )
    db.commit()

    def fail_fetch_sector_constituents(_sector):
        raise RuntimeError("eastmoney blocked")

    def fake_fetch_stock_concept_sectors(ts_code):
        if ts_code == "000001.SZ":
            return [
                {
                    "sector_code": "BK1024",
                    "sector_name": "绿色电力",
                    "sector_type": "concept",
                    "source": "eastmoney_direct",
                    "raw_code": "BK1024",
                }
            ]
        return [
            {
                "sector_code": "BK9999",
                "sector_name": "其他概念",
                "sector_type": "concept",
                "source": "eastmoney_direct",
            }
        ]

    monkeypatch.setattr(strategy_service, "fetch_sector_constituents", fail_fetch_sector_constituents)
    monkeypatch.setattr(strategy_service, "fetch_stock_concept_sectors", fake_fetch_stock_concept_sectors)

    codes = strategy_service._main_wave_scope_codes(db, "pool-1", ["BK1024"], "any")

    assert codes == ["000001.SZ"]
    saved = db.query(StockSectorMap).filter(StockSectorMap.sector_code == "BK1024").one()
    assert saved.ts_code == "000001.SZ"
