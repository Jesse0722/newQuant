from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.sector import SectorDailyQuote, StockSectorMap
from app.models.stock import DailyQuote, StockBasic
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
