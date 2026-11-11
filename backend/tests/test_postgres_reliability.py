"""Real PostgreSQL migration/API/data-copy checks; scratch databases only."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
import os
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.exceptions import AppError, app_error_handler
from app.models.message import MessageSourceItem
from app.models.stock import StockBasic, DailyQuote
from app.routers.messages import router as messages_router
from app.routers.message_agents import router as agents_router
from app.routers.industry_reports import router as reports_router
from scripts.migrate_sqlite_to_postgres import migrate
from test_reliability_migrations import run_alembic, assert_schema_matches, seed_legacy_opportunity

pytestmark = pytest.mark.integration


@contextmanager
def scratch_postgres():
    configured = os.environ.get("QUOTE_REPAIR_POSTGRES_ADMIN_URL")
    if not configured:
        pytest.skip("set QUOTE_REPAIR_POSTGRES_ADMIN_URL for scratch PostgreSQL tests")
    url = make_url(configured)
    admin = create_engine(url, isolation_level="AUTOCOMMIT")
    name = "newquant_reliability_test_" + uuid.uuid4().hex[:12]
    target = url.set(database=name)
    with admin.connect() as conn:
        conn.exec_driver_sql('CREATE DATABASE "' + name + '"')
    engine = create_engine(target)
    try:
        yield target.render_as_string(hide_password=False), engine
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.exec_driver_sql('DROP DATABASE "' + name + '" WITH (FORCE)')
        admin.dispose()


def test_postgres_upgrade_legacy_data_downgrade_and_api_smoke():
    with scratch_postgres() as (url, engine):
        run_alembic(url, "upgrade", "1f4b0c7d9e2a")
        seed_legacy_opportunity(engine)
        run_alembic(url, "upgrade", "head")
        assert_schema_matches(engine)
        factory = sessionmaker(bind=engine)
        app = FastAPI()
        app.add_exception_handler(AppError, app_error_handler)
        def dependency():
            with factory() as db:
                yield db
        app.dependency_overrides[get_db] = dependency
        app.include_router(messages_router)
        app.include_router(agents_router)
        app.include_router(reports_router)
        with TestClient(app) as client:
            response = client.get("/api/messages/daily?trade_date=20261110&ensure_seed=false")
            assert response.status_code == 200
            assert response.json()["opportunities"][0]["id"] == "legacy-opportunity"
            response = client.post("/api/industry-reports/generate", json={"trade_date": "20261110", "use_llm": False, "refresh_seeds": True})
            assert response.status_code == 200, response.text
        run_alembic(url, "downgrade", "1f4b0c7d9e2a")
        with engine.connect() as conn:
            assert conn.exec_driver_sql("SELECT id FROM message_opportunity").scalar_one() == "legacy-opportunity"


def test_sqlite_to_postgres_preserves_composite_keys_json_and_datetime(tmp_path):
    source_url = "sqlite:///" + str(tmp_path / "source.db")
    source = create_engine(source_url)
    Base.metadata.create_all(source)
    with source.begin() as conn:
        conn.execute(StockBasic.__table__.insert(), {"ts_code": "000001.SZ", "name": "fixture", "list_date": "19910403", "list_status": "L"})
        conn.execute(DailyQuote.__table__.insert(), {"ts_code": "000001.SZ", "trade_date": "20261110", "close": 10.25})
        conn.execute(MessageSourceItem.__table__.insert(), {"id": "source-item", "trade_date": "20261110", "channel": "import",
                     "content": "source fixture", "dedupe_key": "fixture-key", "captured_at": datetime(2026, 11, 10, 8),
                     "raw_payload": {"unicode": "证据", "nested": [1, None, {"supported": True}]}})
    with scratch_postgres() as (url, engine):
        run_alembic(url, "upgrade", "head")
        rows = migrate(sqlite_url=source_url, target_url=url, create_schema=False, batch_size=1)
        assert all(row["status"] in ("ok", "empty") for row in rows)
        with engine.connect() as conn:
            assert conn.execute(select(DailyQuote.__table__.c.close)).scalar_one() == 10.25
            row = conn.execute(select(MessageSourceItem.__table__)).mappings().one()
            assert row["raw_payload"]["unicode"] == "证据"
            assert row["raw_payload"]["nested"][2]["supported"] is True
            assert row["captured_at"] == datetime(2026, 11, 10, 8)
        with pytest.raises(ValueError, match="target must be empty"):
            migrate(sqlite_url=source_url, target_url=url, create_schema=False)
    source.dispose()


def test_postgres_deployment_restore_removes_new_migration_objects_atomically(tmp_path):
    from app.services.quote_repair_io import create_backup
    from scripts.deployment_database import restore_database
    from sqlalchemy import inspect
    with scratch_postgres() as (url, engine):
        run_alembic(url, "upgrade", "1f4b0c7d9e2a")
        seed_legacy_opportunity(engine)
        manifest = create_backup(url, str(tmp_path), str(tmp_path / "backups"))
        run_alembic(url, "upgrade", "head")
        assert "message_evidence" in inspect(engine).get_table_names()
        assert restore_database(url, manifest)["status"] == "restored"
        assert "message_evidence" not in inspect(engine).get_table_names()
        assert "background_task" not in inspect(engine).get_table_names()
        with engine.connect() as conn:
            assert conn.exec_driver_sql("SELECT id FROM message_opportunity").scalar_one() == "legacy-opportunity"
            assert conn.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one() == "1f4b0c7d9e2a"


def test_postgres_restore_error_rolls_back_schema_removal(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from sqlalchemy import inspect
    from app.services.quote_repair_io import create_backup
    from scripts import deployment_database as deployment
    with scratch_postgres() as (url, engine):
        run_alembic(url, "upgrade", "1f4b0c7d9e2a")
        seed_legacy_opportunity(engine)
        manifest = create_backup(url, str(tmp_path), str(tmp_path / "backups"))
        run_alembic(url, "upgrade", "head")
        original = deployment.subprocess.run
        def corrupt_restore(command, **kwargs):
            if command[:3] == ["pg_restore", "--file", "-"]:
                kwargs["stdout"].write(b"SELECT 1 / 0;\n")
                return SimpleNamespace(returncode=0)
            return original(command, **kwargs)
        monkeypatch.setattr(deployment.subprocess, "run", corrupt_restore)
        with pytest.raises(ValueError, match="transaction rolled back"):
            deployment.restore_database(url, manifest)
        assert "message_evidence" in inspect(engine).get_table_names()
        with engine.connect() as conn:
            assert conn.exec_driver_sql("SELECT id FROM message_opportunity").scalar_one() == "legacy-opportunity"
            assert conn.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one() == "3b2f8da1c422"
