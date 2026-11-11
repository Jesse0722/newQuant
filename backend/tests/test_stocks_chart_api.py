from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models.stock import DailyQuote, StockBasic
from app.routers import stocks as stocks_router


def _client() -> TestClient:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    db = TestingSessionLocal()
    try:
        db.add(StockBasic(ts_code="300502.SZ", symbol="300502", name="新易盛"))
        start = date(2026, 1, 1)
        for i in range(30):
            trade_date = (start + timedelta(days=i)).strftime("%Y%m%d")
            close = 100 + i
            db.add(
                DailyQuote(
                    ts_code="300502.SZ",
                    trade_date=trade_date,
                    open=close - 1,
                    high=close + 2,
                    low=close - 2,
                    close=close,
                    pre_close=close - 1,
                    change=1,
                    pct_chg=1,
                    vol=1000 + i,
                    amount=100000 + i,
                )
            )
        db.commit()
    finally:
        db.close()

    def override_get_db():
        test_db = TestingSessionLocal()
        try:
            yield test_db
        finally:
            test_db.close()

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def test_stock_chart_accepts_bare_ts_code(monkeypatch):
    monkeypatch.setattr("app.routers.stocks._fetch_stock_concept_tags", lambda _ts_code: [])
    client = _client()
    try:
        res = client.get("/api/stocks/300502/chart?period=10&auto_sync_latest=false")
        assert res.status_code == 200
        body = res.json()
        assert body["basic"]["ts_code"] == "300502.SZ"
        assert len(body["quotes"]) == 10
        assert body["quotes"][-1]["date"] == "20260130"
    finally:
        app.dependency_overrides.clear()


def test_sparse_chart_fallback_normalizes_direct_leaf_before_writing(monkeypatch):
    class EmptyProvider:
        def get_daily(self, **kwargs):
            return pd.DataFrame()

    monkeypatch.setattr(
        stocks_router.TencentAdapter,
        "get_daily",
        lambda self, **kwargs: pd.DataFrame(),
    )
    monkeypatch.setattr(stocks_router, "tushare_adapter", EmptyProvider())
    monkeypatch.setattr(
        stocks_router.BaoStockAdapter,
        "get_daily",
        lambda self, **kwargs: pd.DataFrame(
            [
                {
                    "ts_code": kwargs["ts_code"],
                    "trade_date": "20261008",
                    "open": 10,
                    "high": 11,
                    "low": 9,
                    "close": 10,
                    "pre_close": 9.5,
                    "change": 0.5,
                    "pct_chg": 0,
                    "vol": 1000,
                    "amount": 20000,
                    "turnover_rate": 1.2,
                },
                {
                    "ts_code": "000002.SZ",
                    "trade_date": "20261009",
                    "open": 20,
                    "high": 21,
                    "low": 19,
                    "close": 20,
                    "pre_close": 19,
                    "change": 1,
                    "pct_chg": 0,
                    "vol": 2000,
                    "amount": 40000,
                    "turnover_rate": 2.4,
                },
            ]
        ),
    )

    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine, tables=[DailyQuote.__table__])
    session_factory = sessionmaker(bind=engine)
    with session_factory() as db:
        result = stocks_router._backfill_sparse_chart_from_remote(
            db,
            "000001.SZ",
            pd.DataFrame(),
            60,
        )
        stored = db.get(DailyQuote, ("000001.SZ", "20261008"))
        wrong_code_row = db.get(DailyQuote, ("000001.SZ", "20261009"))

    assert len(result) == 1
    assert result.iloc[0]["vol"] == 10
    assert result.iloc[0]["amount"] == 20
    assert result.iloc[0]["pre_close"] == 9.5
    assert result.iloc[0]["change"] == 0.5
    assert stored.vol == 10
    assert stored.amount == 20
    assert stored.pre_close == 9.5
    assert stored.change == 0.5
    assert wrong_code_row is None
    engine.dispose()
