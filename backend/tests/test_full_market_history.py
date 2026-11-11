from __future__ import annotations

from dataclasses import replace
from datetime import datetime
import json

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.stock import DailyQuote, StockBasic
from app.models.sync_log import SyncLog
from app.services import full_market_history_service as history
from app.services.market_data_capabilities import ProviderCapabilities
from app.services.tushare_adapter import CompositeAdapter

CAPS = ProviderCapabilities("fixture", False, True, False, ("SH", "SZ"), "share", "cny", False, True, True)
DATES = ["20261008", "20261009"]


def quote(code="000001.SZ", day=DATES[0], close=10):
    return {"ts_code": code, "trade_date": day, "open": 10, "high": 11, "low": 9,
            "close": close, "pre_close": 10, "pct_chg": 0, "vol": 1000, "amount": 20000}


class Provider:
    def __init__(self, rows=(), caps=CAPS, error=False):
        self.capabilities, self.rows, self.error, self.calls = caps, list(rows), error, []

    def get_daily(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise ConnectionError("secret-api-token")
        return pd.DataFrame([r for r in self.rows if r["ts_code"] == kwargs["ts_code"]
                             and kwargs["start_date"] <= r["trade_date"] <= kwargs["end_date"]])

    def get_daily_by_date(self, day):
        self.calls.append(day)
        if self.error:
            raise ConnectionError("secret-api-token")
        return pd.DataFrame([r for r in self.rows if r["trade_date"] == day])

    def get_sse_open_dates(self, *args, **kwargs):
        return []


@pytest.fixture
def database():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine, tables=[StockBasic.__table__, DailyQuote.__table__, SyncLog.__table__])
    session_factory = sessionmaker(bind=engine)
    with session_factory() as db:
        db.add_all([StockBasic(ts_code="000001.SZ", name="银行", list_status="L"),
                    StockBasic(ts_code="000001.SH", name="指数", list_status="L")])
        db.commit()
        yield db, session_factory
    engine.dispose()


def collect(db, provider):
    return history.collect_full_market_history(db, provider, DATES, request_interval=0)


def test_default_style_composite_uses_symbol_history_and_is_idempotent(database):
    db, _ = database
    unsupported = Provider(caps=replace(CAPS, name="snapshot", history_by_symbol=False, snapshot_by_date=True))
    source = Provider([quote(day=d) for d in DATES])
    composite = CompositeAdapter([unsupported, source])
    result = collect(db, composite)
    assert len(source.calls) == 1 and unsupported.calls == []
    assert result["days_synced"] == 2 and result["success_count"] == 2
    assert result["completed_dates"] == DATES
    assert result["market_coverage_ratio"] is None
    row = db.get(DailyQuote, ("000001.SZ", DATES[0]))
    assert row.vol == 10 and row.amount == 20
    # Do not rewrite pre-existing values, even when the provider changes them.
    source.rows = [quote(day=d, close=10.5) for d in DATES]
    result2 = collect(db, composite)
    assert result2["success_count"] == 0 and result2["skipped_count"] == 2
    assert db.get(DailyQuote, ("000001.SZ", DATES[0])).close == 10


@pytest.mark.parametrize("kind,expected", [("empty", "no_data"), ("failed", "failed"), ("unsupported", "unsupported")])
def test_empty_failed_unsupported_are_distinct(database, kind, expected):
    db, _ = database
    p = Provider(error=kind == "failed", caps=replace(CAPS, history_by_symbol=kind != "unsupported"))
    result = collect(db, p)
    assert result["outcome"] == expected and result["days_synced"] == 0
    assert "secret-api-token" not in json.dumps(result)
    assert db.query(DailyQuote).count() == 0


def test_by_date_error_cannot_be_hidden_as_unsupported(database):
    db, _ = database
    p = Provider(error=True, caps=replace(CAPS, history_by_date=True, history_by_symbol=False))
    result = collect(db, p)
    assert result["outcome"] == "failed"
    assert len(result["failed_dates"]) == 2


def test_missing_sessions_fall_back_without_overwriting_first_source(database):
    db, _ = database
    first = Provider([quote(day=DATES[0])])
    second = Provider([quote(day=DATES[1])], caps=replace(CAPS, name="second"))
    result = collect(db, CompositeAdapter([first, second]))
    assert result["outcome"] == "complete"
    assert second.calls[0]["start_date"] == DATES[1]
    assert result["date_results"][0]["inserted_sources"] == {"fixture": 1}
    assert result["date_results"][1]["inserted_sources"] == {"second": 1}


def test_existing_invalid_row_is_not_claimed_as_complete(database):
    db, _ = database
    db.add(DailyQuote(ts_code="000001.SZ", trade_date=DATES[0], close=10))
    db.commit()
    result = collect(db, Provider([quote(day=d) for d in DATES]))
    assert result["outcome"] == "partial"
    assert result["completed_dates"] == [DATES[1]]
    assert result["date_results"][0]["target_coverage_ratio"] == 0
    assert db.get(DailyQuote, ("000001.SZ", DATES[0])).pre_close is None


