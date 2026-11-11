from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

from sqlalchemy import create_engine, inspect
import pytest

from app.models.stock import DailyQuote
from app.services.quote_repair_io import QuoteRepairIOError

from scripts.migrate_daily_quote_repair_audit import migrate


TABLES = {"daily_quote_repair_batch", "daily_quote_repair_audit"}
BASELINE_REVISION = "c4647a9160ea"


def _sqlite_url(path: Path) -> str:
    return f"sqlite:///{path}"


def test_sqlite_compatibility_migration_is_idempotent(tmp_path: Path):
    database_url = _sqlite_url(tmp_path / "compatibility.db")
    bootstrap = create_engine(database_url)
    DailyQuote.__table__.create(bootstrap)
    bootstrap.dispose()

    first = migrate(database_url)
    second = migrate(database_url)

    assert set(first["created"]) == TABLES
    assert second == {"created": [], "existing": sorted(TABLES)}

    engine = create_engine(database_url)
    try:
        schema = inspect(engine)
        assert TABLES.issubset(schema.get_table_names())
        audit_columns = {column["name"]: column for column in schema.get_columns("daily_quote_repair_audit")}
        assert audit_columns["old_values"]["nullable"]
        assert not audit_columns["new_values"]["nullable"]
        assert not audit_columns["source_json"]["nullable"]
        assert {index["name"] for index in schema.get_indexes("daily_quote_repair_audit")} == {
            "ix_daily_quote_repair_audit_batch_sequence",
            "ix_daily_quote_repair_audit_quote",
        }
        assert {tuple(item["column_names"]) for item in schema.get_unique_constraints("daily_quote_repair_audit")} == {
            ("batch_id", "ts_code", "trade_date"),
        }
        foreign_keys = schema.get_foreign_keys("daily_quote_repair_audit")
        assert foreign_keys[0]["referred_table"] == "daily_quote_repair_batch"
        assert foreign_keys[0]["options"].get("ondelete") == "RESTRICT"
    finally:
        engine.dispose()


def test_sqlite_compatibility_migration_never_creates_missing_database(tmp_path: Path):
    path = tmp_path / "missing.db"
    with pytest.raises(QuoteRepairIOError):
        migrate(_sqlite_url(path))
    assert not path.exists()


def _run_alembic(root: Path, database_url: str, *args: str) -> None:
    env = os.environ.copy()
    env["DATABASE_URL"] = database_url
    subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(root / "alembic.ini"), *args],
        cwd=root,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )


def test_alembic_upgrade_is_repeatable_and_downgrade_removes_only_repair_tables(tmp_path: Path):
    root = Path(__file__).resolve().parents[2]
    database_url = _sqlite_url(tmp_path / "alembic.db")

    _run_alembic(root, database_url, "upgrade", "head")
    _run_alembic(root, database_url, "upgrade", "head")

    engine = create_engine(database_url)
    try:
        assert TABLES.issubset(inspect(engine).get_table_names())
    finally:
        engine.dispose()

    _run_alembic(root, database_url, "downgrade", BASELINE_REVISION)

    engine = create_engine(database_url)
    try:
        tables = set(inspect(engine).get_table_names())
        assert not TABLES & tables
        assert {"daily_quote", "stock_basic", "alembic_version"}.issubset(tables)
    finally:
        engine.dispose()
