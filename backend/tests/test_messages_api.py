from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
import app.services.x_message_service as x_message_service
from app.database import Base, get_db
from app.exceptions import AppError, app_error_handler
from app.routers.message_agents import router as message_agents_router
from app.routers.messages import router
from app.services.x_message_service import build_x_recent_search_query, x_payload_to_source_items


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
    app.add_exception_handler(AppError, app_error_handler)
    app.include_router(router)
    app.include_router(message_agents_router)
    return TestClient(app)


def test_daily_messages_default_is_real_data_only():
    client = _client()

    resp = client.get("/api/messages/daily?trade_date=20260514")

    assert resp.status_code == 200
    body = resp.json()
    assert body["trade_date"] == "20260514"
    assert body["stats"]["topic_count"] == 0
    assert body["stats"]["opportunity_count"] == 0
    assert body["topics"] == []
    assert body["opportunities"] == []


def test_daily_messages_explicit_demo_seed():
    client = _client()

    resp = client.get("/api/messages/daily?trade_date=20260514&ensure_seed=true")

    assert resp.status_code == 200
    body = resp.json()
    assert body["stats"]["topic_count"] >= 4
    assert body["stats"]["opportunity_count"] >= 5
    assert body["stats"]["top_score"] >= 80
    assert any(item["theme"] == "AI算力" for item in body["topics"])
    assert any(item["ts_code"] == "300308.SZ" for item in body["opportunities"])


def test_daily_messages_hides_legacy_seed_rows_in_real_mode():
    client = _client()

    seeded = client.get("/api/messages/daily?trade_date=20260514&ensure_seed=true")
    assert seeded.status_code == 200

    real = client.get("/api/messages/daily?trade_date=20260514&ensure_seed=false")
    assert real.status_code == 200
    body = real.json()
    assert body["stats"]["topic_count"] == 0
    assert body["stats"]["opportunity_count"] == 0
    assert body["topics"] == []
    assert body["opportunities"] == []


def test_daily_messages_real_mode_does_not_mutate_active_rows():
    client = _client()
    topic = client.post(
        "/api/messages/topics",
        json={
            "trade_date": "20260514",
            "theme": "AI算力",
            "summary": "真实导入的历史机会不应被读取接口降级。",
            "heat_score": 75,
        },
    ).json()

    created = client.post(
        "/api/messages/opportunities",
        json={
            "trade_date": "20260514",
            "topic_id": topic["id"],
            "theme": "AI算力",
            "ts_code": "300308.SZ",
            "stock_name": "中际旭创",
            "opportunity_score": 81,
            "reason": "光模块作为 AI 数据中心扩容的高弹性方向，来自真实导入。",
            "source_platforms": ["X"],
        },
    )
    assert created.status_code == 201

    first = client.get("/api/messages/daily?trade_date=20260514&ensure_seed=false").json()
    second = client.get("/api/messages/daily?trade_date=20260514&ensure_seed=false").json()

    assert first["stats"]["opportunity_count"] == 1
    assert second["stats"]["opportunity_count"] == 1
    assert second["opportunities"][0]["status"] == "active"


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


