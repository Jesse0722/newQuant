from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.database import Base
from app.models.message import MessageAgentRun, MessageEvidence, MessageSourceItem, MessageOpportunity, IndustryDailyReport, MessageEntity, MessageRelation, MessageRelationEvidence
from app.models.stock import StockBasic, StockAiAnalysis
from app.services import message_evidence_service as evidence_service
from app.services import message_extraction_service as extraction_service
from app.services import ai_analysis_service as ai_service
from app.services import message_pipeline_service as pipeline_service
from app.services.industry_report_service import _build_candidate_rows, generate_industry_report
from app.services.message_graph_service import import_seed_graph, upsert_entity, upsert_relation, find_paths
from app.services.message_mapping_service import mapping_candidates, run_entity_mapping_agent
from app.services.message_service import aggregate_source_items
from app.services.message_source_policy import source_policy


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as session:
        yield session
    engine.dispose()


def source(db, ident="first", **kwargs):
    data = {"id": ident, "trade_date": "20261111", "channel": "news", "theme": "AI算力",
            "ts_code": "601138.SH", "content": "公司发布产品与订单进度。", "dedupe_key": ident,
            "heat_score": 80, "credibility_score": 80}
    data.update(kwargs)
    row = MessageSourceItem(**data)
    db.add(row)
    db.commit()
    return row


def llm_quote(text="公司发布产品与订单进度", **kwargs):
    data = {"is_relevant": True, "quality_score": 80,
            "evidence": [{"text": text, "stance": "support", "confidence": 80}]}
    data.update(kwargs)
    return json.dumps(data, ensure_ascii=False)


def test_batch_failure_keeps_prior_success_and_raw_failure(db, monkeypatch):
    for ident, heat in [("first", 90), ("second", 80), ("third", 70)]:
        source(db, ident, heat_score=heat)
    responses = iter([llm_quote(), "invalid json", llm_quote()])
    monkeypatch.setattr(evidence_service, "call_llm_model", lambda *a, **k: next(responses))
    result = evidence_service.run_llm_evidence_cleaner(db, trade_date="20261111")
    assert result.created_count == result.evidence_count == db.query(MessageEvidence).count() == 3
    assert result.fallback_count == 1
    assert {row.source_item_id for row in db.query(MessageEvidence)} == {"first", "second", "third"}
    failure = db.query(MessageAgentRun).filter_by(status="failed").one()
    assert failure.output_json["raw_response"] == "invalid json"
    assert failure.output_json["input_snapshot"]["id"] == "second"
    assert db.query(MessageAgentRun).filter_by(input_ref_id="first", status="success").count() == 1


def test_cleaner_reuses_input_digest_and_retires_stale_stance(db, monkeypatch):
    item = source(db)
    calls = []
    def model(*a, **k):
        calls.append(1)
        return llm_quote()
    monkeypatch.setattr(evidence_service, "call_llm_model", model)
    evidence_service.run_llm_evidence_cleaner(db, trade_date="20261111")
    repeat = evidence_service.run_llm_evidence_cleaner(db, trade_date="20261111")
    assert len(calls) == 1 and repeat.skipped_count == 1
    monkeypatch.setattr(evidence_service, "call_llm_model", lambda *a, **k: json.dumps({"is_relevant": False, "evidence": []}))
    evidence_service.run_llm_evidence_cleaner(db, trade_date="20261111", force=True)
    assert db.query(MessageEvidence).filter_by(status="active", source_item_id=item.id).count() == 0


def test_irrelevant_cleaner_verdict_cannot_be_revived_by_rule_projection(db, monkeypatch):
    item = source(db)
    aggregate_source_items(db, "20261111")
    monkeypatch.setattr(evidence_service, "call_llm_model", lambda *a, **k: json.dumps({"is_relevant": False, "evidence": []}))
    evidence_service.run_llm_evidence_cleaner(db, source_item_ids=[item.id])
    aggregate_source_items(db, "20261111")
    assert db.query(MessageEvidence).filter_by(source_item_id=item.id, status="active").count() == 0
    assert db.query(MessageOpportunity).one().status == "inactive"
    # A source edit invalidates the old verdict, allowing a new review.
    item.content = "公司发布新的产品公告，前次spam判断不再适用。"
    db.commit()
    aggregate_source_items(db, "20261111")
    assert db.query(MessageOpportunity).one().status == "active"


