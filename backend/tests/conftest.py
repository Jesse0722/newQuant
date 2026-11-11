from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="run tests marked as integration",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption("--run-integration"):
        return

    skip_integration = pytest.mark.skip(
        reason="integration test skipped by default; pass --run-integration to enable",
    )
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_integration)


@pytest.fixture(scope="session")
def background_storage_factory(tmp_path_factory):
    """Task metadata always uses a disposable DB, never a developer .env DB."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.models.task import BackgroundTask, SchedulerLease, ScheduledJobRun
    path = tmp_path_factory.mktemp("background-storage") / "tasks.db"
    engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
    for model in (BackgroundTask, SchedulerLease, ScheduledJobRun):
        model.__table__.create(engine)
    yield sessionmaker(bind=engine, expire_on_commit=False)
    engine.dispose()


@pytest.fixture(autouse=True)
def isolate_background_task_storage(monkeypatch, background_storage_factory):
    # Only metadata storage is overridden; integration tests keep their own
    # explicitly configured business database and may override this factory.
    from app.tasks import background
    monkeypatch.setattr(background, "SessionLocal", background_storage_factory)
    monkeypatch.setattr(background, "_ensure_monitor", lambda: None)