def test_import_source_items_aggregates_topic_and_opportunity():
    client = _client()

    resp = client.post(
        "/api/messages/source-items/import",
        json={
            "aggregate": True,
            "items": [
                {
                    "trade_date": "20260514",
                    "channel": "雪球",
                    "source_name": "产业观察",
                    "title": "CPO 光模块热度提升",
                    "content": "CPO 光模块方向被反复提及，新易盛关注度提升。",
                    "url": "https://example.test/a",
                    "theme": "CPO",
                    "ts_code": "300502.SZ",
                    "stock_name": "新易盛",
                    "tags": ["光模块", "CPO"],
                    "heat_score": 78,
                    "credibility_score": 70,
                },
                {
                    "trade_date": "20260514",
                    "channel": "淘股吧",
                    "source_name": "短线情绪",
                    "title": "资金讨论 CPO 映射",
                    "content": "CPO 题材扩散到光模块个股，新易盛被多次提到。",
                    "url": "https://example.test/b",
                    "theme": "CPO",
                    "ts_code": "300502.SZ",
                    "stock_name": "新易盛",
                    "tags": ["光模块"],
                    "heat_score": 82,
                    "credibility_score": 66,
                },
            ],
        },
    )

    assert resp.status_code == 201
    body = resp.json()
    assert body["created_count"] == 2
    assert body["skipped_count"] == 0
    assert body["aggregation"]["topic_count"] == 1
    assert body["aggregation"]["opportunity_count"] == 1

    daily = client.get("/api/messages/daily?trade_date=20260514&ensure_seed=false").json()

    assert daily["stats"]["topic_count"] == 1
    assert daily["stats"]["opportunity_count"] == 1
    assert daily["topics"][0]["theme"] == "CPO"
    assert set(daily["opportunities"][0]["source_platforms"]) == {"雪球", "淘股吧"}
    assert daily["opportunities"][0]["ts_code"] == "300502.SZ"
    platforms = daily["opportunities"][0]["source_platforms"]
    links = daily["opportunities"][0]["source_links"]
    assert len(links) == len(platforms)
    assert dict(zip(platforms, links)) == {
        "淘股吧": "https://example.test/b",
        "雪球": "https://example.test/a",
    }

    evidence = client.get("/api/messages/evidence?trade_date=20260514&ts_code=300502.SZ").json()
    assert len(evidence) == 2
    assert {row["source_item"]["url"] for row in evidence} == {
        "https://example.test/a",
        "https://example.test/b",
    }
    assert all(row["status"] == "active" for row in evidence)

    opportunity_id = daily["opportunities"][0]["id"]
    linked = client.get(f"/api/messages/opportunities/{opportunity_id}/evidence").json()
    assert len(linked) == 2
    assert {row["evidence"]["source_item"]["channel"] for row in linked} == {"雪球", "淘股吧"}

    runs = client.get("/api/message-agents/runs?agent_name=rule_evidence_cleaner&trade_date=20260514").json()
    assert len(runs) == 1
    assert runs[0]["status"] == "success"
    assert runs[0]["output_json"]["source_item_count"] == 2
    assert runs[0]["output_json"]["evidence_count"] == 2


def test_import_source_items_skips_duplicates():
    client = _client()
    payload = {
        "aggregate": False,
        "items": [
            {
                "trade_date": "20260514",
                "channel": "雪球",
                "title": "重复消息",
                "content": "相同 URL 的消息只入库一次。",
                "url": "https://example.test/dup",
                "theme": "AI算力",
            }
        ],
    }

    first = client.post("/api/messages/source-items/import", json=payload)
    second = client.post("/api/messages/source-items/import", json=payload)

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["created_count"] == 1
    assert second.json()["created_count"] == 0
    assert second.json()["skipped_count"] == 1


def test_source_item_reaggregation_does_not_duplicate_evidence_or_links():
    client = _client()
    payload = {
        "aggregate": True,
        "items": [
            {
                "trade_date": "20260514",
                "channel": "雪球",
                "title": "CPO 光模块热度提升",
                "content": "CPO 光模块方向被反复提及，新易盛关注度提升。",
                "url": "https://example.test/evidence-once",
                "theme": "CPO",
                "ts_code": "300502.SZ",
                "stock_name": "新易盛",
                "tags": ["光模块", "CPO"],
                "heat_score": 78,
                "credibility_score": 70,
            }
        ],
    }

    first = client.post("/api/messages/source-items/import", json=payload)
    second = client.post("/api/messages/source-items/import", json=payload)

    assert first.status_code == 201
    assert second.status_code == 201
    evidence = client.get("/api/messages/evidence?trade_date=20260514&ts_code=300502.SZ").json()
    assert len(evidence) == 1

    daily = client.get("/api/messages/daily?trade_date=20260514&ensure_seed=false").json()
    opportunity_id = daily["opportunities"][0]["id"]
    linked = client.get(f"/api/messages/opportunities/{opportunity_id}/evidence").json()
    assert len(linked) == 1