def test_entity_mapping_cannot_invalidate_spam_verdict_for_unchanged_text(db, monkeypatch):
    item = source(db, content="HBM giveaway join my discord for guaranteed profit.", ts_code=None, theme="存储芯片")
    monkeypatch.setattr(evidence_service, "call_llm_model", lambda *a, **k: json.dumps({"is_relevant": False, "evidence": []}))
    evidence_service.run_llm_evidence_cleaner(db, source_item_ids=[item.id])
    run_entity_mapping_agent(db, source_item_ids=[item.id])
    assert item.ts_code == "300475.SZ"
    aggregate_source_items(db, "20261111")
    assert db.query(MessageEvidence).filter_by(status="active").count() == 0
    assert db.query(MessageOpportunity).count() == 0


def test_stock_ai_excludes_demo_dismissed_ignored_and_dates_outside_window(db):
    source(db, "ignored", status="ignored")
    source(db, "before", trade_date="20260926")
    source(db, "boundary", trade_date="20260927")
    source(db, "future", trade_date="20261112")
    for ident, status, review in [("demo", "demo", "reviewed"), ("dismissed", "dismissed", "dismissed"), ("hidden_review", "active", "dismissed")]:
        db.add(MessageOpportunity(id=ident, trade_date="20261111", theme="AI算力", ts_code="601138.SH",
                                  reason="演示百亿订单", status=status, review_status=review))
    db.commit()
    news = ai_service._query_messages(db, "601138.SH", as_of=datetime(2026, 11, 11))
    assert len(news["items"]) == 1
    assert news["items"][0]["trade_date"] == "20260927"
    assert news["items"][0]["type"] == "source"


def test_official_contradiction_downgrades_industry_and_message_candidates(db):
    import_seed_graph(db)
    source(db, "positive", channel="announcement", sentiment="positive")
    aggregate_source_items(db, "20261111")
    before = next(row for row in _build_candidate_rows(db, "20261111") if row["ts_code"] == "601138.SH")
    source(db, "refutation", channel="exchange", content="公司公告否认新增订单。", credibility_score=100)
    aggregate_source_items(db, "20261111")
    after = next(row for row in _build_candidate_rows(db, "20261111") if row["ts_code"] == "601138.SH")
    assert after["grade"] == "risk_watch"
    assert after["risk_score"] >= 85 and after["final_score"] < before["final_score"]
    opp = db.query(MessageOpportunity).one()
    assert opp.risk_score >= 85 and opp.action_suggestion == "risk_watch"
    assert any(row.get("stance") == "contradiction" and row.get("url") is None for row in after["evidence_json"])


def test_seed_only_and_multi_social_never_become_strong(db):
    import_seed_graph(db)
    assert all(row["grade"] == "weak" for row in _build_candidate_rows(db, "20261111"))
    source(db, "x", channel="X", heat_score=100, credibility_score=100)
    source(db, "snow", channel="雪球", heat_score=100, credibility_score=100)
    aggregate_source_items(db, "20261111")
    candidate = next(row for row in _build_candidate_rows(db, "20261111") if row["ts_code"] == "601138.SH")
    assert candidate["grade"] == "weak" and candidate["final_score"] <= 59
    assert any("社媒" in risk for risk in candidate["risks"])
    assert db.query(MessageOpportunity).one().action_suggestion == "watch"


