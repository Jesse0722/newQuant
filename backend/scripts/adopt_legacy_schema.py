"""Validate a pre-Alembic schema before stamping it; refuse unknown schemas."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sqlalchemy import create_engine, inspect
from scripts.audit_market_data_quality import configured_database

BASELINE = "c4647a9160ea"
AUDIT = "1f4b0c7d9e2a"


def _run(url, *args):
    result = subprocess.run([sys.executable, "-m", "alembic", "-c", str(ROOT.parent / "alembic.ini"), *args],
                            cwd=ROOT.parent, env={**os.environ, "DATABASE_URL": url,
                                "AUTO_INIT_DB": "false", "AUTO_START_SCHEDULER": "false"},
                            capture_output=True, timeout=60)
    if result.returncode:
        raise ValueError("Alembic legacy-schema operation failed")


def adopt_legacy_schema(url, *, dry_run=False):
    target = create_engine(url)
    try:
        actual = inspect(target)
        tables = set(actual.get_table_names())
        audit_tables = {"daily_quote_repair_batch", "daily_quote_repair_audit"}
        current = None
        if "alembic_version" in tables:
            with target.connect() as conn:
                current = conn.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one_or_none()
                # The explicit SQLite repair bootstrap created audit tables while
                # leaving an already-versioned MVP at baseline. Validate those
                # exact structures before advancing their version stamp.
                if current and not (current == BASELINE and bool(tables & audit_tables)):
                    return "already_versioned"
        if not tables - {"alembic_version"}:
            return "empty"
        if bool(tables & audit_tables) and not audit_tables <= tables:
            raise ValueError("Incomplete existing quote-repair audit schema")
        revision = AUDIT if audit_tables <= tables else BASELINE
        with tempfile.TemporaryDirectory(prefix="newquant-baseline-") as folder:
            reference_url = "sqlite:///" + str(Path(folder) / "baseline.db")
            _run(reference_url, "upgrade", revision)
            reference = create_engine(reference_url)
            try:
                expected = inspect(reference)
                # A recorded baseline is not re-adopted. Only validate the extra
                # audit structures whose version is about to be advanced. This
                # avoids rewriting unrelated legacy SQLite constraints here.
                names = audit_tables if current == BASELINE else set(expected.get_table_names()) - {"alembic_version"}
                for name in names:
                    if name not in tables:
                        raise ValueError("Legacy schema missing baseline table: " + name)
                    expected_columns = {c["name"]: c for c in expected.get_columns(name)}
                    actual_columns = {c["name"]: c for c in actual.get_columns(name)}
                    for field, column in expected_columns.items():
                        if field not in actual_columns or column["type"]._type_affinity != actual_columns[field]["type"]._type_affinity:
                            raise ValueError("Legacy schema column mismatch: " + name + "." + field)
                        if not column["nullable"] and actual_columns[field]["nullable"]:
                            raise ValueError("Legacy required-column mismatch: " + name + "." + field)
                    if expected.get_pk_constraint(name)["constrained_columns"] != actual.get_pk_constraint(name)["constrained_columns"]:
                        raise ValueError("Legacy primary-key mismatch: " + name)
                    def unique_keys(schema):
                        keys = [item["column_names"] for item in schema.get_unique_constraints(name)]
                        keys.extend(item["column_names"] for item in schema.get_indexes(name) if item.get("unique"))
                        keys.append(schema.get_pk_constraint(name)["constrained_columns"])
                        return {frozenset(key) for key in keys if key}
                    if not unique_keys(expected) <= unique_keys(actual):
                        raise ValueError("Legacy unique-constraint mismatch: " + name)
                    def foreign_keys(schema):
                        return {(tuple(item["constrained_columns"]), item["referred_table"], tuple(item["referred_columns"]),
                                 (item.get("options", {}).get("ondelete") or "NO ACTION").upper())
                                for item in schema.get_foreign_keys(name)}
                    if not foreign_keys(expected) <= foreign_keys(actual):
                        raise ValueError("Legacy foreign-key mismatch: " + name)
            finally:
                reference.dispose()
        if dry_run:
            return "would_stamp:" + revision
        _run(url, "stamp", revision)
        return revision
    finally:
        target.dispose()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Validate only; do not stamp the target")
    args = parser.parse_args()
    try:
        print(adopt_legacy_schema(configured_database(ROOT)[0], dry_run=args.dry_run))
    except Exception as exc:
        print(f"Legacy schema validation failed ({type(exc).__name__}); restore/inspect before migrating.", file=sys.stderr)
        raise SystemExit(1)