def test_rule_evidence_cleaner_manual_run_supports_dry_run_and_persist():
    client = _client()
    imported = client.post(
        "/api/messages/source-items/import",
        json={
            "aggregate": False,
            "items": [
                {
                    "trade_date": "20260514",
                    "channel": "RSS",
                    "title": "HBM 产业链消息",
                    "content": "HBM 供需紧张带动存储芯片产业链关注。",
                    "url": "https://example.test/hbm",
                    "theme": "存储芯片",
                    "ts_code": "300475.SZ",
                    "stock_name": "香农芯创",
                    "heat_score": 76,
                    "credibility_score": 74,
                }
            ],
        },
    )
    assert imported.status_code == 201

    dry = client.post(
        "/api/message-agents/run",
        json={
            "agent_name": "rule_evidence_cleaner",
            "trade_date": "20260514",
            "dry_run": True,
        },
    )
    assert dry.status_code == 201
    assert dry.json()["created_count"] == 1
    assert dry.json()["run"] is None
    assert client.get("/api/messages/evidence?trade_date=20260514").json() == []

    persisted = client.post(
        "/api/message-agents/run",
        json={
            "agent_name": "rule_evidence_cleaner",
            "trade_date": "20260514",
        },
    )
    assert persisted.status_code == 201
    body = persisted.json()
    assert body["created_count"] == 1
    assert body["run"]["status"] == "success"

    evidence = client.get("/api/messages/evidence?trade_date=20260514&ts_code=300475.SZ").json()
    assert len(evidence) == 1
    assert evidence[0]["evidence_text"] == "HBM 产业链消息"


def test_opportunity_review_and_dismiss_prevents_reactivation():
    client = _client()
    payload = {
        "aggregate": True,
        "items": [
            {
                "trade_date": "20260514",
                "channel": "雪球",
                "title": "CPO 光模块热度提升",
                "content": "CPO 光模块方向被反复提及，新易盛关注度提升。",
                "url": "https://example.test/review",
                "theme": "CPO",
                "ts_code": "300502.SZ",
                "stock_name": "新易盛",
                "tags": ["光模块", "CPO"],
                "heat_score": 78,
                "credibility_score": 70,
            }
        ],
    }
    imported = client.post("/api/messages/source-items/import", json=payload)
    assert imported.status_code == 201
    daily = client.get("/api/messages/daily?trade_date=20260514&ensure_seed=false").json()
    opportunity = daily["opportunities"][0]
    assert opportunity["review_status"] == "reviewed"
    assert opportunity["generated_by"] == "rule"
    assert opportunity["evidence_score"] > 0
    assert opportunity["mapping_confidence"] > 0

    reviewed = client.post(
        f"/api/messages/opportunities/{opportunity['id']}/review",
        json={"review_status": "needs_review", "review_reason": "单一来源，等待验证"},
    )
    assert reviewed.status_code == 200
    assert reviewed.json()["review_status"] == "needs_review"
    assert reviewed.json()["review_reason"] == "单一来源，等待验证"

    dismissed = client.post(
        f"/api/messages/opportunities/{opportunity['id']}/dismiss",
        json={"review_reason": "映射过弱"},
    )
    assert dismissed.status_code == 200
    assert dismissed.json()["review_status"] == "dismissed"
    assert dismissed.json()["status"] == "dismissed"

    reimported = client.post("/api/messages/source-items/import", json=payload)
    assert reimported.status_code == 201
    daily_after = client.get("/api/messages/daily?trade_date=20260514&ensure_seed=false").json()
    assert daily_after["stats"]["opportunity_count"] == 0
    assert daily_after["opportunities"] == []


def test_message_agent_run_rejects_unknown_agent():
    client = _client()

    resp = client.post(
        "/api/message-agents/run",
        json={
            "agent_name": "unknown_agent",
            "trade_date": "20260514",
        },
    )

    assert resp.status_code == 400
    assert resp.json()["message"] == "暂不支持的 Agent"