def test_human_review_fields_and_terminal_decisions_survive_reaggregation(db):
    item = source(db)
    aggregate_source_items(db, "20261111")
    opp = db.query(MessageOpportunity).one()
    opp.review_reason = "人工记录：客户认证待公告"
    opp.review_status = "needs_review"
    db.commit()
    score = opp.opportunity_score
    item.heat_score = 10
    db.commit()
    aggregate_source_items(db, "20261111")
    assert opp.opportunity_score != score
    assert opp.review_status == "needs_review" and opp.review_reason == "人工记录：客户认证待公告"
    for terminal in ["accepted", "dismissed"]:
        opp.review_status = terminal
        db.commit()
        frozen = (opp.reason, opp.opportunity_score, opp.review_reason)
        item.heat_score = 95
        db.commit()
        aggregate_source_items(db, "20261111")
        assert (opp.reason, opp.opportunity_score, opp.review_reason) == frozen


CASES = json.loads((Path(__file__).parent / "fixtures/message_agent_cases/cases.json").read_text())["cases"]


@pytest.mark.parametrize("case", CASES, ids=[case["name"] for case in CASES])
def test_offline_message_agent_corpus(db, monkeypatch, case):
    item = source(db, content=case["content"], theme=case.get("theme"), ts_code=case.get("ts_code"),
                  channel=case.get("channel", "news"))
    raw = case.get("raw", json.dumps(case.get("output"), ensure_ascii=False))
    monkeypatch.setattr(evidence_service, "call_llm_model", lambda *a, **k: raw)
    result = evidence_service.run_llm_evidence_cleaner(db, source_item_ids=[item.id])
    assert (result.fallback_count == 0) is case["accepted"]
    for row in db.query(MessageEvidence).filter_by(extraction_method="llm", status="active"):
        assert row.evidence_text in item.content or row.evidence_text in (item.title or "")
        assert row.raw_json["text_kind"] == "quote"
    audit = db.query(MessageAgentRun).filter_by(input_ref_id=item.id, input_ref_type="source_item").one()
    assert audit.output_json["raw_response"] == raw
    assert audit.input_digest


def test_offline_quality_metrics(db):
    """Run with -s to record deterministic corpus metrics (not live-model accuracy)."""
    parsed = 0
    correct_decisions = 0
    anchored = 0
    accepted_quotes = 0
    false_mappings = 0
    for index, case in enumerate(CASES):
        item = source(db, str(index), content=case["content"], theme=case.get("theme"), ts_code=case.get("ts_code"))
        raw = case.get("raw", json.dumps(case.get("output"), ensure_ascii=False))
        accepted = False
        try:
            output = evidence_service._json_from_llm_text(raw)
            parsed += 1
            checked = evidence_service._sanitize_llm_evidence_data(output, item, db)
            accepted = True
            for quote in checked["evidence"]:
                accepted_quotes += 1
                anchored += quote["text"] in item.content
            if case["name"] == "fabricated_stock":
                false_mappings += 1
        except (ValueError, TypeError):
            pass
        correct_decisions += accepted == case["accepted"]
    metrics = {"corpus_version": "1.0", "case_count": len(CASES), "json_parse_rate": parsed / len(CASES),
               "decision_accuracy": correct_decisions / len(CASES),
               "accepted_quote_accuracy": anchored / accepted_quotes, "false_mapping_count": false_mappings,
               "live_model_called": False}
    print(json.dumps(metrics, sort_keys=True))
    assert metrics["decision_accuracy"] == metrics["accepted_quote_accuracy"] == 1
    assert metrics["false_mapping_count"] == 0 and parsed == 11


def test_entity_mapping_reuses_seeds_and_exposes_weak_paths(db):
    item = source(db, content="HBM supply remains tight.", ts_code=None, theme=None)
    result = run_entity_mapping_agent(db, source_item_ids=[item.id])
    output = result.run.output_json["mappings"][0]
    assert output["candidates"][0]["matched_terms"] == ["HBM"]
    assert "seed_business_mapping" in output["candidates"][0]["mapping_path"]
    assert output["review_status"] == "needs_review"
    assert item.ts_code == "300475.SZ"
    aggregate_source_items(db, "20261111")
    assert db.query(MessageOpportunity).one().review_status == "needs_review"
    demand = source(db, "demand", content="demand has changed", ts_code=None, theme=None)
    assert mapping_candidates(db, demand) == []  # MU must not match demand.


