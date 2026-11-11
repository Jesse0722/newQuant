from __future__ import annotations

from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, event
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from app.database import Base
import app.models  # noqa: F401
from app.models.monitor import Alert
from app.models.pool import WatchPool, WatchStock
from app.models.stock import DailyQuote
from app.models.trade import TradePlan, TradePlanStock, TradeDetail
from app.routers import plans, alerts
from app.schemas.trade import TradeDetailCreate, TradeDetailUpdate, ReviewSubmit, TradePlanUpdate
from app.services import monitor_engine, strategy_service, strategy_backtest, sync_service
from app.tasks import background


@pytest.fixture
def database(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'correctness.db'}", connect_args={"check_same_thread": False, "timeout": 20})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    yield factory
    engine.dispose()


def test_latest_window_and_historical_cutoff(database):
    with database() as db:
        for i in range(300):
            db.add(DailyQuote(ts_code="000001.SZ", trade_date=(datetime(2025, 1, 1) + timedelta(days=i)).strftime("%Y%m%d"),
                              open=10, high=30, low=10, close=30 if i == 299 else 10, vol=100))
        db.commit()
        for read in (monitor_engine._get_df, strategy_service._get_df_from_db):
            frame = read(db, "000001.SZ")
            assert len(frame) == 250
            assert frame.iloc[-1]["trade_date"] == "20251027"
            assert frame.iloc[-1]["close"] == 30
        assert not monitor_engine.evaluate_template(monitor_engine._get_df(db, "000001.SZ"), "ma_support", {"n": 20})
        history = monitor_engine._get_df(db, "000001.SZ", as_of_date="20250601")
        assert history.iloc[-1]["trade_date"] == "20250601"


def test_full_market_indicator_uses_condition_history(database, monkeypatch):
    frame = pd.DataFrame({"close": list(range(1, 62)), "vol": [100] * 61})
    for field in ("open", "high", "low", "pre_close"):
        frame[field] = frame["close"]
    frame["pct_chg"] = 0
    calls = []
    monkeypatch.setattr(strategy_service, "SessionLocal", database)
    monkeypatch.setattr(strategy_service, "_fetch_full_market_daily", lambda days: calls.append(days) or {"000001.SZ": frame})
    monkeypatch.setattr(strategy_service.tushare_adapter, "get_stock_basic", lambda: pd.DataFrame())
    task = background.TaskStatus(id="condition-history", type="strategy")
    monkeypatch.setitem(background.task_registry, task.id, task)
    strategy_service.run_indicator_screen(task.id, "full", [{"template_id": "breakout_high", "params": {"n": 60}}], "and")
    assert calls == [61]
    assert task.result["ts_codes"] == ["000001.SZ"]
    assert strategy_service._eval_condition(frame.head(20), "ma_above", {"n": 20})
    assert not strategy_service._eval_condition(frame.head(19), "ma_above", {"n": 20})
    assert not strategy_service._eval_condition(frame.head(60), "breakout_high", {"n": 60})


def test_indicator_reports_insufficient_history(database, monkeypatch):
    monkeypatch.setattr(strategy_service, "SessionLocal", database)
    monkeypatch.setattr(strategy_service, "_fetch_full_market_daily", lambda days: {"000001.SZ": pd.DataFrame({"close": [10] * 10})})
    monkeypatch.setattr(strategy_service.tushare_adapter, "get_stock_basic", lambda: pd.DataFrame())
    task = background.TaskStatus(id="short-history", type="strategy")
    monkeypatch.setitem(background.task_registry, task.id, task)
    strategy_service.run_indicator_screen(task.id, "full", [{"template_id": "ma_above", "params": {"n": 20}}], "and")
    assert task.result["insufficient_data_codes"] == ["000001.SZ"]
    assert task.result["total"] == 0


def test_lock_error_never_reports_an_empty_commit_as_success(database):
    with database() as db:
        db.add(DailyQuote(ts_code="000001.SZ", trade_date="20261111", close=10))
        calls = []
        def fail_once(session):
            calls.append(1)
            raise OperationalError("COMMIT", {}, Exception("database is locked"))
        event.listen(db, "before_commit", fail_once, once=True)
        with pytest.raises(OperationalError):
            sync_service._commit_with_retry(db, wait_s=0)
        assert calls == [1]
        assert db.query(DailyQuote).count() == 0


@pytest.mark.parametrize("field,value", [
    ("direction", "oops"), ("trade_date", "20260230"), ("trade_date", "2026-01-01"),
    ("price", -1), ("price", float("inf")), ("quantity", 0), ("quantity", -1),
    ("commission", -1), ("trade_time", "25:00:00"),
])
def test_invalid_execution_fields_rejected(field, value):
    body = dict(trade_date="20261111", direction="buy", price=10, quantity=100)
    body[field] = value
    with pytest.raises(ValidationError):
        TradeDetailCreate(**body)
    with pytest.raises(ValidationError):
        TradeDetailUpdate(**{field: value})