def test_complete_database_does_not_call_broken_upstream(database):
    db, _ = database
    for day in DATES:
        db.add(DailyQuote(**quote(day=day)))
    db.commit()
    source = Provider(error=True)
    result = collect(db, source)
    assert result["outcome"] == "complete" and result["already_satisfied"]
    assert result["days_synced"] == 2 and result["skipped_count"] == 2
    assert not source.calls and not result["provider_attempts"]


def test_first_run_can_bootstrap_master_without_non_stock_codes(database):
    db, _ = database
    db.query(StockBasic).delete()
    db.commit()
    class BootstrapProvider(Provider):
        def get_stock_basic(self):
            return pd.DataFrame([{"ts_code": "000001.SZ", "name": "银行"},
                                 {"ts_code": "000001.SH", "name": "指数"}])
    result = collect(db, BootstrapProvider([quote(day=d) for d in DATES]))
    assert result["outcome"] == "complete"
    assert result["universe_bootstrap_source"] == "fixture"
    assert db.query(StockBasic).count() == 1


def test_existing_invalid_only_is_classified_as_repair_not_unsupported(database):
    db, _ = database
    for day in DATES:
        db.add(DailyQuote(ts_code="000001.SZ", trade_date=day, close=10))
    db.commit()
    source = Provider(error=True)
    result = collect(db, source)
    assert result["outcome"] == "no_data"
    assert result["repair_required_dates"] == DATES
    assert all(d["status"] == "requires_repair" for d in result["date_results"])
    assert not result["unsupported_dates"] and not source.calls


def test_95_percent_target_coverage_can_complete_with_empty_responses(database):
    db, _ = database
    for index in range(19):
        db.add(StockBasic(ts_code=f"600{index:03d}.SH", name="测试股", list_status="L"))
    codes = ["000001.SZ"] + [f"600{index:03d}.SH" for index in range(18)]
    for day in DATES:
        db.add_all([DailyQuote(**quote(code=code, day=day)) for code in codes])
    db.commit()
    source = Provider()
    result = collect(db, source)
    assert result["outcome"] == "complete" and result["completed_dates"] == DATES
    assert result["date_results"][0]["target_coverage_ratio"] == .95
    assert result["date_results"][0]["requests"]["empty"] == 1
    assert result["has_source_warnings"] and len(source.calls) == 1


def test_bj_not_claimed_when_source_only_supports_sh_sz(database):
    db, _ = database
    db.add(StockBasic(ts_code="920001.BJ", name="北交所", list_status="L"))
    db.commit()
    p = Provider([quote(day=d) for d in DATES])
    result = collect(db, p)
    assert len(p.calls) == 1
    assert result["outcome"] == "partial"
    assert result["date_results"][0]["requests"]["unsupported"] == 1


def test_insert_failure_rolls_back_and_next_symbol_continues(database, monkeypatch):
    db, _ = database
    db.add(StockBasic(ts_code="600000.SH", name="另一银行", list_status="L"))
    db.commit()
    original = history._insert_missing
    def insert(session, rows):
        if rows[0]["ts_code"] == "000001.SZ":
            session.add(DailyQuote(**rows[0]))
            session.flush()
            session.rollback()
            raise RuntimeError("injected write failure")
        return original(session, rows)
    monkeypatch.setattr(history, "_insert_missing", insert)
    result = collect(db, Provider([quote(code=c, day=d) for c in ("000001.SZ", "600000.SH") for d in DATES]))
    assert result["outcome"] == "partial"
    assert db.query(DailyQuote).count() == 2
    assert result["failed_count"] == 2


def test_by_date_bulk_is_prioritized(database):
    db, _ = database
    source = Provider([quote(day=d) for d in DATES], caps=replace(CAPS, history_by_date=True))
    result = collect(db, source)
    assert source.calls == DATES
    assert result["outcome"] == "complete"


def test_truncated_bulk_response_backfills_missing_symbols(database):
    db, _ = database
    db.add(StockBasic(ts_code="600000.SH", name="另一银行", list_status="L"))
    db.commit()
    bulk = Provider([quote(day=d) for d in DATES], caps=replace(CAPS, name="bulk", history_by_date=True, history_by_symbol=False))
    single = Provider([quote(code="600000.SH", day=d) for d in DATES])
    result = collect(db, CompositeAdapter([bulk, single]))
    assert result["outcome"] == "complete" and result["success_count"] == 4
    assert len(single.calls) == 1 and single.calls[0]["ts_code"] == "600000.SH"


def test_actual_insert_exception_rolls_back_entire_batch(database):
    db, _ = database
    rows = [quote(), {**quote(day=DATES[1]), "close": "not-a-number"}]
    with pytest.raises(Exception):
        history._insert_missing(db, rows)
    assert db.query(DailyQuote).count() == 0
    # Session remains usable after rollback.
    history._insert_missing(db, [quote()])
    assert db.query(DailyQuote).count() == 1