def test_direct_company_mapping_uses_master_and_retains_review_ambiguity(db):
    db.add_all([StockBasic(ts_code="601138.SH", name="工业富联"), StockBasic(ts_code="300308.SZ", name="中际旭创")])
    db.commit()
    item = source(db, content="工业富联发布产品。", ts_code=None)
    result = mapping_candidates(db, item)
    assert result[0]["strength"] == "strong" and result[0]["review_status"] == "reviewed"
    item.content = "工业富联与中际旭创发布产品。"
    assert all(row["review_status"] == "needs_review" for row in mapping_candidates(db, item))


def graph_output():
    return json.dumps({"entities": [{"name": "Rubin", "entity_type": "product", "confidence": 80},
                                    {"name": "NVLink", "entity_type": "technology", "confidence": 80}],
                       "relations": [{"source": "Rubin", "target": "NVLink", "relation_type": "uses",
                                      "confidence": 80, "evidence_text": "Rubin uses NVLink"}]})


def test_graph_extraction_digest_skips_processed_and_advances_batch(db, monkeypatch):
    source(db, "first", content="Rubin uses NVLink.", heat_score=90)
    source(db, "second", content="Rubin uses NVLink.", heat_score=80)
    calls = []
    def model(*args, **kwargs):
        calls.append(1)
        return graph_output()
    monkeypatch.setattr(extraction_service, "call_llm_model", model)
    assert extraction_service.extract_source_items_for_date(db, trade_date="20261111", limit=1).processed_count == 1
    second = extraction_service.extract_source_items_for_date(db, trade_date="20261111", limit=1)
    assert second.processed_count == 1 and second.skipped_count == 1
    third = extraction_service.extract_source_items_for_date(db, trade_date="20261111", limit=1)
    assert third.processed_count == 0 and third.skipped_count == 2 and len(calls) == 2
    assert db.query(MessageAgentRun).filter_by(agent_name=extraction_service.EXTRACTION_AGENT).count() == 2


def test_unanchored_graph_relation_fails_without_partial_graph_and_keeps_raw(db, monkeypatch):
    item = source(db, content="Only development progress disclosed.")
    monkeypatch.setattr(extraction_service, "call_llm_model", lambda *a, **k: graph_output())
    result = extraction_service.extract_source_items_for_date(db, trade_date="20261111")
    assert result.error_count == 1 and db.query(MessageEntity).count() == 0 and db.query(MessageRelation).count() == 0
    run = db.query(MessageAgentRun).one()
    assert run.status == "failed" and run.output_json["raw_response"] == graph_output()
    assert run.input_ref_id == item.id


def test_paid_cleaner_advances_past_cached_sources_and_caps_automatic_retries(db, monkeypatch):
    source(db, "first", heat_score=90)
    source(db, "second", heat_score=80)
    calls = []
    def model(*a, **k):
        calls.append(1)
        return llm_quote()
    monkeypatch.setattr(evidence_service, "call_llm_model", model)
    evidence_service.run_llm_evidence_cleaner(db, trade_date="20261111", limit=1)
    result = evidence_service.run_llm_evidence_cleaner(db, trade_date="20261111", limit=1)
    assert result.source_item_count == 1 and result.skipped_count == 1 and len(calls) == 2
    assert db.query(MessageEvidence).filter_by(extraction_method="llm", status="active").count() == 2
    failing = source(db, "failure", content="Rubin uses NVLink.", heat_score=100)
    bad_calls = []
    def broken(*a, **k):
        bad_calls.append(1)
        return "{broken"
    monkeypatch.setattr(evidence_service, "call_llm_model", broken)
    for _ in range(4):
        evidence_service.run_llm_evidence_cleaner(db, source_item_ids=[failing.id])
    assert len(bad_calls) == 3
    evidence_service.run_llm_evidence_cleaner(db, source_item_ids=[failing.id], force=True)
    assert len(bad_calls) == 4
    monkeypatch.setattr(extraction_service, "call_llm_model", broken)
    for _ in range(4):
        extraction_service.extract_source_items_for_date(db, trade_date="20261111", limit=1)
    # First source reaches its retry cap, then the batch advances to the next.
    failed_runs = db.query(MessageAgentRun).filter_by(agent_name=extraction_service.EXTRACTION_AGENT, input_ref_id=failing.id).count()
    assert failed_runs == 3