@pytest.mark.parametrize("field", ["trade_date", "direction", "price", "quantity", "commission"])
def test_required_execution_fields_cannot_be_cleared(field):
    with pytest.raises(ValidationError):
        TradeDetailUpdate(**{field: None})
    assert TradeDetailUpdate().model_dump(exclude_unset=True) == {}


def test_plan_status_matches_active_ui():
    assert TradePlanUpdate(status="active").status == "active"
    with pytest.raises(ValidationError):
        TradePlanUpdate(status="unknown")


def test_review_snapshot_does_not_override_current_cash_flow(database):
    with database() as db:
        plan = TradePlan(title="研究计划")
        db.add(plan)
        db.flush()
        db.add(TradePlanStock(plan_id=plan.id, ts_code="000001.SZ"))
        db.add(TradeDetail(ts_code="000001.SZ", trade_date="20261101", direction="buy", price=10,
                           quantity=100, amount=1000, commission=0, stamp_tax=0))
        sell = TradeDetail(ts_code="000001.SZ", trade_date="20261102", direction="sell", price=12,
                           quantity=100, amount=1200, commission=0, stamp_tax=0)
        db.add(sell)
        db.commit()
        reviewed = plans.submit_review(plan.id, ReviewSubmit(review_summary="当时复盘"), db)
        assert reviewed.review_pnl_snapshot == 200
        plans.update_detail(sell.id, TradeDetailUpdate(price=13), db)
        current = plans.get_plan(plan.id, db)
        assert current.actual_pnl == current.pnl_summary.net_pnl == 299.35
        assert current.review_pnl_snapshot == 200
        assert current.pnl_scope == "stock_lifetime"
        plans.delete_detail(sell.id, db)
        assert plans.get_plan(plan.id, db).actual_pnl == -1000


def test_alert_to_plan_is_idempotent_with_concurrent_requests(database):
    with database() as db:
        pool = WatchPool(name="test")
        db.add(pool)
        db.flush()
        stock = WatchStock(pool_id=pool.id, ts_code="000001.SZ")
        db.add(stock)
        db.flush()
        alert = Alert(stock_id=stock.id, ts_code=stock.ts_code, trigger_date="20261111")
        db.add(alert)
        db.commit()
        alert_id = alert.id
    def create(_):
        with database() as db:
            return alerts.create_plan_from_alert(alert_id, db)["id"]
    with ThreadPoolExecutor(max_workers=3) as executor:
        ids = list(executor.map(create, range(6)))
    assert len(set(ids)) == 1
    with database() as db:
        assert db.query(TradePlan).count() == 1
        assert db.query(TradePlanStock).count() == 1
        plans.delete_plan(ids[0], db)
        assert db.get(Alert, alert_id).plan_id is None
        assert db.get(Alert, alert_id).status == "pending"


def test_backtest_worst_forward_return_is_not_drawdown(database, monkeypatch):
    frame = pd.DataFrame({"trade_date": [(datetime(2026, 1, 1) + timedelta(days=i)).strftime("%Y%m%d") for i in range(40)],
                          "close": [10.0 + i for i in range(40)]})
    monkeypatch.setattr(strategy_backtest, "_build_backtest_df", lambda *args: frame)
    monkeypatch.setattr(strategy_backtest, "_calc_indicators", lambda df: df)
    monkeypatch.setattr(strategy_backtest, "_find_limit_up_idx", lambda *args: 0)
    monkeypatch.setattr(strategy_backtest, "_validate_life_line", lambda *args: {"valid": True})
    monkeypatch.setattr(strategy_backtest, "_analyze_stock", lambda *args: {"signal_status": "triggered"})
    with database() as db:
        result = strategy_backtest.run_strategy_backtest(db, "two_phase", "20260101", "20261231", codes=["000001.SZ"])
    assert result["total_signals"] == 34
    assert result["max_drawdown"] is None
    assert result["worst_return_5d"] == 11.36
    assert result["evaluation_basis"] == "signal_close_forward_return"


