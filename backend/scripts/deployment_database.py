"""Deployment backup/restore/check commands; never called by web startup."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy.engine import make_url
from app.services.market_data_quality_service import readonly_connection
from app.services.quote_repair_io import create_backup, database_identity, validate_backup, quote_fingerprint, _postgres_libpq_env
from app.services.readiness_service import check_database_ready
from scripts.audit_market_data_quality import configured_database
from scripts.repair_daily_quotes import write_json


def restore_database(url, manifest):
    with readonly_connection(url, ROOT) as (conn, _):
        identity = database_identity(conn)
        validated = validate_backup(manifest, identity)
        if identity["dialect"] == "postgresql":
            schemas = set(conn.exec_driver_sql("SELECT nspname FROM pg_namespace WHERE left(nspname, 3) <> 'pg_' AND nspname <> 'information_schema'").scalars())
            if schemas != {"public"} or identity.get("schema") != "public":
                raise ValueError("Automatic rollback requires a dedicated application database with only the public schema")
    if identity["dialect"] == "sqlite":
        path = Path(validated["path"])
        # sqlite backup handles WAL correctly. Caller must stop all app writers.
        with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as source:
            with sqlite3.connect(identity["database"]) as target:
                source.backup(target)
                if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValueError("restored SQLite integrity check failed")
    else:
        parsed = make_url(url)
        # --clean alone cannot remove objects introduced after this backup; their
        # FKs may even prevent dropping archived tables. Rebuild the dedicated
        # schema AND restore inside one transaction, so any restore error rolls
        # back the schema removal as well. The SQL artifact is private/temporary.
        with tempfile.NamedTemporaryFile(prefix="newquant-restore-", suffix=".sql", mode="w+b") as script:
            script.write(b"DROP SCHEMA IF EXISTS public CASCADE;\nCREATE SCHEMA public;\n")
            script.flush()
            generated = subprocess.run(["pg_restore", "--file", "-", "--clean", "--if-exists", "--no-owner", "--no-privileges", validated["path"]],
                                       stdout=script, stderr=subprocess.PIPE, timeout=600)
            if generated.returncode:
                raise ValueError("PostgreSQL restore SQL generation failed")
            script.flush()
            result = subprocess.run(["psql", "--no-psqlrc", "--dbname", parsed.database, "--set", "ON_ERROR_STOP=1",
                                     "--single-transaction", "--file", script.name],
                                    env=_postgres_libpq_env(parsed), capture_output=True, timeout=600)
            if result.returncode:
                raise ValueError("PostgreSQL restore failed; schema/data transaction rolled back")
    with readonly_connection(url, ROOT) as (conn, _):
        fingerprint = quote_fingerprint(conn)
        if any(fingerprint[key] != manifest[key] for key in ("daily_quote_row_count", "daily_quote_sha256")):
            raise ValueError("Restored daily-quote fingerprint differs from backup")
    return {"status": "restored", "backup_id": manifest["id"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    backup = sub.add_parser("backup")
    backup.add_argument("--directory", type=Path, required=True)
    restore = sub.add_parser("restore")
    restore.add_argument("--manifest", type=Path, required=True)
    sub.add_parser("check")
    args = parser.parse_args(argv)
    url, _ = configured_database(ROOT)
    try:
        if args.command == "backup":
            manifest = create_backup(url, str(ROOT), str(args.directory))
            path = Path(manifest["path"] + ".manifest.json")
            write_json(path, manifest)
            print(str(path))
        elif args.command == "restore":
            result = restore_database(url, json.loads(args.manifest.read_text()))
            print(json.dumps(result))
        else:
            with readonly_connection(url, ROOT) as (conn, _):
                print(json.dumps(check_database_ready(conn)))
        return 0
    except Exception as exc:
        print(f"Deployment database operation failed ({type(exc).__name__}); no credentials are logged.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
