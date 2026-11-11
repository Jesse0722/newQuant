from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.models.task import SchedulerLease, ScheduledJobRun
from app.tasks import scheduler as module


@pytest.fixture
def setup(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'scheduler.db'}")
    SchedulerLease.__table__.create(engine)
    ScheduledJobRun.__table__.create(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(module, "IDLE_KLINE_BACKFILL_ENABLED", False)
    monkeypatch.setattr(module, "IDLE_MAIN_WAVE_CONCEPT_BACKFILL_ENABLED", False)
    monkeypatch.setenv("MESSAGE_PIPELINE_ENABLED", "false")
    monkeypatch.setenv("SCHEDULER_MISFIRE_POLICY", "skip")
    calls = []
    monkeypatch.setattr(module, "run_industry_report_job", lambda session: calls.append(session) or {})
    monkeypatch.setattr(module, "run_4pm_collect_limit_up_job", lambda: calls.append("limit_up") or {})
    monkeypatch.setattr(module, "run_5pm_sync_latest_kline_job", lambda: calls.append("sync") or {})
    monkeypatch.setattr(module, "run_intraday_scan_job", lambda: calls.append("intraday") or {})
    yield factory, calls
    engine.dispose()


def local(hour, minute=0, day="2026-11-11"):
    return datetime.fromisoformat(f"{day}T{hour:02d}:{minute:02d}:00").replace(tzinfo=ZoneInfo("Asia/Shanghai"))


def test_slots_are_durable_and_default_misfires_are_skipped(setup):
    factory, calls = setup
    first = module.DailyJobScheduler(factory)
    assert first.run_once(local(17))
    first.run_once(local(17))
    assert calls == ["sync"]
    with factory() as db:
        runs = db.query(ScheduledJobRun).all()
        assert len(runs) == 4
        assert sum(r.status == "skipped" for r in runs) == 3
        # Expire the owner to simulate a process exit; restart must not replay.
        db.get(SchedulerLease, "daily_scheduler").expires_at = datetime(2020, 1, 1)
        db.commit()
    restarted = module.DailyJobScheduler(factory)
    assert restarted.run_once(local(17))
    assert calls == ["sync"]


def test_live_lease_prevents_another_scheduler_and_utc_is_converted(setup):
    factory, calls = setup
    first, second = module.DailyJobScheduler(factory), module.DailyJobScheduler(factory)
    first.run_once(datetime(2026, 11, 11, 9, tzinfo=ZoneInfo("UTC")))
    assert calls == ["sync"]
    assert not second.run_once(local(17))
    assert calls == ["sync"]


def test_holiday_never_runs_market_jobs(setup):
    factory, calls = setup
    module.DailyJobScheduler(factory).run_once(local(17, day="2026-10-01"))
    assert calls == []


def test_missing_calendar_fails_closed(setup, monkeypatch, tmp_path):
    factory, calls = setup
    monkeypatch.setenv("SCHEDULER_CALENDAR_FILE", str(tmp_path / "missing.csv"))
    module.DailyJobScheduler(factory).run_once(local(17))
    assert calls == []


def test_opt_in_catchup_is_bounded_and_failure_not_replayed(setup, monkeypatch):
    factory, calls = setup
    monkeypatch.setenv("SCHEDULER_MISFIRE_POLICY", "catch_up")
    monkeypatch.setenv("SCHEDULER_MISFIRE_GRACE_SECONDS", "3600")
    def fail():
        calls.append("failed-sync")
        raise RuntimeError("source unavailable")
    monkeypatch.setattr(module, "run_5pm_sync_latest_kline_job", fail)
    scheduler = module.DailyJobScheduler(factory)
    scheduler.run_once(local(17, 10))
    scheduler.run_once(local(17, 11))
    assert calls == ["failed-sync"]
    with factory() as db:
        assert db.query(ScheduledJobRun).filter_by(job_key="sync_latest_kline_17").one().status == "failed"


def test_takeover_marks_running_job_interrupted_and_does_not_replay(setup):
    factory, calls = setup
    first = module.DailyJobScheduler(factory)
    utc = local(17).astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
    first._acquire_lease(utc)
    assert first._claim("sync_latest_kline_17", "202611111700", "running", utc)
    with factory() as db:
        db.get(SchedulerLease, "daily_scheduler").expires_at = utc - timedelta(seconds=1)
        db.commit()
    module.DailyJobScheduler(factory).run_once(local(17))
    assert calls == []
    with factory() as db:
        assert db.query(ScheduledJobRun).filter_by(job_key="sync_latest_kline_17").one().status == "interrupted"


def test_intraday_slot_deduplicates_within_minute(setup):
    factory, calls = setup
    scheduler = module.DailyJobScheduler(factory)
    scheduler.run_once(local(10))
    scheduler.run_once(local(10))
    assert calls == ["intraday"]


def test_message_pipeline_is_default_off_then_claimed_once(setup, monkeypatch):
    from app.services import message_pipeline_service
    factory, calls = setup
    monkeypatch.setattr(message_pipeline_service, "run_message_pipeline_job",
                        lambda trade_date=None: calls.append("pipeline:" + trade_date) or {"status": "completed", "error_count": 0})
    scheduler = module.DailyJobScheduler(factory)
    scheduler.run_once(local(8, 15))
    assert calls == []
    monkeypatch.setenv("MESSAGE_PIPELINE_ENABLED", "true")
    scheduler.run_once(local(8, 15))
    scheduler.run_once(local(8, 15))
    assert calls == ["pipeline:20261111"]
