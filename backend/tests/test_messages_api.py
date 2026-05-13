from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.database import Base, get_db
from app.routers.messages import router


def _client() -> TestClient:
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
    app.include_router(router)
    return TestClient(app)


def test_daily_messages_auto_seed_today():
    client = _client()

    resp = client.get("/api/messages/daily?trade_date=20260514")

    assert resp.status_code == 200
    body = resp.json()
    assert body["trade_date"] == "20260514"
    assert body["stats"]["topic_count"] >= 4
    assert body["stats"]["opportunity_count"] >= 5
    assert body["stats"]["top_score"] >= 80
    assert any(item["theme"] == "AI算力" for item in body["topics"])
    assert any(item["ts_code"] == "300308.SZ" for item in body["opportunities"])


def test_topic_upsert_is_idempotent():
    client = _client()
    payload = {
        "trade_date": "20260514",
        "theme": "AI电力",
        "summary": "first",
        "heat_score": 70,
    }

    first = client.post("/api/messages/topics", json=payload)
    second = client.post("/api/messages/topics", json={**payload, "summary": "updated", "heat_score": 82})

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    assert second.json()["summary"] == "updated"
    assert second.json()["heat_score"] == 82


def test_created_opportunity_appears_in_daily_without_seed():
    client = _client()
    topic = client.post(
        "/api/messages/topics",
        json={
            "trade_date": "20260514",
            "theme": "CPO",
            "summary": "光模块方向",
            "heat_score": 75,
        },
    ).json()

    resp = client.post(
        "/api/messages/opportunities",
        json={
            "trade_date": "20260514",
            "topic_id": topic["id"],
            "theme": "CPO",
            "ts_code": "300502.SZ",
            "stock_name": "新易盛",
            "opportunity_score": 89,
            "reason": "CPO 主题扩散到光模块个股。",
            "source_platforms": ["Twitter", "雪球"],
        },
    )
    assert resp.status_code == 201

    daily = client.get("/api/messages/daily?trade_date=20260514&ensure_seed=false").json()

    assert daily["stats"]["opportunity_count"] == 1
    assert daily["opportunities"][0]["ts_code"] == "300502.SZ"
    assert daily["opportunities"][0]["source_platforms"] == ["Twitter", "雪球"]
