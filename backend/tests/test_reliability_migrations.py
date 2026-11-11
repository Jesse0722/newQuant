from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import subprocess
import sys

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import MetaData, Table, create_engine, inspect, select

from app.database import Base
import app.models  # noqa: F401

ROOT = Path(__file__).resolve().parents[2]


def run_alembic(url, *args):
    env = {**os.environ, "DATABASE_URL": url, "AUTO_INIT_DB": "false",
           "AUTO_START_SCHEDULER": "false", "SCHEDULER_ENABLED": "false"}
    result = subprocess.run([sys.executable, "-m", "alembic", "-c", str(ROOT / "alembic.ini"), *args],
                            cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, "Alembic operation failed: " + result.stderr[-2000:]


def assert_schema_matches(engine):
    with engine.connect() as conn:
        differences = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert differences == [], differences


def seed_legacy_opportunity(engine):
    table = Table("message_opportunity", MetaData(), autoload_with=engine)
    row = {"id": "legacy-opportunity", "trade_date": "20261110", "theme": "fixture",
           "opportunity_score": 50, "heat_score": 50, "credibility_score": 50,
           "risk_score": 40, "action_suggestion": "watch", "status": "active",
           "created_at": datetime(2026, 11, 10)}
    with engine.begin() as conn:
        conn.execute(table.insert(), row)


def test_upgrade_preserves_legacy_data_and_matches_orm(tmp_path):
    url = "sqlite:///" + str(tmp_path / "upgrade.db")
    run_alembic(url, "upgrade", "1f4b0c7d9e2a")
    engine = create_engine(url)
    seed_legacy_opportunity(engine)
    run_alembic(url, "upgrade", "head")
    run_alembic(url, "upgrade", "head")
    assert_schema_matches(engine)
    with engine.connect() as conn:
        row = conn.execute(select(Base.metadata.tables["message_opportunity"])).mappings().one()
        assert row["id"] == "legacy-opportunity" and row["review_status"] == "reviewed"
        assert row["evidence_score"] == row["mapping_confidence"] == 0
    run_alembic(url, "downgrade", "1f4b0c7d9e2a")
    assert "message_evidence" not in inspect(engine).get_table_names()
    with engine.connect() as conn:
        assert conn.exec_driver_sql("SELECT id FROM message_opportunity").scalar_one() == "legacy-opportunity"
    run_alembic(url, "upgrade", "head")
    assert_schema_matches(engine)
    engine.dispose()


def test_sqlite_mvp_compatibility_adds_audit_columns_idempotently(tmp_path, monkeypatch):
    from app import database
    from scripts.migrate_reliability_fields import migrate
    engine = create_engine("sqlite:///" + str(tmp_path / "mvp.db"))
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE industry_daily_report (id TEXT PRIMARY KEY, title TEXT)")
        conn.exec_driver_sql("INSERT INTO industry_daily_report VALUES ('old', 'preserved')")
    monkeypatch.setattr(database, "engine", engine)
    migrate()
    migrate()
    assert {"input_snapshot", "raw_response"} <= {c["name"] for c in inspect(engine).get_columns("industry_daily_report")}
    with engine.connect() as conn:
        assert conn.exec_driver_sql("SELECT title FROM industry_daily_report").scalar_one() == "preserved"
    engine.dispose()
