from __future__ import annotations

import logging
import signal
import sys
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.config import SCHEDULER_ENABLED
from app.tasks.scheduler import scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)

logger = logging.getLogger(__name__)
_running = True


def _handle_stop(_signum, _frame):
    global _running
    logger.info("Received stop signal, shutting down scheduler runner")
    _running = False


def main() -> None:
    if not SCHEDULER_ENABLED:
        logger.info("Scheduler runner skipped because SCHEDULER_ENABLED=false")
        return

    signal.signal(signal.SIGINT, _handle_stop)
    signal.signal(signal.SIGTERM, _handle_stop)
    scheduler.start()

    try:
        while _running:
            time.sleep(1)
    finally:
        scheduler.stop()


if __name__ == "__main__":
    main()