def test_new_plan_claims_valid_alert_and_reuses_existing(database):
    from app.schemas.trade import TradePlanCreate, TradePlanStockCreate
    from app.exceptions import AppError
    with database() as db:
        pool = WatchPool(name="alert-plan")
        db.add(pool)
        db.flush()
        stock = WatchStock(pool_id=pool.id, ts_code="000001.SZ")
        db.add(stock)
        db.flush()
        alert = Alert(stock_id=stock.id, ts_code=stock.ts_code, trigger_date="20261111")
        db.add(alert)
        db.commit()
        body = TradePlanCreate(title="候选研究", alert_id=alert.id, stocks=[TradePlanStockCreate(ts_code=stock.ts_code)])
        first = plans.create_plan(body, db)
        second = plans.create_plan(body, db)
        assert first.id == second.id
        db.refresh(alert)
        assert alert.status == "processed" and alert.plan_id == first.id
        invalid = TradePlanCreate(title="bad", alert_id="unknown", stocks=body.stocks)
        with pytest.raises(AppError) as error:
            plans.create_plan(invalid, db)
        assert error.value.status_code == 404
        assert db.query(TradePlan).count() == 1


def _screen_task(database, monkeypatch, identifier="screen-evidence"):
    monkeypatch.setattr(strategy_service, "SessionLocal", database)
    task = background.TaskStatus(id=identifier, type="strategy")
    monkeypatch.setitem(background.task_registry, identifier, task)
    return task


@pytest.mark.parametrize("partial", [False, True])
def test_full_market_fetch_failure_is_data_insufficient(database, monkeypatch, partial):
    from app.services.market_data_capabilities import ProviderCapabilities
    from app.services import full_market_history_service
    class Historical:
        capabilities = ProviderCapabilities(name="fixture", history_by_date=True, history_by_symbol=True,
            snapshot_by_date=False, markets=("SZ",), volume_unit="lot", amount_unit="thousand_cny",
            requires_credentials=False, enabled=True, reliable_pre_close=True)
        def get_daily_by_date(self, day):
            if partial and day == "20261109":
                return pd.DataFrame([dict(ts_code="000001.SZ", trade_date=day, open=10, high=10,
                                         low=10, close=10, pre_close=10, pct_chg=0, vol=100, amount=1000)])
            raise RuntimeError("https://user:secret@proxy.invalid")
    monkeypatch.setattr(strategy_service, "tushare_adapter", Historical())
    monkeypatch.setattr(full_market_history_service, "resolve_history_dates",
                        lambda *args: (["20261109", "20261110"], {"status": "fixture"}))
    monkeypatch.setattr(strategy_service.time, "sleep", lambda seconds: None)
    task = _screen_task(database, monkeypatch, "fetch-partial" if partial else "fetch-failed")
    strategy_service.run_indicator_screen(task.id, "full", [{"template_id": "ma_above", "params": {"n": 20}}], "and")
    assert task.status == "failed"
    assert task.result["outcome"] == "insufficient_data"
    assert len(task.result["data_coverage"]["failed_dates"]) == (1 if partial else 2)
    assert "secret" not in repr(task.result) and "secret" not in task.message


def test_default_snapshot_provider_is_not_called_as_historical_bulk(database, monkeypatch):
    from app.services.tushare_adapter import TencentAdapter, ProviderRouter
    provider = TencentAdapter()
    calls = []
    monkeypatch.setattr(provider, "get_daily_by_date", lambda day: calls.append(day) or pd.DataFrame())
    router = ProviderRouter("tencent")
    router.provider = provider
    monkeypatch.setattr(strategy_service, "tushare_adapter", router)
    task = _screen_task(database, monkeypatch, "unsupported-bulk")
    strategy_service.run_indicator_screen(task.id, "full", [{"template_id": "ma_above", "params": {"n": 20}}], "and")
    assert task.status == "failed" and calls == []
    assert task.result["data_coverage"]["outcome"] == "unsupported_history"


def test_full_market_prefers_local_price_evidence_and_reports_gaps(database, monkeypatch):
    with database() as db:
        for code, count in [("000001.SZ", 6), ("000002.SZ", 5)]:
            for i in range(count):
                price = 10 + i
                db.add(DailyQuote(ts_code=code, trade_date=f"202611{i + 1:02d}", open=price, high=price,
                                  low=price, close=price, pre_close=price, pct_chg=0, vol=None, amount=None))
        db.commit()
    def external(*args):
        raise AssertionError("must not make external requests when local evidence exists")
    monkeypatch.setattr(strategy_service, "_fetch_full_market_daily", external)
    task = _screen_task(database, monkeypatch, "local-gap")
    strategy_service.run_indicator_screen(task.id, "full", [{"template_id": "ma_above", "params": {"n": 5}}], "and")
    assert task.status == "failed"
    assert task.result["ts_codes"] == ["000001.SZ"]
    assert task.result["insufficient_data_codes"] == ["000002.SZ"]
    assert task.result["insufficient_data_reasons"]["000002.SZ"] == ["missing_recent_dates"]
    assert task.result["data_coverage"]["source"] == "local_available_quotes"
    assert task.result["data_coverage"]["latest_available_date"] == "20261106"