def test_mentions_paths_are_weak_and_show_actual_provenance(db):
    a = upsert_entity(db, name="A")
    b = upsert_entity(db, name="B")
    relation = upsert_relation(db, source=a, target=b, relation_type="mentions", confidence=99,
                               source_type="seed", evidence_text="A and B are mentioned together")
    db.commit()
    paths = find_paths(db, "A")
    assert relation.confidence == 50 and paths[0].score <= 40
    assert paths[0].steps[0].evidence[0]["evidence_text"] == "A and B are mentioned together"
    assert paths[0].steps[0].relation_id == relation.id


def test_report_regeneration_and_bad_json_keep_each_input_and_raw(db, monkeypatch):
    monkeypatch.setattr("app.services.industry_report_service.call_llm_model", lambda *a, **k: "{broken")
    first = generate_industry_report(db, trade_date="20261111", use_llm=True)
    assert first.raw_response == "{broken" and first.input_snapshot["candidates"]
    assert first.error_message and first.model_provider == "rules"
    generate_industry_report(db, trade_date="20261111", use_llm=False)
    assert db.query(IndustryDailyReport).count() == 1
    runs = db.query(MessageAgentRun).filter_by(agent_name="industry_daily_reporter").all()
    assert len(runs) == 2 and any(row.output_json.get("raw_response") == "{broken" for row in runs)


def test_stock_parse_failure_saves_raw_response(db, monkeypatch):
    monkeypatch.setattr(ai_service, "_build_snapshot", lambda *a, **k: {"market": {"latest_trade_date": "20261111"}})
    monkeypatch.setattr(ai_service, "_build_prompt", lambda *a, **k: "fixed source snapshot")
    monkeypatch.setattr(ai_service, "call_llm_model", lambda *a, **k: "{broken")
    with pytest.raises(Exception):
        ai_service.analyze_stock_detail(db, "601138.SH", force_refresh=True)
    row = db.query(StockAiAnalysis).one()
    assert row.status == "failed" and row.raw_response == "{broken"


def test_pipeline_disabled_is_noop_and_rules_mode_never_calls_llm(db, monkeypatch):
    for key in ["MESSAGE_PIPELINE_ENABLED", "MESSAGE_PIPELINE_COLLECT_ENABLED", "MESSAGE_PIPELINE_LLM_ENABLED"]:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(evidence_service, "call_llm_model", lambda *a, **k: pytest.fail("unexpected paid call"))
    assert pipeline_service.run_message_pipeline(db)["status"] == "disabled"
    assert db.query(MessageAgentRun).count() == 0
    source(db)
    result = pipeline_service.run_message_pipeline(db, enabled=True, trade_date="20261111")
    assert result["status"] == "success" and result["stages"]["collect"]["status"] == "disabled"
    assert result["stages"]["industry_report"]["status"] == "success"


def test_pipeline_collector_failure_isolated_and_dependency_failure_skips_reports(db, monkeypatch):
    source(db)
    def fail(*args, **kwargs):
        raise RuntimeError("temporary source outage")
    monkeypatch.setattr("app.services.x_message_service.collect_x_recent_posts", fail)
    result = pipeline_service.run_message_pipeline(db, enabled=True, collect_enabled=True, use_llm=False, trade_date="20261111")
    assert result["stages"]["collect"]["status"] == "failed"
    assert result["stages"]["industry_report"]["status"] == "success"
    monkeypatch.setattr(pipeline_service, "run_entity_mapping_agent", fail)
    result = pipeline_service.run_message_pipeline(db, enabled=True, collect_enabled=False, use_llm=False, trade_date="20261111")
    assert result["stages"]["map"]["status"] == "failed"
    assert result["stages"]["score"]["status"] == result["stages"]["industry_report"]["status"] == "skipped"


