"""Opt-in task/scheduler/transaction concurrency against a throwaway PG schema."""
from __future__ import annotations

import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
import app.models  # noqa: F401
from app.models.monitor import Alert
from app.models.pool import WatchPool, WatchStock
from app.models.trade import TradePlan
from app.models.task import BackgroundTask, ScheduledJobRun
from app.routers.alerts import create_plan_from_alert
from app.tasks import background
from app.tasks import scheduler as scheduler_module

pytestmark = pytest.mark.integration


@pytest.fixture
def pg_factory(monkeypatch):
    url = os.environ.get("RUNTIME_POSTGRES_TEST_URL")
    if not url:
        pytest.skip("set RUNTIME_POSTGRES_TEST_URL for disposable schema concurrency checks")
    admin = create_engine(url, isolation_level="AUTOCOMMIT")
    schema = "newquant_runtime_test_" + uuid.uuid4().hex
    with admin.connect() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    try:
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine)
        monkeypatch.setattr(background, "SessionLocal", factory)
        yield factory
    finally:
        engine.dispose()
        with admin.connect() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        admin.dispose()


def test_pg_concurrent_alert_claim_creates_one_plan(pg_factory):
    with pg_factory() as db:
        pool = WatchPool(name="concurrency")
        db.add(pool)
        db.flush()
        stock = WatchStock(pool_id=pool.id, ts_code="000001.SZ")
        db.add(stock)
        db.flush()
        alert = Alert(stock_id=stock.id, ts_code=stock.ts_code, trigger_date="20261111")
        db.add(alert)
        db.commit()
        identifier = alert.id
    def create(_):
        with pg_factory() as db:
            return create_plan_from_alert(identifier, db)["id"]
    with ThreadPoolExecutor(max_workers=6) as executor:
        plans = list(executor.map(create, range(12)))
    assert len(set(plans)) == 1
    with pg_factory() as db:
        assert db.query(TradePlan).count() == 1
        assert db.get(Alert, identifier).plan_id == plans[0]


def test_pg_task_result_and_stale_recovery(pg_factory, monkeypatch):
    class ImmediateExecutor:
        def submit(self, fn):
            fn()
    monkeypatch.setattr(background, "executor", ImmediateExecutor())
    def succeed(task_id):
        background.task_registry[task_id].result = {"evidence": [{"id": 1}], "score": None}
    identifier = background.submit_task("sync", succeed)
    monkeypatch.delitem(background.task_registry, identifier)
    assert background.get_task_status(identifier).result == {"evidence": [{"id": 1}], "score": None}
    now = datetime.utcnow()
    with pg_factory() as db:
        db.add(BackgroundTask(id="pg-interrupted", type="sync", status="running", progress=.2,
                              message="", owner_id="old-process", created_at=now,
                              updated_at=now, heartbeat_at=now - timedelta(seconds=background.STALE_SECONDS + 1)))
        db.commit()
    assert background.get_task_status("pg-interrupted").status == "interrupted"


def test_pg_scheduler_singleton_and_slot_claim(pg_factory, monkeypatch):
    monkeypatch.setenv("MESSAGE_PIPELINE_ENABLED", "false")
    monkeypatch.setenv("SCHEDULER_MISFIRE_POLICY", "skip")
    monkeypatch.setattr(scheduler_module, "IDLE_KLINE_BACKFILL_ENABLED", False)
    monkeypatch.setattr(scheduler_module, "IDLE_MAIN_WAVE_CONCEPT_BACKFILL_ENABLED", False)
    calls = []
    monkeypatch.setattr(scheduler_module, "run_5pm_sync_latest_kline_job", lambda: calls.append(1) or {})
    now = datetime(2026, 11, 11, 17, tzinfo=ZoneInfo("Asia/Shanghai"))
    schedulers = [scheduler_module.DailyJobScheduler(pg_factory) for _ in range(2)]
    with ThreadPoolExecutor(max_workers=2) as executor:
        claimed = list(executor.map(lambda scheduler: scheduler.run_once(now), schedulers))
    assert sum(claimed) == 1
    assert calls == [1]
    with pg_factory() as db:
        assert db.query(ScheduledJobRun).count() == 4