def test_llm_evidence_cleaner_uses_deepseek_and_sanitizes(monkeypatch):
    client = _client()

    imported = client.post(
        "/api/messages/source-items/import",
        json={
            "aggregate": False,
            "items": [
                {
                    "trade_date": "20260514",
                    "channel": "X",
                    "source_name": "memory_research",
                    "content": "HBM supply remains tight as AI accelerator demand expands.",
                    "url": "https://example.test/llm",
                    "theme": "存储芯片",
                    "ts_code": "300475.SZ",
                    "stock_name": "香农芯创",
                    "heat_score": 80,
                    "credibility_score": 72,
                }
            ],
        },
    )
    assert imported.status_code == 201

    def fake_llm(prompt: str, provider: str, model: str, temperature: float = 0.1):
        assert provider == "deepseek"
        assert model == "deepseek-v4-flash"
        assert "HBM supply remains tight" in prompt
        return """
        {
          "is_relevant": true,
          "quality_score": 82,
          "theme": "存储芯片",
          "ts_code": "300475.SZ",
          "entities": [{"type": "product", "name": "HBM", "confidence": 80}],
          "evidence": [
            {"text": "HBM supply remains tight，确定买入", "stance": "support", "confidence": 78}
          ],
          "risk_flags": ["weak_mapping"]
        }
        """

    monkeypatch.setattr("app.services.message_evidence_service.call_llm_model", fake_llm)

    resp = client.post(
        "/api/message-agents/run",
        json={
            "agent_name": "llm_evidence_cleaner",
            "trade_date": "20260514",
            "provider": "deepseek",
            "model": "deepseek-v4-flash",
        },
    )

    assert resp.status_code == 201
    body = resp.json()
    assert body["created_count"] == 1
    assert body["fallback_count"] == 0
    assert body["run"]["model_provider"] == "deepseek"
    assert body["run"]["model_name"] == "deepseek-v4-flash"

    evidence = client.get("/api/messages/evidence?trade_date=20260514&ts_code=300475.SZ").json()
    assert len(evidence) == 1
    assert evidence[0]["extractor_name"] == "llm_evidence_cleaner"
    assert "确定买入" not in evidence[0]["evidence_text"]
    assert "待验证" in evidence[0]["evidence_text"]
    assert evidence[0]["raw_json"]["risk_flags"] == ["weak_mapping"]


def test_llm_evidence_cleaner_falls_back_to_rules_on_bad_json(monkeypatch):
    client = _client()

    imported = client.post(
        "/api/messages/source-items/import",
        json={
            "aggregate": False,
            "items": [
                {
                    "trade_date": "20260514",
                    "channel": "X",
                    "content": "CPO optical module demand expands with AI capex.",
                    "theme": "CPO",
                    "ts_code": "300502.SZ",
                    "stock_name": "新易盛",
                    "heat_score": 78,
                    "credibility_score": 70,
                }
            ],
        },
    )
    assert imported.status_code == 201

    def fake_llm(_prompt: str, provider: str, model: str, temperature: float = 0.1):
        return "not json"

    monkeypatch.setattr("app.services.message_evidence_service.call_llm_model", fake_llm)

    resp = client.post(
        "/api/message-agents/run",
        json={
            "agent_name": "llm_evidence_cleaner",
            "trade_date": "20260514",
            "provider": "deepseek",
            "model": "deepseek-v4-flash",
        },
    )

    assert resp.status_code == 201
    body = resp.json()
    assert body["fallback_count"] == 1
    assert body["error_count"] == 1
    assert body["run"]["status"] == "success_with_fallback"

    evidence = client.get("/api/messages/evidence?trade_date=20260514&ts_code=300502.SZ").json()
    assert len(evidence) == 1
    assert evidence[0]["extractor_name"] == "rule_evidence_cleaner"


