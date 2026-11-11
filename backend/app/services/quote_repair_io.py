"""Explicit, fail-closed database I/O helpers for daily-quote repair.

This module deliberately does not import :mod:`app.database`.  Repair callers
must pass the database URL explicitly, and SQLite targets must already exist.
"""

from __future__ import annotations

import getpass
import hashlib
import hmac
import json
import os
import sqlite3
import subprocess
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Iterator, Mapping, Optional
from urllib.parse import quote

from sqlalchemy import create_engine
from sqlalchemy.engine import Connection, URL, make_url
from sqlalchemy.pool import NullPool


SQLITE_BACKUP_FORMAT = "sqlite"
POSTGRES_BACKUP_FORMAT = "postgresql-custom"
POSTGRES_STATEMENT_TIMEOUT_MS = 30_000
POSTGRES_LOCK_TIMEOUT_MS = 5_000
POSTGRES_DUMP_TIMEOUT_SECONDS = 300
POSTGRES_VALIDATE_TIMEOUT_SECONDS = 30
POSTGRES_DEFAULT_PORT = 5432
POSTGRES_SSL_QUERY_ENV = {
    "sslmode": "PGSSLMODE",
    "sslcert": "PGSSLCERT",
    "sslkey": "PGSSLKEY",
    "sslrootcert": "PGSSLROOTCERT",
    "sslcrl": "PGSSLCRL",
}


class QuoteRepairIOError(RuntimeError):
    """Base class for safe repair I/O failures."""


class UnsupportedDatabaseError(QuoteRepairIOError):
    """The explicit database URL uses an unsupported backend."""


class UnsafeDatabaseTargetError(QuoteRepairIOError):
    """The requested target could be created or resolved ambiguously."""


class BackupError(QuoteRepairIOError):
    """A backup could not be created or independently checked."""


class BackupValidationError(QuoteRepairIOError):
    """A backup manifest or artifact failed validation."""


def _backend(url: URL) -> str:
    name = url.get_backend_name()
    if name == "sqlite":
        return "sqlite"
    if name in {"postgresql", "postgres"}:
        return "postgresql"
    raise UnsupportedDatabaseError("unsupported database backend")


def _sqlite_path(database_url: str, app_cwd: str) -> Path:
    try:
        url = make_url(database_url)
    except Exception:
        raise UnsafeDatabaseTargetError("invalid database URL") from None
    if _backend(url) != "sqlite":
        raise UnsupportedDatabaseError("SQLite database URL required")
    if url.query:
        raise UnsafeDatabaseTargetError("SQLite URL query parameters are not allowed")
    database = str(url.database or "").strip()
    if not database or database == ":memory:" or database.startswith("file:"):
        raise UnsafeDatabaseTargetError("SQLite target must be an existing file")
    path = Path(database).expanduser()
    if not path.is_absolute():
        path = Path(app_cwd).expanduser() / path
    try:
        path = path.resolve(strict=True)
    except (FileNotFoundError, OSError) as exc:
        raise UnsafeDatabaseTargetError("SQLite target file does not exist") from exc
    if not path.is_file():
        raise UnsafeDatabaseTargetError("SQLite target is not a regular file")
    return path


def _sqlite_engine(path: Path):
    uri = f"file:{quote(str(path), safe='/')}?mode=rw"
    return create_engine(
        URL.create("sqlite+pysqlite", database=str(path)),
        poolclass=NullPool,
        future=True,
        creator=lambda: sqlite3.connect(uri, uri=True),
    )


