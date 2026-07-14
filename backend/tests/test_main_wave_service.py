from __future__ import annotations

from datetime import datetime, timedelta

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


def _date_range(start: str, count: int) -> list[str]:
    base = datetime.strptime(start, "%Y%m%d")
    return [(base + timedelta(days=i)).strftime("%Y%m%d") for i in range(count)]


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


def test_analyze_main_wave_stock_respects_as_of_date():
    db = _session()
    db.add(StockBasic(ts_code="000012.SZ", symbol="000012", name="历史股份", industry="软件开发"))

    price = 10.0
    for trade_date in _date_range("20260401", 80):
        price *= 1.01
        db.add(
            DailyQuote(
                ts_code="000012.SZ",
                trade_date=trade_date,
                open=price * 0.99,
                high=price * 1.02,
                low=price * 0.98,
                close=price,
                pct_chg=1.0,
                vol=100000.0,
                amount=price * 100000.0,
            )
        )
    db.commit()

    result = analyze_main_wave_stock(db, "000012.SZ", as_of_date="20260530")

    assert result["trade_date"] == "20260530"
    assert result["metrics"]["latest_close"] < price


def test_analyze_main_wave_stock_marks_overheated_as_avoid_chase():
    db = _session()
    db.add(StockBasic(ts_code="000010.SZ", symbol="000010", name="过热股份", industry="半导体"))

    price = 10.0
    for i, trade_date in enumerate(_date_range("20260401", 90)):
        if i >= 70:
            price *= 1.055
        else:
            price *= 1.006
        db.add(
            DailyQuote(
                ts_code="000010.SZ",
                trade_date=trade_date,
                open=price * 0.98,
                high=price * 1.03,
                low=price * 0.97,
                close=price,
                pct_chg=5.5 if i >= 70 else 0.6,
                vol=350000.0 if i == 70 else 100000.0,
                amount=price * 100000.0,
            )
        )
    db.commit()

    result = analyze_main_wave_stock(db, "000010.SZ")

    assert result["total_score"] >= 60
    assert result["status"] == "accelerating_hot"
    assert result["entry"]["stage"] == "avoid_chase"
    assert result["entry"]["score"] <= 55
    assert result["metrics"]["overheat"]["reasons"]


def test_analyze_main_wave_stock_rewards_market_relative_strength():
    db = _session()
    db.add(StockBasic(ts_code="300001.SZ", symbol="300001", name="逆势股份", industry="软件开发"))

    dates = _date_range("20260409", 90)
    target_price = 10.0
    peer_prices = {"300002.SZ": 10.0, "300003.SZ": 10.0, "300004.SZ": 10.0}
    for idx, trade_date in enumerate(dates):
        target_pct = 1.0
        target_price *= 1 + target_pct / 100
        db.add(
            DailyQuote(
                ts_code="300001.SZ",
                trade_date=trade_date,
                open=target_price * 0.99,
                high=target_price * 1.02,
                low=target_price * 0.98,
                close=target_price,
                pct_chg=target_pct,
                vol=100000.0,
                amount=target_price * 100000.0,
            )
        )
        for code, price in list(peer_prices.items()):
            peer_pct = -2.0 if idx == len(dates) - 1 else 0.0
            price *= 1 + peer_pct / 100
            peer_prices[code] = price
            db.add(
                DailyQuote(
                    ts_code=code,
                    trade_date=trade_date,
                    close=price,
                    pct_chg=peer_pct,
                    vol=100000.0,
                    amount=price * 100000.0,
                )
            )
    db.commit()

    result = analyze_main_wave_stock(db, "300001.SZ")

    assert result["scores"]["market_relative"] > 0
    assert result["metrics"]["market_proxy"]["group"] == "cyb"
    assert result["metrics"]["market_proxy"]["latest_pct_chg"] < 0
    assert result["metrics"]["market_proxy"]["latest_relative_pct_chg"] >= 2
    assert "大盘/风格下跌时个股逆势上涨" in result["reasons"]["market_relative"]


def test_stale_sector_quotes_do_not_add_resonance_score():
    db = _session()
    db.add(StockBasic(ts_code="000011.SZ", symbol="000011", name="新鲜个股", industry="AI算力"))
    db.add(
        StockSectorMap(
            ts_code="000011.SZ",
            sector_code="BKAI",
            sector_name="AI算力",
            sector_type="concept",
            source="eastmoney_direct",
        )
    )
    price = 10.0
    for trade_date in _date_range("20260409", 90):
        price *= 1.006
        db.add(
            DailyQuote(
                ts_code="000011.SZ",
                trade_date=trade_date,
                open=price * 0.99,
                high=price * 1.02,
                low=price * 0.98,
                close=price,
                pct_chg=0.6,
                vol=100000.0,
                amount=price * 100000.0,
            )
        )

    sector_price = 100.0
    for trade_date in _date_range("20260413", 40):
        sector_price *= 1.01
        db.add(
            SectorDailyQuote(
                sector_code="BKAI",
                trade_date=trade_date,
                sector_name="AI算力",
                sector_type="concept",
                source="eastmoney_direct",
                open=sector_price * 0.99,
                high=sector_price * 1.01,
                low=sector_price * 0.98,
                close=sector_price,
                pct_chg=1.0,
            )
        )
    db.commit()

    result = analyze_main_wave_stock(db, "000011.SZ")

    assert result["trade_date"] == "20260707"
    assert result["scores"]["sector_resonance"] == 0
    assert result["metrics"]["sector_data_status"] == "stale"
    assert "过期" in result["metrics"]["sector_data_warning"]


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
