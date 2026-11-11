from __future__ import annotations

import csv
import logging
import os
import threading
import uuid
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

from app.database import SessionLocal
from app.models.task import SchedulerLease, ScheduledJobRun
from app.services.scheduled_jobs_service import (
    run_4pm_collect_limit_up_job, run_5pm_sync_latest_kline_job,
    run_idle_main_wave_concept_backfill_job, run_idle_pool_kline_backfill_job,
    run_industry_report_job, run_intraday_scan_job,
)
from app.services.trading_session import shanghai_datetime, is_a_share_trading_session
from app.config import (
    IDLE_KLINE_BACKFILL_ENABLED, IDLE_KLINE_BACKFILL_INTERVAL_MINUTES,
    IDLE_MAIN_WAVE_CONCEPT_BACKFILL_ENABLED, IDLE_MAIN_WAVE_CONCEPT_BACKFILL_INTERVAL_MINUTES,
    env_flag,
)

logger = logging.getLogger(__name__)
LEASE_SECONDS = 120


@lru_cache(maxsize=8)
def _calendar(path: str) -> dict[str, bool]:
    with open(path, encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    result = {}
    for row in rows:
        day = row["trade_date"]
        datetime.strptime(day, "%Y%m%d")
        if len(day) != 8 or day in result or row["is_open"] not in {"0", "1"}:
            raise ValueError("交易日历格式错误或日期重复")
        result[day] = row["is_open"] == "1"
    return result


def is_scheduler_trade_day(now: datetime) -> bool:
    day = shanghai_datetime(now).strftime("%Y%m%d")
    default = Path(__file__).resolve().parents[2] / "data_reference" / f"sse_calendar_{day[:4]}.csv"
    path = os.getenv("SCHEDULER_CALENDAR_FILE", str(default))
    try:
        # Missing dates are not silently treated as weekdays/open sessions.
        return _calendar(path).get(day, False)
    except (OSError, ValueError, KeyError):
        logger.error("Scheduler calendar unavailable: %s; market jobs disabled", path)
        return False


class DailyJobScheduler:
    """Single leased scheduler; each slot is claimed once and never auto-replayed.

    Default misfire policy is skip. Opt-in catch_up only runs today's daily jobs
    within SCHEDULER_MISFIRE_GRACE_SECONDS (default 3600 seconds); missed intraday
    scans are never replayed. Failed/interrupted work requires manual inspection.
    """
    def __init__(self, session_factory=None):
        self._factory = session_factory
        self.owner_id = f"{os.getpid()}-{uuid.uuid4()}"
        self._stop_event = threading.Event()
        self._heartbeat_stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._heartbeat_thread: threading.Thread | None = None
        self._start_lock = threading.Lock()

    def _db(self):
        return (self._factory or SessionLocal)()

    def _acquire_lease(self, now: datetime) -> bool:
        with self._db() as db:
            previous = db.get(SchedulerLease, "daily_scheduler")
            old_owner = previous.owner_id if previous else None
            updated = db.query(SchedulerLease).filter(
                SchedulerLease.id == "daily_scheduler",
                or_(SchedulerLease.owner_id == self.owner_id, SchedulerLease.expires_at <= now),
            ).update({"owner_id": self.owner_id, "heartbeat_at": now,
                      "expires_at": now + timedelta(seconds=LEASE_SECONDS)}, synchronize_session=False)
            if not updated:
                if previous is not None:
                    return False
                db.add(SchedulerLease(id="daily_scheduler", owner_id=self.owner_id,
                                      heartbeat_at=now, expires_at=now + timedelta(seconds=LEASE_SECONDS)))
                try:
                    db.flush()
                except IntegrityError:
                    db.rollback()
                    return False
            if old_owner != self.owner_id:
                db.query(ScheduledJobRun).filter(ScheduledJobRun.status == "running").update(
                    {"status": "interrupted", "completed_at": now,
                     "error": "原调度器租约已失效；请核查业务结果后手动重试"}, synchronize_session=False)
            db.commit()
            return True

    def _renew_lease(self) -> bool:
        now = datetime.utcnow()
        with self._db() as db:
            count = db.query(SchedulerLease).filter(
                SchedulerLease.id == "daily_scheduler", SchedulerLease.owner_id == self.owner_id,
            ).update({"heartbeat_at": now, "expires_at": now + timedelta(seconds=LEASE_SECONDS)},
                     synchronize_session=False)
            db.commit()
            return bool(count)

    def _heartbeat(self):
        while not self._heartbeat_stop.wait(20):
            try:
                if not self._renew_lease():
                    logger.error("Scheduler lease lost; no further jobs will start")
                    self._stop_event.set()
                    return
            except Exception:
                logger.exception("Could not renew scheduler lease")
                self._stop_event.set()
                return

    def start(self):
        with self._start_lock:
            if self._thread and self._thread.is_alive():
                return
            # Validate migrations before starting a daemon; no implicit create_all.
            with self._db() as db:
                db.query(SchedulerLease.id).limit(1).all()
                db.query(ScheduledJobRun.id).limit(1).all()
            self._stop_event.clear()
            self._heartbeat_stop.clear()
            self._thread = threading.Thread(target=self._loop, daemon=True, name="daily-job-scheduler")
            self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)
        # A long-running job keeps renewing its lease until its loop exits.
        # This prevents another process starting new jobs during graceful drain.

    def _claim(self, key: str, slot: str, status: str, now: datetime) -> str | None:
        with self._db() as db:
            lease = db.get(SchedulerLease, "daily_scheduler")
            if not lease or lease.owner_id != self.owner_id or lease.expires_at <= now:
                return None
            run_id = str(uuid.uuid4())
            db.add(ScheduledJobRun(id=run_id, job_key=key, slot=slot, status=status,
                                   started_at=now, completed_at=now if status == "skipped" else None,
                                   error="错过执行窗口，按 skip 策略跳过" if status == "skipped" else None))
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                return None
            return run_id

    def _run_job(self, key: str, slot: str, fn, *, skipped=False, now=None):
        now = now or datetime.utcnow()
        run_id = self._claim(key, slot, "skipped" if skipped else "running", now)
        if not run_id or skipped:
            return False
        status, error = "completed", None
        try:
            result = fn()
            if isinstance(result, dict) and (result.get("status") in {"failed", "partial"}
                                             or result.get("error_count", 0) or result.get("errors")):
                status, error = "failed", str(result)[:2000]
            logger.info("Scheduler job %s %s", key, status)
        except Exception as exc:
            status, error = "failed", str(exc)[:2000]
            logger.exception("Scheduler job %s failed", key)
        with self._db() as db:
            # An interrupted run must not be changed back to success by a late worker.
            db.query(ScheduledJobRun).filter(ScheduledJobRun.id == run_id,
                                             ScheduledJobRun.status == "running").update(
                {"status": status, "error": error, "completed_at": datetime.utcnow()},
                synchronize_session=False)
            db.commit()
        return status == "completed"

    def run_once(self, now: datetime | None = None):
        local = shanghai_datetime(now)
        utc = local.astimezone(timezone.utc).replace(tzinfo=None)
        if not self._acquire_lease(utc):
            return False
        if self._thread is not None and (self._heartbeat_thread is None or not self._heartbeat_thread.is_alive()):
            self._heartbeat_thread = threading.Thread(target=self._heartbeat, daemon=True, name="scheduler-heartbeat")
            self._heartbeat_thread.start()
        if is_scheduler_trade_day(local):
            daily = [
                ("industry_report_preopen_0830", 8, 30, lambda: run_industry_report_job("preopen")),
                ("industry_report_afterclose_1530", 15, 30, lambda: run_industry_report_job("afterclose")),
                ("collect_limit_up_16", 16, 0, run_4pm_collect_limit_up_job),
                ("sync_latest_kline_17", 17, 0, run_5pm_sync_latest_kline_job),
            ]
            if env_flag("MESSAGE_PIPELINE_ENABLED", False):
                from app.services.message_pipeline_service import run_message_pipeline_job
                daily.extend([
                    ("message_pipeline_preopen_0815", 8, 15,
                     lambda: run_message_pipeline_job(trade_date=local.strftime("%Y%m%d"))),
                    ("message_pipeline_afterclose_1515", 15, 15,
                     lambda: run_message_pipeline_job(trade_date=local.strftime("%Y%m%d"))),
                ])
            daily.sort(key=lambda job: (job[1], job[2]))
            for key, hour, minute, fn in daily:
                due = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
                current = local if now is not None else shanghai_datetime()
                lateness = (current - due).total_seconds()
                if lateness < 0:
                    continue
                catch_up = os.getenv("SCHEDULER_MISFIRE_POLICY", "skip") == "catch_up"
                grace = max(60, int(os.getenv("SCHEDULER_MISFIRE_GRACE_SECONDS", "3600"))) if catch_up else 60
                claim_time = utc if now is not None else datetime.utcnow()
                self._run_job(key, due.strftime("%Y%m%d%H%M"), fn, skipped=lateness >= grace, now=claim_time)
            if is_a_share_trading_session(local):
                self._run_job("intraday_scan", local.strftime("%Y%m%d%H%M"), run_intraday_scan_job, now=utc)
        for enabled, key, minutes, fn in [
            (IDLE_KLINE_BACKFILL_ENABLED, "idle_pool_kline_backfill", IDLE_KLINE_BACKFILL_INTERVAL_MINUTES, run_idle_pool_kline_backfill_job),
            (IDLE_MAIN_WAVE_CONCEPT_BACKFILL_ENABLED, "idle_main_wave_concept_backfill", IDLE_MAIN_WAVE_CONCEPT_BACKFILL_INTERVAL_MINUTES, run_idle_main_wave_concept_backfill_job),
        ]:
            if enabled:
                bucket = int(local.timestamp()) // (max(1, minutes) * 60)
                self._run_job(key, str(bucket), fn, now=utc)
        with self._db() as db:
            days = max(1, int(os.getenv("SCHEDULER_RUN_RETENTION_DAYS", "90")))
            db.query(ScheduledJobRun).filter(ScheduledJobRun.status != "running",
                                             ScheduledJobRun.completed_at < utc - timedelta(days=days)).delete(synchronize_session=False)
            db.commit()
        return True

    def _loop(self):
        try:
            while not self._stop_event.is_set():
                try:
                    self.run_once()
                except Exception:
                    logger.exception("Scheduler iteration failed")
                self._stop_event.wait(20)
        finally:
            self._heartbeat_stop.set()
            with self._db() as db:
                db.query(SchedulerLease).filter(SchedulerLease.id == "daily_scheduler",
                                                SchedulerLease.owner_id == self.owner_id).update(
                    {"expires_at": datetime.utcnow()}, synchronize_session=False)
                db.commit()


scheduler = DailyJobScheduler()