def test_pipeline_fallbacks_are_visible_without_discarding_rule_results(db, monkeypatch):
    source(db)
    monkeypatch.setattr(evidence_service, "call_llm_model", lambda *a, **k: "{broken")
    monkeypatch.setattr("app.services.industry_report_service.call_llm_model", lambda *a, **k: "{broken")
    result = pipeline_service.run_message_pipeline(db, enabled=True, collect_enabled=False, use_llm=True, trade_date="20261111")
    assert result["status"] == "success_with_errors" and result["error_count"] == 3
    assert result["stages"]["clean"]["status"] == "success_with_fallback"
    assert result["stages"]["agent_report"]["status"] == "success_with_fallback"
    assert result["stages"]["industry_report"]["status"] == "success_with_fallback"
    assert db.query(MessageEvidence).filter_by(status="active").count() == 1
    assert db.query(IndustryDailyReport).one().model_provider == "rules"


def terminal_mapping(db, trade_date="20261110"):
    import_seed_graph(db)
    candidate = _build_candidate_rows(db, trade_date)[0]
    return candidate, db.get(MessageRelation, candidate["path_json"][-1]["relation_id"])


def find_candidate(rows, baseline):
    return next((row for row in rows if (row["ts_code"], row["theme"]) == (baseline["ts_code"], baseline["theme"])), None)


def test_terminal_mapping_clips_future_evidence_and_relation_validity(db):
    baseline, relation = terminal_mapping(db)
    future = source(db, "future-source", trade_date="20261112", channel="official",
                    ts_code=baseline["ts_code"], theme=baseline["theme"],
                    content="Future company business fact only published on November 12")
    db.add(MessageRelationEvidence(relation_id=relation.id, source_item_id=future.id,
                                  evidence_text=future.content, source_channel="official",
                                  extraction_method="llm", confidence=100))
    # A future extraction must not raise the historical mapping's confidence.
    relation.confidence = 100
    db.commit()
    candidate = find_candidate(_build_candidate_rows(db, "20261110"), baseline)
    assert candidate is not None  # Static seed mappings survive today's import.
    assert all(row.get("source_item_id") != future.id for row in candidate["evidence_json"])
    assert all(row.get("source_item_id") != future.id for row in candidate["path_json"][-1]["evidence"])
    assert candidate["path_json"][-1]["confidence"] == baseline["path_json"][-1]["confidence"]
    assert candidate["grade"] == "weak" and any("种子" in risk for risk in candidate["risks"])
    relation.valid_from = "20261112"
    db.commit()
    assert find_candidate(_build_candidate_rows(db, "20261110"), baseline) is None
    relation.valid_from, relation.valid_to = "20261101", "20261109"
    db.commit()
    assert find_candidate(_build_candidate_rows(db, "20261110"), baseline) is None
    relation.valid_to = "20261110"
    db.commit()
    assert find_candidate(_build_candidate_rows(db, "20261110"), baseline) is not None


def test_terminal_mapping_requires_active_anchored_source_available_by_publication_day(db):
    baseline, relation = terminal_mapping(db)
    db.query(MessageRelationEvidence).filter_by(relation_id=relation.id).delete()
    item = source(db, "terminal-source", trade_date="20261112", channel="official",
                  ts_code=baseline["ts_code"], theme=baseline["theme"], content="Company maps to the business.")
    db.add(MessageRelationEvidence(relation_id=relation.id, source_item_id=item.id,
                                  evidence_text=item.content, source_channel="official", extraction_method="llm", confidence=80))
    db.commit()
    assert find_candidate(_build_candidate_rows(db, "20261110"), baseline) is None
    item.trade_date = "20261110"
    item.published_at = datetime(2026, 11, 10, 16, 0)  # UTC -> next Shanghai day.
    db.commit()
    assert find_candidate(_build_candidate_rows(db, "20261110"), baseline) is None
    item.published_at = datetime(2026, 11, 10, 15, 59)
    db.commit()
    assert find_candidate(_build_candidate_rows(db, "20261110"), baseline) is not None
    item.status = "ignored"
    db.commit()
    assert find_candidate(_build_candidate_rows(db, "20261110"), baseline) is None
    item.status, item.content = "processed", "The original quotation was removed."
    db.commit()
    assert find_candidate(_build_candidate_rows(db, "20261110"), baseline) is None


