from __future__ import annotations

import sys
from types import SimpleNamespace

import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.sector import SectorBasic, SectorDailyQuote, SectorQuoteSyncState, StockSectorMap
from app.models.stock import DailyQuote
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


def test_fetch_sector_daily_quotes_falls_back_to_akshare(monkeypatch):
    sector = SectorBasic(
        sector_code="BK0714",
        sector_name="5G概念",
        sector_type="concept",
        source=svc.SOURCE,
        raw_code="BK0714",
    )

    def fail_primary(*args, **kwargs):
        raise svc.EastMoneyRequestError("primary closed")

    def fake_concept_hist_em(**kwargs):
        assert kwargs["symbol"] == "5G概念"
        return pd.DataFrame(
            [
                {
                    "日期": "2026-07-06",
                    "开盘": 100.0,
                    "收盘": 101.0,
                    "最高": 102.0,
                    "最低": 99.0,
                    "涨跌幅": 1.0,
                    "成交量": 100000,
                    "成交额": 200000000,
                },
                {
                    "日期": "2026-07-07",
                    "开盘": 101.0,
                    "收盘": 103.0,
                    "最高": 104.0,
                    "最低": 100.5,
                    "涨跌幅": 1.98,
                    "成交量": 120000,
                    "成交额": 240000000,
                },
            ]
        )

    fake_akshare = SimpleNamespace(stock_board_concept_hist_em=fake_concept_hist_em)
    monkeypatch.setattr(svc, "_em_get_json", fail_primary)
    monkeypatch.setitem(sys.modules, "akshare", fake_akshare)

    rows = svc.fetch_sector_daily_quotes(sector, start_date="20260701", end_date="20260707", limit=1)

    assert len(rows) == 1
    assert rows[0]["trade_date"] == "20260707"
    assert rows[0]["sector_code"] == "BK0714"
    assert rows[0]["close"] == 103.0


def test_build_local_proxy_sector_daily_quotes_from_member_returns():
    db = _session()
    sector = SectorBasic(
        sector_code="BKAI",
        sector_name="AI算力",
        sector_type="concept",
        source=svc.SOURCE,
        raw_code="BKAI",
    )
    db.add(sector)
    for code in ["000001.SZ", "000002.SZ", "000003.SZ"]:
        db.add(
            StockSectorMap(
                ts_code=code,
                sector_code="BKAI",
                sector_name="AI算力",
                sector_type="concept",
                source=svc.SOURCE,
            )
        )
        close = 10.0
        for idx, date in enumerate(["20260701", "20260702", "20260703"], start=1):
            pct = 1.0 * idx
            close *= 1 + pct / 100
            db.add(
                DailyQuote(
                    ts_code=code,
                    trade_date=date,
                    close=close,
                    pct_chg=pct,
                    vol=1000.0,
                    amount=100000.0,
                )
            )
    db.commit()

    rows = svc.build_local_proxy_sector_daily_quotes(
        db,
        sector,
        start_date="20260701",
        end_date="20260703",
        min_members=3,
    )

    assert [row["trade_date"] for row in rows] == ["20260701", "20260702", "20260703"]
    assert rows[0]["source"] == svc.LOCAL_PROXY_SOURCE
    assert rows[-1]["pct_chg"] == 3.0
    assert rows[-1]["amount"] == 300000.0