def test_agent_daily_report_from_evidence():
    client = _client()
    imported = client.post(
        "/api/messages/source-items/import",
        json={
            "aggregate": True,
            "items": [
                {
                    "trade_date": "20260514",
                    "channel": "雪球",
                    "title": "CPO 光模块热度提升",
                    "content": "CPO 光模块方向被反复提及，新易盛关注度提升。",
                    "url": "https://example.test/report",
                    "theme": "CPO",
                    "ts_code": "300502.SZ",
                    "stock_name": "新易盛",
                    "heat_score": 78,
                    "credibility_score": 70,
                }
            ],
        },
    )
    assert imported.status_code == 201

    resp = client.get("/api/messages/agent-daily?trade_date=20260514")
    assert resp.status_code == 200
    body = resp.json()
    assert body["model_provider"] == "rules"
    assert body["evidence_coverage"]["evidence_count"] == 1
    assert body["evidence_coverage"]["candidate_count"] == 1
    assert body["candidates"][0]["ts_code"] == "300502.SZ"
    assert "待验证" in " ".join(body["risk_flags"])


def test_agent_daily_report_can_use_deepseek_and_sanitize(monkeypatch):
    client = _client()
    imported = client.post(
        "/api/messages/source-items/import",
        json={
            "aggregate": True,
            "items": [
                {
                    "trade_date": "20260514",
                    "channel": "X",
                    "content": "HBM supply remains tight as AI accelerator demand expands.",
                    "theme": "存储芯片",
                    "ts_code": "300475.SZ",
                    "stock_name": "香农芯创",
                    "heat_score": 80,
                    "credibility_score": 72,
                }
            ],
        },
    )
    assert imported.status_code == 201

    def fake_llm(prompt: str, provider: str, model: str, temperature: float = 0.1):
        assert provider == "deepseek"
        assert model == "deepseek-v4-flash"
        assert "candidate_count" in prompt
        return """
        {
          "headline": "今日主线：存储芯片",
          "summary": "确定买入，稳赚",
          "risk_flags": ["无风险"],
          "next_actions": ["加入观察池等待买点雷达确认"]
        }
        """

    monkeypatch.setattr("app.services.message_evidence_service.call_llm_model", fake_llm)
    resp = client.post(
        "/api/messages/agent-daily/generate",
        json={
            "trade_date": "20260514",
            "use_llm": True,
            "provider": "deepseek",
            "model": "deepseek-v4-flash",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    text = str(body)
    assert body["model_provider"] == "deepseek"
    assert "确定买入" not in text
    assert "稳赚" not in text
    assert "无风险" not in text


def test_x_seed_summary_exposes_keyword_and_account_pool():
    client = _client()

    resp = client.get("/api/messages/x/seeds")

    assert resp.status_code == 200
    body = resp.json()
    assert body["keyword_count"] >= 60
    assert body["account_count"] >= 20
    assert "AI算力" in body["top_themes"]
    assert any(item["keyword"] == "HBM" for item in body["keywords"])
    assert any(item["handle"] == "SemiAnalysis_" for item in body["accounts"])


def test_import_default_keywords_persists_seed_pool():
    client = _client()

    imported = client.post("/api/messages/keywords/import-default")

    assert imported.status_code == 201
    body = imported.json()
    assert body["created_count"] >= 60
    assert body["updated_count"] == 0
    assert any(item["keyword"] == "AI capex" for item in body["items"])

    rows = client.get("/api/messages/keywords").json()
    assert len(rows) <= body["created_count"]
    assert any(item["keyword"] == "HBM" and item["theme"] == "存储芯片" for item in rows)


def test_import_keywords_upserts_and_x_seeds_prefer_db_pool():
    client = _client()

    first = client.post(
        "/api/messages/keywords/import",
        json={
            "items": [
                {
                    "keyword": "AI wafer scale",
                    "type": "industry",
                    "theme": "AI芯片",
                    "priority": 5,
                    "language": "en",
                }
            ]
        },
    )
    second = client.post(
        "/api/messages/keywords/import",
        json={
            "items": [
                {
                    "keyword": "AI wafer scale",
                    "type": "industry",
                    "theme": "AI芯片",
                    "priority": 4,
                    "language": "en",
                }
            ]
        },
    )

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["created_count"] == 1
    assert second.json()["updated_count"] == 1

    seeds = client.get("/api/messages/x/seeds").json()
    assert seeds["keyword_count"] == 1
    assert seeds["keywords"][0]["keyword"] == "AI wafer scale"
    assert seeds["keywords"][0]["priority"] == 4


def test_save_single_keyword_persists_to_keyword_pool():
    client = _client()

    resp = client.post(
        "/api/messages/keywords",
        json={
            "keyword": "Micron",
            "type": "company",
            "theme": "存储芯片",
            "priority": 5,
            "language": "en",
        },
    )

    assert resp.status_code == 201
    body = resp.json()
    assert body["keyword"] == "Micron"
    assert body["type"] == "company"

    rows = client.get("/api/messages/keywords").json()
    assert len(rows) == 1
    assert rows[0]["keyword"] == "Micron"
    assert rows[0]["theme"] == "存储芯片"


def test_single_keyword_save_rejects_duplicate_keyword_text():
    client = _client()
    payload = {
        "keyword": "Micron",
        "type": "company",
        "theme": "存储芯片",
        "priority": 5,
        "language": "en",
    }

    first = client.post("/api/messages/keywords", json=payload)
    second = client.post(
        "/api/messages/keywords",
        json={**payload, "type": "industry", "theme": "AI算力", "priority": 3},
    )

    assert first.status_code == 201
    assert second.status_code == 400
    assert second.json()["message"] == "关键词已存在"


def test_keyword_list_active_first_and_deduped_by_keyword_text():
    client = _client()

    resp = client.post(
        "/api/messages/keywords/import",
        json={
            "items": [
                {
                    "keyword": "Micron",
                    "type": "company",
                    "theme": "存储芯片",
                    "priority": 3,
                    "language": "en",
                    "status": "disabled",
                },
                {
                    "keyword": "Micron",
                    "type": "industry",
                    "theme": "AI算力",
                    "priority": 5,
                    "language": "en",
                    "status": "active",
                },
                {
                    "keyword": "HBM",
                    "type": "industry",
                    "theme": "存储芯片",
                    "priority": 4,
                    "language": "en",
                    "status": "disabled",
                },
            ]
        },
    )

    assert resp.status_code == 201
    rows = client.get("/api/messages/keywords").json()
    assert [row["keyword"] for row in rows] == ["Micron", "HBM"]
    assert rows[0]["status"] == "active"
    assert rows[0]["theme"] == "AI算力"


def test_disabled_db_keywords_do_not_fallback_to_csv_pool():
    client = _client()

    resp = client.post(
        "/api/messages/keywords/import",
        json={
            "items": [
                {
                    "keyword": "Dormant keyword",
                    "type": "industry",
                    "theme": "测试题材",
                    "priority": 5,
                    "language": "en",
                    "status": "disabled",
                }
            ]
        },
    )

    assert resp.status_code == 201
    seeds = client.get("/api/messages/x/seeds").json()

    assert seeds["keyword_count"] == 0
    assert seeds["keywords"] == []


def test_build_x_recent_search_query_uses_priority_seed_terms():
    query = build_x_recent_search_query(min_priority=5, keyword_limit=4)

    assert "-is:retweet" in query
    assert "-is:reply" in query
    assert "AI capex" in query or '"AI capex"' in query
    assert " OR " in query


def test_x_payload_to_source_items_maps_posts_to_message_sources():
    payload = {
        "data": [
            {
                "id": "123",
                "author_id": "u1",
                "created_at": "2026-05-16T01:30:00Z",
                "text": "HBM demand and Memory pricing remain strong for accelerator supply chains.",
                "public_metrics": {
                    "like_count": 120,
                    "retweet_count": 12,
                    "reply_count": 5,
                    "quote_count": 3,
                },
            },
            {
                "id": "124",
                "author_id": "u2",
                "created_at": "2026-05-16T02:30:00Z",
                "text": "Unrelated market comment.",
                "public_metrics": {},
            },
        ],
        "includes": {
            "users": [
                {"id": "u1", "username": "memory_watch"},
                {"id": "u2", "username": "other"},
            ]
        },
    }

    items = x_payload_to_source_items(payload, "20260516")

    assert len(items) == 1
    item = items[0]
    assert item.channel == "X"
    assert item.source_name == "memory_watch"
    assert item.external_id == "123"
    assert item.theme == "存储芯片"
    assert item.ts_code == "300475.SZ"
    assert item.stock_name == "香农芯创"
    assert item.url == "https://x.com/memory_watch/status/123"
    assert item.heat_score >= 80
    assert any(tag.startswith("quality:") for tag in item.tags)


def test_x_payload_to_source_items_filters_low_quality_spam():
    payload = {
        "data": [
            {
                "id": "spam-1",
                "author_id": "u1",
                "created_at": "2026-05-16T01:30:00Z",
                "text": "Best trading decision this year. Steady, consistent profits. #HBM #OKLO $FTNT $AI https://t.co/a https://t.co/b",
                "public_metrics": {
                    "like_count": 0,
                    "retweet_count": 5,
                    "reply_count": 0,
                    "quote_count": 0,
                },
            },
            {
                "id": "real-1",
                "author_id": "u2",
                "created_at": "2026-05-16T02:30:00Z",
                "text": "HBM supply remains tight as AI accelerator demand expands, with packaging capacity and DRAM stack yields still central to the memory cycle.",
                "public_metrics": {
                    "like_count": 18,
                    "retweet_count": 2,
                    "reply_count": 1,
                    "quote_count": 0,
                },
            },
        ],
        "includes": {
            "users": [
                {"id": "u1", "username": "signal_spam"},
                {"id": "u2", "username": "memory_research"},
            ]
        },
    }

    items = x_payload_to_source_items(payload, "20260516")

    assert len(items) == 1
    assert items[0].external_id == "real-1"
    assert items[0].source_name == "memory_research"


def test_keyword_import_collect_and_conclusion_closed_loop(monkeypatch):
    client = _client()

    keyword_resp = client.post(
        "/api/messages/keywords/import",
        json={
            "items": [
                {
                    "keyword": "HBM",
                    "type": "industry",
                    "theme": "存储芯片",
                    "priority": 5,
                    "language": "en",
                }
            ]
        },
    )

    assert keyword_resp.status_code == 201

    def fake_fetch(query: str, max_results: int):
        assert "HBM" in query
        return {
            "data": [
                {
                    "id": "closed-loop-1",
                    "author_id": "u1",
                    "created_at": "2026-05-18T01:30:00Z",
                    "text": "HBM supply remains tight as AI accelerator demand expands, with packaging capacity and DRAM yields driving the memory cycle.",
                    "public_metrics": {
                        "like_count": 80,
                        "retweet_count": 12,
                        "reply_count": 4,
                        "quote_count": 2,
                    },
                }
            ],
            "includes": {"users": [{"id": "u1", "username": "memory_research"}]},
        }

    monkeypatch.setattr(x_message_service, "_fetch_x_recent_search", fake_fetch)

    collect_resp = client.post(
        "/api/messages/x/collect",
        json={
            "trade_date": "20260518",
            "max_results": 10,
            "aggregate": True,
        },
    )

    assert collect_resp.status_code == 201
    collected = collect_resp.json()
    assert collected["raw_count"] == 1
    assert collected["imported"]["created_count"] == 1
    assert collected["imported"]["aggregation"]["topic_count"] == 1
    assert collected["imported"]["aggregation"]["opportunity_count"] == 1

    conclusion_resp = client.get("/api/messages/daily-conclusion?trade_date=20260518&ensure_seed=false")

    assert conclusion_resp.status_code == 200
    conclusion = conclusion_resp.json()
    assert "存储芯片" in conclusion["headline"]
    assert conclusion["top_topics"][0]["theme"] == "存储芯片"
    assert conclusion["top_opportunities"][0]["ts_code"] == "300475.SZ"
    assert conclusion["top_opportunities"][0]["stock_name"] == "香农芯创"
    assert "买点" in conclusion["next_action"] or "风险观察" in conclusion["next_action"]
