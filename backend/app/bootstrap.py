from __future__ import annotations

import logging

from app.config import (
    AUTO_INIT_DB,
    AUTO_START_SCHEDULER,
    RUN_STARTUP_MIGRATIONS,
    SCHEDULER_ENABLED,
)
from app.database import init_db
from app.tasks.scheduler import scheduler

logger = logging.getLogger(__name__)


def initialize_application() -> None:
    if AUTO_INIT_DB:
        logger.info(
            "Initializing database at startup (run_migrations=%s)",
            RUN_STARTUP_MIGRATIONS,
        )
        init_db(run_migrations=RUN_STARTUP_MIGRATIONS, create_tables=True)
    else:
        logger.info("Skipping database initialization at startup")

    if AUTO_START_SCHEDULER and SCHEDULER_ENABLED:
        scheduler.start()
    else:
        logger.info(
            "Skipping scheduler startup (auto_start=%s, enabled=%s)",
            AUTO_START_SCHEDULER,
            SCHEDULER_ENABLED,
        )


def shutdown_application() -> None:
    scheduler.stop()
