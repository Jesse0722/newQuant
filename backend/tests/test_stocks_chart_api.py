from __future__ import annotations

from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models.stock import DailyQuote, StockBasic


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
