from __future__ import annotations

import threading
import time
import logging
from datetime import datetime

from app.services.scheduled_jobs_service import (
    run_4pm_collect_limit_up_job,
    run_5pm_sync_latest_kline_job,
    run_industry_report_job,
    run_intraday_scan_job,
)

logger = logging.getLogger(__name__)


class DailyJobScheduler:
    def __init__(self):
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_run_date: dict[str, str] = {}

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="daily-job-scheduler")
        self._thread.start()
        logger.info("Scheduler started")

    def stop(self):
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)
        self._thread = None
        logger.info("Scheduler stopped")

    def _should_run(self, key: str, now: datetime, hour: int, minute: int) -> bool:
        today = now.strftime("%Y%m%d")
        if now.weekday() >= 5:
            return False
        # 仅在目标分钟执行，避免服务重启后“补跑”导致并发写库冲突
        if not (now.hour == hour and now.minute == minute):
            return False
        return self._last_run_date.get(key) != today

    def _mark_run(self, key: str, now: datetime):
        self._last_run_date[key] = now.strftime("%Y%m%d")

    def _safe_run(self, key: str, fn):
        try:
            result = fn()
            logger.info("Scheduler job %s done: %s", key, result)
            return True
        except Exception:
            logger.exception("Scheduler job %s failed", key)
            return False

    def _loop(self):
        while not self._stop_event.is_set():
            now = datetime.now()

            # 盘中每分钟检查一次是否触发分钟级扫描（由配置中的 interval_minutes 决定）
            if now.second < 20:
                self._safe_run("intraday_scan", run_intraday_scan_job)

            if self._should_run("industry_report_preopen_0830", now, 8, 30):
                if self._safe_run("industry_report_preopen_0830", lambda: run_industry_report_job("preopen")):
                    self._mark_run("industry_report_preopen_0830", now)

            if self._should_run("industry_report_afterclose_1530", now, 15, 30):
                if self._safe_run("industry_report_afterclose_1530", lambda: run_industry_report_job("afterclose")):
                    self._mark_run("industry_report_afterclose_1530", now)

            if self._should_run("collect_limit_up_16", now, 16, 0):
                if self._safe_run("collect_limit_up_16", run_4pm_collect_limit_up_job):
                    self._mark_run("collect_limit_up_16", now)

            if self._should_run("sync_latest_kline_17", now, 17, 0):
                if self._safe_run("sync_latest_kline_17", run_5pm_sync_latest_kline_job):
                    self._mark_run("sync_latest_kline_17", now)

            time.sleep(20)


scheduler = DailyJobScheduler()
