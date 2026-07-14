from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.database import Base, get_db
from app.exceptions import AppError, app_error_handler
from app.models.pool import WatchPool, WatchStock
from app.models.sector import SectorBasic, StockSectorMap
from app.models.stock import DailyQuote, StockBasic
from app.routers.pools import router


def _client() -> tuple[TestClient, sessionmaker]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app = FastAPI()
    app.dependency_overrides[get_db] = override_get_db
    app.add_exception_handler(AppError, app_error_handler)
    app.include_router(router)
    return TestClient(app), TestingSessionLocal


def test_cleanup_pool_sector_only_removes_current_pool_matches():
    client, Session = _client()
    db = Session()
    try:
        db.add_all(
            [
                WatchPool(id="pool-main", name="主升浪"),
                WatchPool(id="pool-other", name="其它池"),
                WatchStock(id="s1", pool_id="pool-main", ts_code="000001.SZ"),
                WatchStock(id="s2", pool_id="pool-main", ts_code="000002.SZ", pinned=True),
                WatchStock(id="s3", pool_id="pool-main", ts_code="000003.SZ"),
                WatchStock(id="s4", pool_id="pool-other", ts_code="000001.SZ"),
                StockBasic(ts_code="000001.SZ", symbol="000001", name="养老一号"),
                StockBasic(ts_code="000002.SZ", symbol="000002", name="养老二号"),
                StockBasic(ts_code="000003.SZ", symbol="000003", name="机器人三号"),
                SectorBasic(sector_code="BKYL", sector_name="养老概念", sector_type="concept", source="eastmoney"),
                StockSectorMap(ts_code="000001.SZ", sector_code="BKYL", sector_name="养老概念", sector_type="concept", source="eastmoney"),
                StockSectorMap(ts_code="000002.SZ", sector_code="BKYL", sector_name="养老概念", sector_type="concept", source="eastmoney"),
                StockSectorMap(ts_code="000003.SZ", sector_code="BKROBOT", sector_name="机器人", sector_type="concept", source="eastmoney"),
            ]
        )
        db.commit()
    finally:
        db.close()

    preview = client.post(
        "/api/pools/pool-main/cleanup/sector",
        json={"sector_code": "BKYL", "dry_run": True},
    )
    assert preview.status_code == 200
    assert preview.json()["candidate_count"] == 2
    assert preview.json()["deleted_count"] == 0
    assert preview.json()["pinned_count"] == 1

    executed = client.post(
        "/api/pools/pool-main/cleanup/sector",
        json={"sector_code": "BKYL", "dry_run": False},
    )
    assert executed.status_code == 200
    assert executed.json()["deleted_count"] == 2

    db = Session()
    try:
        remaining_main = {
            row.ts_code
            for row in db.query(WatchStock).filter(WatchStock.pool_id == "pool-main").all()
        }
        remaining_other = {
            row.ts_code
            for row in db.query(WatchStock).filter(WatchStock.pool_id == "pool-other").all()
        }
    finally:
        db.close()

    assert remaining_main == {"000003.SZ"}
    assert remaining_other == {"000001.SZ"}


def test_list_stocks_default_path_paginates_before_enrichment():
    client, Session = _client()
    db = Session()
    try:
        db.add(WatchPool(id="pool-main", name="主升浪"))
        db.add_all(
            [
                WatchStock(id="s1", pool_id="pool-main", ts_code="000001.SZ", limit_up_date="20260701"),
                WatchStock(id="s2", pool_id="pool-main", ts_code="000002.SZ", limit_up_date="20260704", pinned=True),
                WatchStock(id="s3", pool_id="pool-main", ts_code="000003.SZ", limit_up_date="20260703"),
                WatchStock(id="s4", pool_id="pool-main", ts_code="000004.SZ", limit_up_date="20260702"),
                StockBasic(ts_code="000001.SZ", symbol="000001", name="平安银行"),
                StockBasic(ts_code="000002.SZ", symbol="000002", name="万科A"),
                StockBasic(ts_code="000003.SZ", symbol="000003", name="国华网安"),
                StockBasic(ts_code="000004.SZ", symbol="000004", name="ST国华"),
                DailyQuote(ts_code="000001.SZ", trade_date="20260708", close=10.0, pct_chg=1.0),
                DailyQuote(ts_code="000002.SZ", trade_date="20260708", close=20.0, pct_chg=2.0),
                DailyQuote(ts_code="000003.SZ", trade_date="20260708", close=30.0, pct_chg=3.0),
                DailyQuote(ts_code="000004.SZ", trade_date="20260708", close=40.0, pct_chg=4.0),
                StockSectorMap(ts_code="000002.SZ", sector_code="BK5G", sector_name="5G概念", sector_type="concept", source="eastmoney"),
                StockSectorMap(ts_code="000004.SZ", sector_code="BK5G", sector_name="5G概念", sector_type="concept", source="eastmoney"),
            ]
        )
        db.commit()
    finally:
        db.close()

    res = client.get(
        "/api/pools/pool-main/stocks",
        params={"page": 1, "size": 2, "sort_by": "limit_up_date", "order": "desc"},
    )

    assert res.status_code == 200
    payload = res.json()
    assert payload["total"] == 4
    assert [item["ts_code"] for item in payload["items"]] == ["000002.SZ", "000003.SZ"]
    assert payload["items"][0]["stock_name"] == "万科A"
    assert payload["items"][0]["latest_price"] == 20.0

    sector_res = client.get(
        "/api/pools/pool-main/stocks",
        params={"page": 1, "size": 10, "sort_by": "limit_up_date", "order": "desc", "sector_code": "BK5G"},
    )
    assert sector_res.status_code == 200
    sector_payload = sector_res.json()
    assert sector_payload["total"] == 2
    assert [item["ts_code"] for item in sector_payload["items"]] == ["000002.SZ", "000004.SZ"]