def _postgres_url(database_url: str) -> URL:
    """Normalize one explicit PostgreSQL target for SQLAlchemy and libpq."""

    try:
        url = make_url(database_url)
    except Exception:
        raise UnsafeDatabaseTargetError("invalid PostgreSQL database URL") from None
    if _backend(url) != "postgresql":
        raise UnsupportedDatabaseError("PostgreSQL database URL required")
    unsupported = set(url.query) - set(POSTGRES_SSL_QUERY_ENV)
    if unsupported:
        raise UnsafeDatabaseTargetError("PostgreSQL URL contains unsupported query parameters")

    host = str(url.host or "").strip()
    database = str(url.database or "").strip()
    if not host or not database:
        raise UnsafeDatabaseTargetError("PostgreSQL URL requires explicit host and database")
    username = str(url.username or "").strip()
    if not username:
        try:
            username = str(getpass.getuser() or "").strip()
        except Exception:
            username = ""
    if not username:
        raise UnsafeDatabaseTargetError("PostgreSQL user could not be determined")
    try:
        port = int(url.port or POSTGRES_DEFAULT_PORT)
    except (TypeError, ValueError):
        raise UnsafeDatabaseTargetError("PostgreSQL port is invalid") from None
    if not 1 <= port <= 65535:
        raise UnsafeDatabaseTargetError("PostgreSQL port is invalid")
    query: Dict[str, str] = {}
    for key, value in url.query.items():
        if not isinstance(value, str) or not value:
            raise UnsafeDatabaseTargetError("PostgreSQL SSL query parameter is invalid")
        query[key] = value
    return url.set(
        host=host,
        database=database,
        username=username,
        port=port,
        query=query,
    )


def _execute_rows(conn: Any, sql: str):
    if hasattr(conn, "exec_driver_sql"):
        return conn.exec_driver_sql(sql).fetchall()
    return conn.execute(sql).fetchall()


def database_identity(conn: Any) -> Dict[str, Any]:
    """Return a credential-free identity for an already-open DB connection."""

    dialect = getattr(getattr(conn, "dialect", None), "name", None)
    if dialect is None and isinstance(conn, sqlite3.Connection):
        dialect = "sqlite"

    if dialect == "sqlite":
        rows = _execute_rows(conn, "PRAGMA database_list")
        main_path = next((str(row[2]) for row in rows if str(row[1]) == "main"), "")
        if not main_path or main_path == ":memory:":
            raise UnsafeDatabaseTargetError("SQLite identity requires a file-backed database")
        try:
            path = Path(main_path).expanduser().resolve(strict=True)
        except (FileNotFoundError, OSError) as exc:
            raise UnsafeDatabaseTargetError("SQLite database identity is not an existing file") from exc
        return {"dialect": "sqlite", "database": str(path)}

    if dialect in {"postgresql", "postgres"}:
        sql = """
            SELECT current_database() AS database,
                   current_schema() AS schema,
                   inet_server_addr()::text AS host,
                   inet_server_port() AS port
        """
        if not hasattr(conn, "exec_driver_sql"):
            raise UnsupportedDatabaseError("unsupported PostgreSQL connection object")
        row = conn.exec_driver_sql(sql).mappings().one()
        return {
            "dialect": "postgresql",
            "database": str(row["database"]),
            "schema": str(row["schema"]) if row["schema"] is not None else None,
            "host": str(row["host"]) if row["host"] is not None else None,
            "port": int(row["port"]) if row["port"] is not None else None,
        }

    raise UnsupportedDatabaseError("unsupported database connection")


def _fingerprint_value(value: Any) -> Any:
    if isinstance(value, float):
        if value != value:
            return {"__float__": "nan"}
        if value == float("inf"):
            return {"__float__": "+inf"}
        if value == float("-inf"):
            return {"__float__": "-inf"}
        if value == 0:
            return 0.0
        return value
    if isinstance(value, Decimal):
        if value.is_nan():
            return {"__float__": "nan"}
        if value.is_infinite():
            return {"__float__": "+inf" if value > 0 else "-inf"}
        if value == 0:
            return 0.0
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, bytes):
        return {"__bytes__": value.hex()}
    return value