def test_akshare_sync_strict_errors_are_not_reported_empty(monkeypatch):
    from app.services import tushare_adapter as adapters
    def failed(**kwargs):
        raise ConnectionError("injected")
    monkeypatch.setattr(adapters.ak, "stock_zh_a_hist", failed)
    monkeypatch.setattr(adapters.time, "sleep", lambda _: None)
    source = adapters.AkshareAdapter()
    assert source.get_daily("000001.SZ").empty
    with pytest.raises(ConnectionError):
        source.get_daily("000001.SZ", strict=True)


def test_akshare_historical_identity_survives_dataframe_construction(monkeypatch):
    from app.services import tushare_adapter as adapters
    frame = pd.DataFrame([{"日期": "2026-10-08", "开盘": 10, "最高": 11, "最低": 9,
                           "收盘": 10, "涨跌额": 0, "涨跌幅": 0, "成交量": 20, "成交额": 20000}])
    monkeypatch.setattr(adapters, "_call_with_retry", lambda *a, **k: frame)
    source = adapters.AkshareAdapter()
    result = source.get_daily("000001.SZ", strict=True)
    assert result["ts_code"].tolist() == ["000001.SZ"]
    from app.services.market_data_capabilities import provider_capabilities
    rows, rejected = history.normalize_history(result, provider_capabilities(source), {"20261008"}, {"000001.SZ"})
    assert rejected == 0 and rows[0]["amount"] == 20


def test_normalizer_rejects_bad_identity_duplicate_and_nonfinite():
    bad = quote(); bad["close"] = float("inf")
    rows, rejected = history.normalize_history(pd.DataFrame([quote(), quote(), bad, quote(code="000001.SH")]), CAPS, set(DATES), {"000001.SZ"})
    assert rows == [] and rejected == 4


def test_calendar_excludes_holidays_and_includes_completed_today():
    p = Provider()
    dates, info = history.resolve_history_dates(p, 2, now=datetime(2026, 10, 8, 17))
    assert dates == ["20260930", "20261008"] and info["status"] == "provided_calendar"
    dates, _ = history.resolve_history_dates(p, 1, now=datetime(2026, 10, 8, 15, 59))
    assert dates == ["20260930"]
    with pytest.raises(ValueError):
        history.resolve_history_dates(p, 1, "20261009", now=datetime(2026, 10, 8, 17))
    with pytest.raises(ValueError):
        history.resolve_history_dates(p, 5, "20270104", now=datetime(2027, 1, 4, 17))


def test_task_failure_persists_and_is_not_swallowed(database, monkeypatch):
    from app.services import sync_service
    from app.tasks.background import TaskStatus, task_registry
    db, factory = database
    monkeypatch.setattr(sync_service, "SessionLocal", factory)
    monkeypatch.setattr(sync_service, "tushare_adapter", Provider())
    monkeypatch.setattr(history, "resolve_history_dates", lambda *args: (DATES, {"status": "fixture"}))
    monkeypatch.setattr(history.clock, "sleep", lambda _: None)
    task = TaskStatus(id="t06-test", type="sync_full_market")
    monkeypatch.setitem(task_registry, task.id, task)
    with pytest.raises(RuntimeError):
        sync_service.sync_full_market(task.id, 2)
    assert task.status == "failed" and task.result["outcome"] == "no_data"
    db.expire_all()
    log = db.get(SyncLog, task.id)
    assert log.status == "failed" and json.loads(log.result)["days_synced"] == 0


def test_background_wrapper_preserves_failed_full_market_task(database, monkeypatch):
    from app.services import sync_service
    from app.tasks import background
    _, factory = database
    class ImmediateExecutor:
        def submit(self, fn):
            fn()
    registry = {}
    monkeypatch.setattr(background, "executor", ImmediateExecutor())
    monkeypatch.setattr(background, "task_registry", registry)
    monkeypatch.setattr(sync_service, "task_registry", registry)
    monkeypatch.setattr(sync_service, "SessionLocal", factory)
    monkeypatch.setattr(sync_service, "tushare_adapter", Provider())
    monkeypatch.setattr(history, "resolve_history_dates", lambda *args: (DATES, {"status": "fixture"}))
    monkeypatch.setattr(history.clock, "sleep", lambda _: None)
    task_id = background.submit_task("sync_full_market", sync_service.sync_full_market, 2)
    assert registry[task_id].status == "failed"


def test_sync_api_forwards_optional_end_date_and_reports_capabilities(monkeypatch):
    from app.routers import sync as routes
    from app.services import tushare_adapter as adapters
    calls = []
    def submit(*args):
        calls.append(args)
        return "fixture-task"
    monkeypatch.setattr(routes, "submit_task", submit)
    assert routes.sync_full_market_route(2, "20261009") == {"task_id": "fixture-task"}
    assert calls[0][2:] == (2, "20261009")
    monkeypatch.setattr(adapters, "tushare_adapter", Provider())
    response = routes.full_market_capabilities()
    assert response["providers"][0]["name"] == "fixture"
    assert response["market_coverage_ratio"] is None