@pytest.mark.parametrize("reverse", [False, True])
def test_same_url_repost_preserves_official_refutation_and_one_source(reverse):
    rows = [{"url": "https://exchange.example/notice/1", "channel": "official", "stance": "contradiction", "confidence": 80},
            {"url": "https://exchange.example/notice/1", "channel": "X", "stance": "contradiction", "confidence": 95}]
    policy = source_policy(list(reversed(rows)) if reverse else rows)
    assert policy["official_contradiction"] and not policy["social_only"]
    assert policy["independent_sources"] == policy["contradiction_count"] == 1
    assert policy["source_groups"][0]["channels"] == ["official", "x"]
    assert policy["support_confidences"] == []


def test_repost_confidence_does_not_upgrade_original_official_evidence():
    rows = [{"url": "https://exchange.example/notice/1", "channel": "official", "stance": "support", "confidence": 80},
            {"url": "https://exchange.example/notice/1", "channel": "X", "stance": "support", "confidence": 95}]
    policy = source_policy(rows)
    assert policy["independent_sources"] == 1 and policy["support_confidences"] == [80]


def test_same_url_official_counterevidence_still_downgrades_industry_report(db):
    baseline, _ = terminal_mapping(db)
    for ident, channel, confidence in [("official", "official", 80), ("repost", "X", 95)]:
        item = source(db, ident, trade_date="20261110", channel=channel, content="公司公告否认新增订单。",
                      theme=baseline["theme"], ts_code=baseline["ts_code"], url="https://exchange.example/notice/1")
        db.add(MessageEvidence(source_item_id=item.id, trade_date=item.trade_date, channel=channel,
                               theme=item.theme, ts_code=item.ts_code, evidence_text=item.content,
                               stance="contradiction", confidence=confidence, status="active"))
    db.commit()
    candidate = find_candidate(_build_candidate_rows(db, "20261110"), baseline)
    assert candidate["grade"] == "risk_watch" and candidate["risk_score"] >= 85
    assert any("官方反证" in risk for risk in candidate["risks"])


@pytest.mark.parametrize("human_confirmed", [False, True])
def test_weak_mapping_downgrades_only_automatic_reviewed_state(db, human_confirmed):
    item = source(db, content="HBM supply remains tight and semiconductor demand is growing worldwide.",
                  channel="X", theme="存储芯片", ts_code="300475.SZ")
    aggregate_source_items(db, "20261111")
    opportunity = db.query(MessageOpportunity).one()
    assert opportunity.review_status == "reviewed" and opportunity.review_reason is None
    if human_confirmed:
        evidence_service.review_opportunity(db, opportunity.id, "reviewed")
    run_entity_mapping_agent(db, source_item_ids=[item.id])
    aggregate_source_items(db, "20261111")
    assert opportunity.review_status == ("reviewed" if human_confirmed else "needs_review")
    if human_confirmed:
        marker = db.query(MessageAgentRun).filter_by(agent_name=evidence_service.MANUAL_REVIEW_AGENT).one()
        assert marker.model_provider == "human" and marker.input_ref_id == opportunity.id


def test_legacy_manual_opportunity_keeps_review_origin_without_reason(db):
    source(db, content="HBM supply remains tight and semiconductor demand is growing worldwide.",
           channel="X", theme="存储芯片", ts_code="300475.SZ")
    opportunity = MessageOpportunity(trade_date="20261111", theme="存储芯片", ts_code="300475.SZ",
                                     generated_by="manual", review_status="reviewed")
    db.add(opportunity)
    db.commit()
    run_entity_mapping_agent(db, trade_date="20261111")
    aggregate_source_items(db, "20261111")
    aggregate_source_items(db, "20261111")
    assert opportunity.review_status == "reviewed" and opportunity.generated_by == "manual"
