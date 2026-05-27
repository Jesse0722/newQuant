from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.database import Base, get_db
from app.routers.industry_reports import router as industry_router
from app.routers.messages import router as messages_router
from app.routers.message_graph import router as graph_router


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
    app.include_router(messages_router)
    app.include_router(graph_router)
    app.include_router(industry_router)
    return TestClient(app)


def test_import_seed_graph_and_query_paths():
    client = _client()

    imported = client.post("/api/message-graph/import-seeds")

    assert imported.status_code == 200
    body = imported.json()
    assert body["entity_created"] > 0
    assert body["relation_created"] > 0

    paths = client.get("/api/message-graph/paths", params={"entity": "Rubin", "max_depth": 3})

    assert paths.status_code == 200
    assert any(path["end"] == "铜连接" for path in paths.json())


def test_generate_industry_report_from_seed_graph():
    client = _client()

    resp = client.post(
        "/api/industry-reports/generate",
        json={"trade_date": "20260528", "refresh_seeds": True},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["trade_date"] == "20260528"
    assert body["status"] == "success"
    assert body["report_json"]["candidate_count"] > 0
    assert body["candidates"]
    assert all(candidate["path_json"] for candidate in body["candidates"])
    assert all(candidate["grade"] in {"strong", "medium", "weak", "risk_watch"} for candidate in body["candidates"])

    daily = client.get("/api/industry-reports/daily?trade_date=20260528")
    assert daily.status_code == 200
    assert daily.json()["id"] == body["id"]


def test_generate_industry_report_with_mocked_llm(monkeypatch):
    client = _client()

    def fake_llm(_prompt: str, provider: str, model: str, temperature: float = 0.1):
        assert provider == "deepseek"
        return """
        {
          "headline": "今日主线：AI服务器",
          "summary": "AI服务器链条待验证候选增多。",
          "core_catalysts": ["AI服务器"],
          "industry_paths": [],
          "candidate_summary": [],
          "risk_flags": ["待验证"],
          "next_actions": ["加入观察池等待买点雷达确认"]
        }
        """

    monkeypatch.setattr("app.services.industry_report_service.call_llm_model", fake_llm)
    resp = client.post(
        "/api/industry-reports/generate",
        json={"trade_date": "20260528", "refresh_seeds": True, "use_llm": True},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["headline"] == "今日主线：AI服务器"
    assert body["model_provider"] == "deepseek"
    assert body["report_json"]["risk_flags"] == ["待验证"]


def test_llm_report_output_is_sanitized(monkeypatch):
    client = _client()

    def fake_llm(_prompt: str, provider: str, model: str, temperature: float = 0.1):
        return """
        {
          "headline": ["bad"],
          "summary": "确定买入，稳赚",
          "core_catalysts": ["AI服务器", 123],
          "industry_paths": [{"theme": "AI服务器", "path": ["AI算力", "AI服务器"], "evidence_level": "medium"}],
          "candidate_summary": [{"ts_code": "601138.SH", "stock_name": "工业富联", "grade": "medium", "reason": "强烈推荐买入"}],
          "risk_flags": ["无风险"],
          "next_actions": ["加入观察池等待买点雷达确认"]
        }
        """

    monkeypatch.setattr("app.services.industry_report_service.call_llm_model", fake_llm)
    resp = client.post(
        "/api/industry-reports/generate",
        json={"trade_date": "20260528", "refresh_seeds": True, "use_llm": True},
    )

    assert resp.status_code == 200
    body = resp.json()
    text = str(body["report_json"]) + str(body["summary"])
    assert "确定买入" not in text
    assert "稳赚" not in text
    assert "强烈推荐买入" not in text
    assert "无风险" not in text
    assert body["headline"] == "今日主线：AI算力"


def test_extract_relations_from_source_item(monkeypatch):
    client = _client()

    def fake_llm(_prompt: str, provider: str, model: str, temperature: float = 0.1):
        assert provider == "deepseek"
        assert model == "deepseek-v4-flash"
        return """
        {
          "entities": [
            {"name": "Rubin", "entity_type": "product", "confidence": 80},
            {"name": "NVLink", "entity_type": "technology", "confidence": 78}
          ],
          "relations": [
            {"source": "Rubin", "relation_type": "uses", "target": "NVLink", "confidence": 76, "evidence_text": "Rubin uses NVLink"}
          ]
        }
        """

    monkeypatch.setattr("app.services.message_extraction_service.call_llm_model", fake_llm)
    imported = client.post(
        "/api/messages/source-items/import",
        json={
            "aggregate": False,
            "items": [
                {
                    "trade_date": "20260528",
                    "channel": "X",
                    "source_name": "semi",
                    "content": "Rubin uses NVLink in the AI server platform.",
                    "theme": "NVIDIA产业链",
                    "heat_score": 80,
                    "credibility_score": 65,
                }
            ],
        },
    )
    assert imported.status_code == 201

    extracted = client.post(
        "/api/message-graph/extract",
        json={"trade_date": "20260528", "limit": 5, "provider": "deepseek", "model": "deepseek-v4-flash"},
    )

    assert extracted.status_code == 200
    body = extracted.json()
    assert body["processed_count"] == 1
    assert body["relation_count"] >= 1
    assert body["evidence_count"] == 1
