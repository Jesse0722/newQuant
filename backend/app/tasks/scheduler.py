import threading
import time
from datetime import datetime

from app.services.scheduled_jobs_service import (
    run_4pm_collect_limit_up_job,
    run_5pm_sync_latest_kline_job,
    run_intraday_scan_job,
)


class DailyJobScheduler:
    def __init__(self):
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_run_date: dict[str, str] = {}

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._loop, daemon=True, name="daily-job-scheduler")
        self._thread.start()
        print("[scheduler] started")

    def stop(self):
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)
        print("[scheduler] stopped")

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
            print(f"[scheduler] {key} done: {result}")
        except Exception as e:
            print(f"[scheduler] {key} failed: {e}")

    def _loop(self):
        while not self._stop_event.is_set():
            now = datetime.now()

            # 盘中每分钟检查一次是否触发分钟级扫描（由配置中的 interval_minutes 决定）
            if now.second < 20:
                self._safe_run("intraday_scan", run_intraday_scan_job)

            if self._should_run("collect_limit_up_16", now, 16, 0):
                self._safe_run("collect_limit_up_16", run_4pm_collect_limit_up_job)
                self._mark_run("collect_limit_up_16", now)

            if self._should_run("sync_latest_kline_17", now, 17, 0):
                self._safe_run("sync_latest_kline_17", run_5pm_sync_latest_kline_job)
                self._mark_run("sync_latest_kline_17", now)

            time.sleep(20)


scheduler = DailyJobScheduler()


def start_scheduler():
    scheduler.start()


def stop_scheduler():
    scheduler.stop()