def quote_fingerprint(conn: Any) -> Dict[str, Any]:
    """Stream a deterministic content hash of the complete daily_quote table."""

    sql = "SELECT * FROM daily_quote ORDER BY ts_code, trade_date"
    if hasattr(conn, "exec_driver_sql"):
        result = conn.exec_driver_sql(sql, execution_options={"stream_results": True})
        columns = [str(value) for value in result.keys()]
        rows = result
    else:
        rows = conn.execute(sql)
        columns = [str(item[0]) for item in (rows.description or [])]
    if not columns or "ts_code" not in columns or "trade_date" not in columns:
        raise BackupValidationError("daily_quote table is missing required columns")

    digest = hashlib.sha256()
    header = json.dumps(columns, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    digest.update(header.encode("utf-8"))
    digest.update(b"\n")
    count = 0
    try:
        for row in rows:
            values = [_fingerprint_value(value) for value in tuple(row)]
            body = json.dumps(values, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
            digest.update(body.encode("utf-8"))
            digest.update(b"\n")
            count += 1
    except (TypeError, ValueError, OverflowError) as exc:
        raise BackupValidationError("daily_quote contains an unsupported value") from exc
    finally:
        close = getattr(rows, "close", None)
        if callable(close):
            close()
    return {"daily_quote_row_count": count, "daily_quote_sha256": digest.hexdigest()}


@contextmanager
def writer_connection(database_url: str, app_cwd: str) -> Iterator[Connection]:
    """Yield one independent, explicit write transaction.

    SQLite obtains the write reservation before yielding.  PostgreSQL callers
    remain responsible for locking rows in a deterministic order.
    """

    try:
        parsed = make_url(database_url)
    except Exception:
        raise UnsafeDatabaseTargetError("invalid database URL") from None
    backend = _backend(parsed)

    if backend == "sqlite":
        path = _sqlite_path(database_url, app_cwd)
        engine = _sqlite_engine(path)
        conn: Optional[Connection] = None
        try:
            try:
                conn = engine.connect()
            except Exception:
                raise UnsafeDatabaseTargetError("SQLite target file is no longer available") from None
            conn.exec_driver_sql("PRAGMA foreign_keys = ON")
            if conn.in_transaction():
                conn.commit()
            conn.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                yield conn
            except BaseException:
                conn.rollback()
                raise
            else:
                conn.commit()
        finally:
            if conn is not None:
                conn.close()
            engine.dispose()
        return

    normalized = _postgres_url(database_url)
    try:
        engine = create_engine(normalized, poolclass=NullPool, future=True)
    except Exception:
        raise QuoteRepairIOError("PostgreSQL writer connection could not be configured") from None
    conn = None
    transaction = None
    try:
        try:
            conn = engine.connect().execution_options(isolation_level="READ COMMITTED")
            transaction = conn.begin()
            conn.exec_driver_sql(f"SET LOCAL statement_timeout = {POSTGRES_STATEMENT_TIMEOUT_MS}")
            conn.exec_driver_sql(f"SET LOCAL lock_timeout = {POSTGRES_LOCK_TIMEOUT_MS}")
        except Exception:
            if transaction is not None and transaction.is_active:
                transaction.rollback()
            raise QuoteRepairIOError("PostgreSQL writer transaction could not be started") from None
        try:
            yield conn
        except BaseException:
            transaction.rollback()
            raise
        else:
            transaction.commit()
    finally:
        if conn is not None:
            conn.close()
        engine.dispose()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _created_at() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _reserve_backup_path(backup_dir: str, suffix: str) -> tuple[str, Path]:
    directory = Path(backup_dir).expanduser().resolve(strict=False)
    directory.mkdir(parents=True, exist_ok=True)
    if not directory.is_dir():
        raise BackupError("backup destination is not a directory")
    for _ in range(10):
        backup_id = str(uuid.uuid4())
        path = directory / f"{backup_id}{suffix}"
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            continue
        os.close(fd)
        return backup_id, path
    raise BackupError("could not reserve a unique backup path")


def _sqlite_readonly_uri(path: Path, *, immutable: bool = False) -> str:
    suffix = "&immutable=1" if immutable else ""
    return f"file:{quote(str(path), safe='/')}?mode=ro{suffix}"


def _inspect_sqlite(path: Path) -> Dict[str, Any]:
    # A completed backup is immutable.  This also permits validation of a
    # WAL-mode source backup without creating -wal/-shm files beside it.
    conn = sqlite3.connect(_sqlite_readonly_uri(path, immutable=True), uri=True)
    try:
        integrity_rows = conn.execute("PRAGMA integrity_check").fetchall()
        integrity = [str(row[0]) for row in integrity_rows]
        if integrity != ["ok"]:
            raise BackupValidationError("SQLite backup integrity check failed")
        table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'daily_quote'"
        ).fetchone()
        if not table:
            raise BackupValidationError("SQLite backup is missing daily_quote")
        return {"integrity_check": "ok", **quote_fingerprint(conn)}
    except sqlite3.DatabaseError as exc:
        raise BackupValidationError("SQLite backup is malformed") from exc
    finally:
        conn.close()


def _postgres_libpq_env(url: URL) -> Dict[str, str]:
    env = dict(os.environ)
    # Ambient libpq variables must not silently redirect an explicit URL to a
    # different server, database, user or service definition.
    for key in (
        "PGHOST",
        "PGHOSTADDR",
        "PGPORT",
        "PGDATABASE",
        "PGUSER",
        "PGPASSWORD",
        "PGPASSFILE",
        "PGSERVICE",
        "PGSERVICEFILE",
        "PGOPTIONS",
        "PGAPPNAME",
        "PGCONNECT_TIMEOUT",
        "PGCLIENTENCODING",
        "PGSSLMODE",
        "PGREQUIRESSL",
        "PGSSLCOMPRESSION",
        "PGSSLCERT",
        "PGSSLKEY",
        "PGSSLROOTCERT",
        "PGSSLCRL",
        "PGSSLCRLDIR",
        "PGSSLSNI",
        "PGCHANNELBINDING",
        "PGGSSENCMODE",
        "PGKRBSRVNAME",
        "PGTARGETSESSIONATTRS",
        "PGLOADBALANCEHOSTS",
    ):
        env.pop(key, None)
    values = {
        "PGHOST": url.host,
        "PGPORT": str(url.port) if url.port is not None else None,
        "PGUSER": url.username,
        "PGPASSWORD": url.password,
        "PGDATABASE": url.database,
    }
    for key, value in values.items():
        if value is not None:
            env[key] = str(value)
    for query_key, env_key in POSTGRES_SSL_QUERY_ENV.items():
        value = url.query.get(query_key)
        if value is not None:
            env[env_key] = str(value)
    return env


def _postgres_identity(database_url: str) -> Dict[str, Any]:
    url = _postgres_url(database_url)
    try:
        engine = create_engine(url, poolclass=NullPool, future=True)
    except Exception:
        raise BackupError("could not configure PostgreSQL identity connection") from None
    conn = None
    try:
        conn = engine.connect()
        return database_identity(conn)
    except QuoteRepairIOError:
        raise
    except Exception:
        raise BackupError("could not read PostgreSQL database identity") from None
    finally:
        if conn is not None:
            conn.close()
        engine.dispose()


def _run_pg_restore_list(path: Path) -> None:
    try:
        result = subprocess.run(
            ["pg_restore", "--list", str(path)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=POSTGRES_VALIDATE_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise BackupValidationError("PostgreSQL backup validation could not run") from exc
    if result.returncode != 0:
        raise BackupValidationError("PostgreSQL custom backup is invalid")


def create_backup(database_url: str, app_cwd: str, backup_dir: str) -> Dict[str, Any]:
    """Create and verify an immutable backup artifact for the explicit DB URL."""

    try:
        parsed = make_url(database_url)
    except Exception:
        raise BackupError("invalid database URL") from None
    backend = _backend(parsed)

    if backend == "sqlite":
        source_path = _sqlite_path(database_url, app_cwd)
        backup_id, destination = _reserve_backup_path(backup_dir, ".db")
        try:
            source = sqlite3.connect(_sqlite_readonly_uri(source_path), uri=True)
            target = sqlite3.connect(str(destination))
            try:
                source.backup(target)
            finally:
                target.close()
                source.close()
            details = _inspect_sqlite(destination)
            return {
                "id": backup_id,
                "path": str(destination),
                "sha256": _sha256(destination),
                "database_identity": {"dialect": "sqlite", "database": str(source_path)},
                "created_at": _created_at(),
                "format": SQLITE_BACKUP_FORMAT,
                **details,
            }
        except Exception as exc:
            destination.unlink(missing_ok=True)
            if isinstance(exc, QuoteRepairIOError):
                raise
            raise BackupError("SQLite backup failed") from exc

    normalized = _postgres_url(database_url)
    backup_id, destination = _reserve_backup_path(backup_dir, ".dump")
    env = _postgres_libpq_env(normalized)
    engine = None
    conn = None
    transaction = None
    try:
        try:
            engine = create_engine(normalized, poolclass=NullPool, future=True)
            conn = engine.connect().execution_options(isolation_level="REPEATABLE READ")
            transaction = conn.begin()
            conn.exec_driver_sql("SET TRANSACTION READ ONLY")
            conn.exec_driver_sql(f"SET LOCAL statement_timeout = {POSTGRES_DUMP_TIMEOUT_SECONDS * 1000}")
            conn.exec_driver_sql(f"SET LOCAL lock_timeout = {POSTGRES_LOCK_TIMEOUT_MS}")
            identity = database_identity(conn)
            fingerprint = quote_fingerprint(conn)
            snapshot_id = str(conn.exec_driver_sql("SELECT pg_export_snapshot()").scalar_one())
        except QuoteRepairIOError:
            raise
        except Exception:
            raise BackupError("could not export a PostgreSQL backup snapshot") from None
        try:
            result = subprocess.run(
                [
                    "pg_dump",
                    "--format=custom",
                    "--snapshot",
                    snapshot_id,
                    "--file",
                    str(destination),
                ],
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=POSTGRES_DUMP_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise BackupError("PostgreSQL backup command failed") from exc
        if result.returncode != 0:
            raise BackupError("PostgreSQL backup command failed")
        # pg_dump has consumed the exported snapshot.  Release the exporter
        # before the independent archive validation step.
        transaction.rollback()
        transaction = None
        conn.close()
        conn = None
        engine.dispose()
        engine = None
        _run_pg_restore_list(destination)
        return {
            "id": backup_id,
            "path": str(destination),
            "sha256": _sha256(destination),
            "database_identity": identity,
            "created_at": _created_at(),
            "format": POSTGRES_BACKUP_FORMAT,
            **fingerprint,
        }
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    finally:
        if transaction is not None and transaction.is_active:
            transaction.rollback()
        if conn is not None:
            conn.close()
        if engine is not None:
            engine.dispose()


def _normalized_identity(value: Any) -> Dict[str, Any]:
    if not isinstance(value, Mapping):
        raise BackupValidationError("database identity is malformed")
    dialect = value.get("dialect")
    if dialect == "sqlite":
        if set(value) != {"dialect", "database"} or not isinstance(value.get("database"), str):
            raise BackupValidationError("SQLite database identity is malformed")
        return {
            "dialect": "sqlite",
            "database": str(Path(value["database"]).expanduser().resolve(strict=False)),
        }
    if dialect == "postgresql":
        allowed = {"dialect", "database", "schema", "host", "port"}
        if set(value) != allowed:
            raise BackupValidationError("PostgreSQL database identity is malformed")
        if not isinstance(value.get("database"), str):
            raise BackupValidationError("PostgreSQL database identity is malformed")
        schema = value.get("schema")
        if schema is not None and not isinstance(schema, str):
            raise BackupValidationError("PostgreSQL database identity is malformed")
        host = value.get("host")
        port = value.get("port")
        if host is not None and not isinstance(host, str):
            raise BackupValidationError("PostgreSQL database identity is malformed")
        if port is not None and (not isinstance(port, int) or isinstance(port, bool)):
            raise BackupValidationError("PostgreSQL database identity is malformed")
        return {key: value[key] for key in ("dialect", "database", "schema", "host", "port")}
    raise BackupValidationError("database identity backend is unsupported")


def validate_backup(manifest: Mapping[str, Any], identity: Mapping[str, Any]) -> Dict[str, Any]:
    """Validate artifact hash, format, source separation and target identity."""

    if not isinstance(manifest, Mapping):
        raise BackupValidationError("backup manifest is malformed")
    required = {
        "id",
        "path",
        "sha256",
        "database_identity",
        "created_at",
        "format",
        "daily_quote_row_count",
        "daily_quote_sha256",
    }
    if not required.issubset(manifest):
        raise BackupValidationError("backup manifest is incomplete")
    try:
        parsed_id = uuid.UUID(str(manifest["id"]))
    except (ValueError, TypeError, AttributeError) as exc:
        raise BackupValidationError("backup manifest id is malformed") from exc
    if str(parsed_id) != str(manifest["id"]):
        raise BackupValidationError("backup manifest id is malformed")
    if not isinstance(manifest["created_at"], str):
        raise BackupValidationError("backup manifest timestamp is malformed")
    try:
        datetime.fromisoformat(manifest["created_at"].replace("Z", "+00:00"))
    except ValueError as exc:
        raise BackupValidationError("backup manifest timestamp is malformed") from exc

    expected_identity = _normalized_identity(manifest["database_identity"])
    actual_identity = _normalized_identity(identity)
    if expected_identity != actual_identity:
        raise BackupValidationError("backup database identity does not match target")

    raw_path = manifest["path"]
    if not isinstance(raw_path, str) or not raw_path:
        raise BackupValidationError("backup path is malformed")
    try:
        path = Path(raw_path).expanduser().resolve(strict=True)
    except (FileNotFoundError, OSError) as exc:
        raise BackupValidationError("backup artifact does not exist") from exc
    if not path.is_file():
        raise BackupValidationError("backup artifact is not a regular file")

    quote_count = manifest["daily_quote_row_count"]
    quote_sha = manifest["daily_quote_sha256"]
    if not isinstance(quote_count, int) or isinstance(quote_count, bool) or quote_count < 0:
        raise BackupValidationError("backup daily_quote row count is malformed")
    if not isinstance(quote_sha, str) or len(quote_sha) != 64:
        raise BackupValidationError("backup daily_quote SHA256 is malformed")
    try:
        int(quote_sha, 16)
    except ValueError as exc:
        raise BackupValidationError("backup daily_quote SHA256 is malformed") from exc

    expected_sha = manifest["sha256"]
    if not isinstance(expected_sha, str) or len(expected_sha) != 64:
        raise BackupValidationError("backup SHA256 is malformed")
    try:
        int(expected_sha, 16)
    except ValueError as exc:
        raise BackupValidationError("backup SHA256 is malformed") from exc
    actual_sha = _sha256(path)
    if not hmac.compare_digest(expected_sha.lower(), actual_sha):
        raise BackupValidationError("backup artifact hash mismatch")

    backup_format = manifest["format"]
    details: Dict[str, Any] = {}
    if backup_format == SQLITE_BACKUP_FORMAT:
        if expected_identity["dialect"] != "sqlite" or path.suffix.lower() != ".db":
            raise BackupValidationError("backup format does not match artifact")
        source = Path(expected_identity["database"])
        try:
            if source.exists() and os.path.samefile(source, path):
                raise BackupValidationError("backup artifact is the source database")
        except OSError as exc:
            raise BackupValidationError("could not compare backup and source") from exc
        details = _inspect_sqlite(path)
        if (
            details["daily_quote_row_count"] != quote_count
            or not hmac.compare_digest(details["daily_quote_sha256"], quote_sha.lower())
        ):
            raise BackupValidationError("SQLite backup daily_quote fingerprint mismatch")
    elif backup_format == POSTGRES_BACKUP_FORMAT:
        if expected_identity["dialect"] != "postgresql" or path.suffix.lower() != ".dump":
            raise BackupValidationError("backup format does not match artifact")
        _run_pg_restore_list(path)
    else:
        raise BackupValidationError("backup format is unsupported")

    return {
        "valid": True,
        "path": str(path),
        "sha256": actual_sha,
        "database_identity": actual_identity,
        "format": backup_format,
        "daily_quote_row_count": quote_count,
        "daily_quote_sha256": quote_sha.lower(),
        **details,
    }
