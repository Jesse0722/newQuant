from __future__ import annotations

import hashlib
import sqlite3
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine

from app.services import quote_repair_io as io


def _sqlite_db(path: Path, *, wal: bool = False) -> str:
    conn = sqlite3.connect(path)
    if wal:
        assert conn.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
    conn.execute(
        "CREATE TABLE daily_quote (id INTEGER PRIMARY KEY, ts_code TEXT NOT NULL, trade_date TEXT NOT NULL)"
    )
    conn.execute("INSERT INTO daily_quote(ts_code, trade_date) VALUES ('000001.SZ', '20260701')")
    conn.commit()
    conn.close()
    return f"sqlite:///{path}"


def test_database_identity_returns_absolute_sqlite_path(tmp_path):
    path = tmp_path / "quotes.db"
    url = _sqlite_db(path)
    engine = create_engine(url)
    with engine.connect() as conn:
        identity = io.database_identity(conn)
    engine.dispose()

    assert identity == {"dialect": "sqlite", "database": str(path.resolve())}
    assert "username" not in identity
    assert "password" not in identity


def test_writer_connection_commits_with_foreign_keys_and_no_wal_change(tmp_path):
    path = tmp_path / "quotes.db"
    url = _sqlite_db(path)
    with io.writer_connection(url, str(tmp_path)) as conn:
        assert conn.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
        assert conn.exec_driver_sql("PRAGMA journal_mode").scalar_one() == "delete"
        conn.exec_driver_sql(
            "INSERT INTO daily_quote(ts_code, trade_date) VALUES ('000002.SZ', '20260702')"
        )

    check = sqlite3.connect(path)
    try:
        assert check.execute("SELECT COUNT(*) FROM daily_quote").fetchone()[0] == 2
        assert check.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    finally:
        check.close()


def test_writer_connection_rolls_back_on_exception(tmp_path):
    path = tmp_path / "quotes.db"
    url = _sqlite_db(path)

    with pytest.raises(RuntimeError, match="stop"):
        with io.writer_connection(url, str(tmp_path)) as conn:
            conn.exec_driver_sql(
                "INSERT INTO daily_quote(ts_code, trade_date) VALUES ('000002.SZ', '20260702')"
            )
            raise RuntimeError("stop")

    check = sqlite3.connect(path)
    try:
        assert check.execute("SELECT COUNT(*) FROM daily_quote").fetchone()[0] == 1
    finally:
        check.close()


def test_writer_connection_reserves_sqlite_write_lock_before_yield(tmp_path):
    path = tmp_path / "quotes.db"
    url = _sqlite_db(path)

    with io.writer_connection(url, str(tmp_path)):
        contender = sqlite3.connect(path, timeout=0)
        try:
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                contender.execute(
                    "INSERT INTO daily_quote(ts_code, trade_date) VALUES ('000003.SZ', '20260703')"
                )
        finally:
            contender.close()


@pytest.mark.parametrize(
    "url",
    [
        "sqlite:///missing.db",
        "sqlite:///:memory:",
        "sqlite:///missing.db?mode=rw",
    ],
)
def test_writer_connection_refuses_missing_memory_and_query_urls(tmp_path, url):
    with pytest.raises(io.UnsafeDatabaseTargetError):
        with io.writer_connection(url, str(tmp_path)):
            pass
    assert list(tmp_path.iterdir()) == []


def test_writer_connection_mode_rw_closes_existence_check_race(monkeypatch, tmp_path):
    path = tmp_path / "quotes.db"
    url = _sqlite_db(path)
    original = io._sqlite_path

    def remove_after_check(database_url, app_cwd):
        checked = original(database_url, app_cwd)
        checked.unlink()
        return checked

    monkeypatch.setattr(io, "_sqlite_path", remove_after_check)
    with pytest.raises(io.UnsafeDatabaseTargetError, match="no longer available"):
        with io.writer_connection(url, str(tmp_path)):
            pass
    assert not path.exists()


def test_create_backup_includes_uncheckpointed_wal_and_validates(tmp_path):
    path = tmp_path / "quotes.db"
    url = _sqlite_db(path, wal=True)
    writer = sqlite3.connect(path)
    writer.execute("PRAGMA wal_autocheckpoint=0")
    writer.execute("INSERT INTO daily_quote(ts_code, trade_date) VALUES ('000002.SZ', '20260702')")
    writer.commit()
    assert (tmp_path / "quotes.db-wal").exists()

    backup_dir = tmp_path / "backups"
    manifest = io.create_backup(url, str(tmp_path), str(backup_dir))
    result = io.validate_backup(manifest, manifest["database_identity"])
    writer.close()

    assert manifest["format"] == io.SQLITE_BACKUP_FORMAT
    assert manifest["path"].endswith(".db")
    assert Path(manifest["path"]).parent == backup_dir.resolve()
    assert manifest["daily_quote_row_count"] == 2
    assert len(manifest["daily_quote_sha256"]) == 64
    assert result["valid"] is True
    assert result["daily_quote_row_count"] == 2
    assert manifest["sha256"] == hashlib.sha256(Path(manifest["path"]).read_bytes()).hexdigest()


def test_validate_backup_rejects_hash_identity_format_and_source_alias(tmp_path):
    source = tmp_path / "quotes.db"
    url = _sqlite_db(source)
    manifest = io.create_backup(url, str(tmp_path), str(tmp_path / "backups"))

    with pytest.raises(io.BackupValidationError, match="hash"):
        io.validate_backup({**manifest, "sha256": "0" * 64}, manifest["database_identity"])
    with pytest.raises(io.BackupValidationError, match="identity"):
        io.validate_backup(
            manifest,
            {"dialect": "sqlite", "database": str(tmp_path / "different.db")},
        )
    with pytest.raises(io.BackupValidationError, match="format"):
        io.validate_backup({**manifest, "format": "tar"}, manifest["database_identity"])
    with pytest.raises(io.BackupValidationError, match="fingerprint"):
        io.validate_backup(
            {**manifest, "daily_quote_row_count": manifest["daily_quote_row_count"] + 1},
            manifest["database_identity"],
        )
    with pytest.raises(io.BackupValidationError, match="fingerprint"):
        io.validate_backup(
            {**manifest, "daily_quote_sha256": "b" * 64},
            manifest["database_identity"],
        )

    source_manifest = {
        **manifest,
        "path": str(source),
        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
    }
    with pytest.raises(io.BackupValidationError, match="source"):
        io.validate_backup(source_manifest, manifest["database_identity"])


def test_validate_backup_rejects_sqlite_without_daily_quote(tmp_path):
    bad = tmp_path / "bad.db"
    sqlite3.connect(bad).close()
    identity = {"dialect": "sqlite", "database": str(tmp_path / "source.db")}
    manifest = {
        "id": "217edb76-ff48-4976-a2f8-35d99d9aea14",
        "path": str(bad),
        "sha256": hashlib.sha256(bad.read_bytes()).hexdigest(),
        "database_identity": identity,
        "created_at": "2026-07-01T00:00:00Z",
        "format": io.SQLITE_BACKUP_FORMAT,
        "daily_quote_row_count": 0,
        "daily_quote_sha256": "0" * 64,
    }
    with pytest.raises(io.BackupValidationError, match="daily_quote"):
        io.validate_backup(manifest, identity)


def test_postgres_backup_uses_libpq_env_and_never_credentials_in_argv(monkeypatch, tmp_path):
    calls = []
    state = {"snapshot_active": False}

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        if argv[0] == "pg_dump":
            assert state["snapshot_active"] is True
            output = Path(argv[argv.index("--file") + 1])
            output.write_bytes(b"PGDMP-safe-test")
        else:
            assert state["snapshot_active"] is False
        return subprocess.CompletedProcess(argv, 0, stdout=b"ok", stderr=b"")

    class Transaction:
        is_active = True

        def rollback(self):
            self.is_active = False
            state["snapshot_active"] = False

    class SnapshotResult:
        def scalar_one(self):
            return "00000003-0000001B-1"

    class Connection:
        def execution_options(self, **kwargs):
            assert kwargs == {"isolation_level": "REPEATABLE READ"}
            return self

        def begin(self):
            state["snapshot_active"] = True
            return Transaction()

        def exec_driver_sql(self, sql):
            if sql == "SELECT pg_export_snapshot()":
                return SnapshotResult()
            assert sql in {
                "SET TRANSACTION READ ONLY",
                f"SET LOCAL statement_timeout = {io.POSTGRES_DUMP_TIMEOUT_SECONDS * 1000}",
                f"SET LOCAL lock_timeout = {io.POSTGRES_LOCK_TIMEOUT_MS}",
            }

        def close(self):
            pass

    class Engine:
        def connect(self):
            return Connection()

        def dispose(self):
            pass

    identity = {
        "dialect": "postgresql",
        "database": "quotes",
        "schema": "public",
        "host": "10.0.0.8",
        "port": 5432,
    }
    monkeypatch.setattr(io.subprocess, "run", fake_run)
    monkeypatch.setattr(io, "create_engine", lambda *args, **kwargs: Engine())
    monkeypatch.setattr(io, "database_identity", lambda _conn: identity)
    monkeypatch.setattr(
        io,
        "quote_fingerprint",
        lambda _conn: {"daily_quote_row_count": 7, "daily_quote_sha256": "a" * 64},
    )
    monkeypatch.setenv("PGSERVICE", "wrong-database")
    monkeypatch.setenv("PGPASSWORD", "wrong-password")

    dsn = "postgresql+psycopg://repair_user:s3cr%40t@db.internal:5432/quotes?sslmode=require"
    manifest = io.create_backup(dsn, str(tmp_path), str(tmp_path / "backups"))

    dump_argv, dump_kwargs = calls[0]
    assert dump_argv[0] == "pg_dump"
    assert all("repair_user" not in arg and "s3cr" not in arg and "postgresql" not in arg for arg in dump_argv)
    assert dump_kwargs["env"]["PGUSER"] == "repair_user"
    assert dump_kwargs["env"]["PGPASSWORD"] == "s3cr@t"
    assert dump_kwargs["env"]["PGDATABASE"] == "quotes"
    assert dump_kwargs["env"]["PGSSLMODE"] == "require"
    assert "PGSERVICE" not in dump_kwargs["env"]
    assert dump_kwargs["timeout"] == io.POSTGRES_DUMP_TIMEOUT_SECONDS
    assert calls[1][0][:2] == ["pg_restore", "--list"]
    assert dump_argv[dump_argv.index("--snapshot") + 1] == "00000003-0000001B-1"
    assert manifest["database_identity"] == identity
    assert manifest["format"] == io.POSTGRES_BACKUP_FORMAT
    assert manifest["daily_quote_row_count"] == 7
    assert manifest["daily_quote_sha256"] == "a" * 64
    assert "repair_user" not in str(manifest)
    assert "s3cr" not in str(manifest)


def test_postgres_failure_does_not_expose_dsn_and_removes_artifact(monkeypatch, tmp_path):
    def fake_run(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 1, stdout=b"", stderr=b"password=s3cr@t")

    class Transaction:
        is_active = True

        def rollback(self):
            self.is_active = False

    class SnapshotResult:
        def scalar_one(self):
            return "00000003-0000001B-1"

    class Connection:
        def execution_options(self, **_kwargs):
            return self

        def begin(self):
            return Transaction()

        def exec_driver_sql(self, sql):
            return SnapshotResult() if sql == "SELECT pg_export_snapshot()" else None

        def close(self):
            pass

    class Engine:
        def connect(self):
            return Connection()

        def dispose(self):
            pass

    monkeypatch.setattr(io.subprocess, "run", fake_run)
    monkeypatch.setattr(io, "create_engine", lambda *args, **kwargs: Engine())
    monkeypatch.setattr(
        io,
        "database_identity",
        lambda _conn: {"dialect": "postgresql", "database": "quotes", "schema": "public", "host": "10.0.0.8", "port": 5432},
    )
    monkeypatch.setattr(
        io,
        "quote_fingerprint",
        lambda _conn: {"daily_quote_row_count": 7, "daily_quote_sha256": "a" * 64},
    )
    dsn = "postgresql+psycopg://repair_user:s3cr%40t@db.internal:5432/quotes"

    with pytest.raises(io.BackupError) as caught:
        io.create_backup(dsn, str(tmp_path), str(tmp_path / "backups"))

    assert "repair_user" not in str(caught.value)
    assert "s3cr" not in str(caught.value)
    assert list((tmp_path / "backups").iterdir()) == []


def test_quote_fingerprint_is_deterministic_and_changes_with_rows(tmp_path):
    path = tmp_path / "fingerprint.db"
    _sqlite_db(path)
    conn = sqlite3.connect(path)
    try:
        first = io.quote_fingerprint(conn)
        assert first == io.quote_fingerprint(conn)
        conn.execute("INSERT INTO daily_quote(ts_code, trade_date) VALUES ('000002.SZ', '20260702')")
        conn.commit()
        second = io.quote_fingerprint(conn)
    finally:
        conn.close()

    assert first["daily_quote_row_count"] == 1
    assert second["daily_quote_row_count"] == 2
    assert first["daily_quote_sha256"] != second["daily_quote_sha256"]
    engine = create_engine(f"sqlite:///{path}")
    try:
        with engine.connect() as sql_conn:
            assert io.quote_fingerprint(sql_conn) == second
    finally:
        engine.dispose()


def test_quote_fingerprint_canonicalizes_float_specials_and_signed_zero():
    class Cursor:
        description = [("ts_code",), ("trade_date",), ("value",)]

        def __init__(self, value):
            self.rows = [("000001.SZ", "20260701", value)]

        def __iter__(self):
            return iter(self.rows)

    class Connection:
        def __init__(self, value):
            self.value = value

        def execute(self, _sql):
            return Cursor(self.value)

    assert io.quote_fingerprint(Connection(-0.0)) == io.quote_fingerprint(Connection(0.0))
    assert io.quote_fingerprint(Connection(float("nan"))) == io.quote_fingerprint(Connection(float("nan")))
    assert io._fingerprint_value(float("inf")) == {"__float__": "+inf"}
    assert io._fingerprint_value(float("-inf")) == {"__float__": "-inf"}


def test_validate_postgres_backup_runs_pg_restore_list(monkeypatch, tmp_path):
    path = tmp_path / "217edb76-ff48-4976-a2f8-35d99d9aea14.dump"
    path.write_bytes(b"PGDMP-safe-test")
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, stdout=b"ok", stderr=b"")

    monkeypatch.setattr(io.subprocess, "run", fake_run)
    identity = {
        "dialect": "postgresql",
        "database": "quotes",
        "schema": "public",
        "host": "10.0.0.8",
        "port": 5432,
    }
    manifest = {
        "id": "217edb76-ff48-4976-a2f8-35d99d9aea14",
        "path": str(path),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "database_identity": identity,
        "created_at": "2026-07-01T00:00:00Z",
        "format": io.POSTGRES_BACKUP_FORMAT,
        "daily_quote_row_count": 7,
        "daily_quote_sha256": "a" * 64,
    }

    assert io.validate_backup(manifest, identity)["valid"] is True
    assert calls[0][0] == ["pg_restore", "--list", str(path.resolve())]


def test_database_identity_postgres_redacts_credentials():
    class Result:
        def mappings(self):
            return self

        def one(self):
            return {"database": "quotes", "schema": "repair", "host": "10.0.0.8", "port": 5432}

    class FakeConnection:
        dialect = SimpleNamespace(name="postgresql")

        def exec_driver_sql(self, _sql):
            return Result()

    identity = io.database_identity(FakeConnection())
    assert identity == {
        "dialect": "postgresql",
        "database": "quotes",
        "schema": "repair",
        "host": "10.0.0.8",
        "port": 5432,
    }
    assert "user" not in identity
    assert "password" not in identity


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+psycopg://user:secret@/quotes",
        "postgresql+psycopg://user:secret@db.internal/",
        "postgresql+psycopg://user:secret@db.internal/quotes?host=evil.internal",
        "postgresql+psycopg://user:secret@db.internal/quotes?dbname=other",
        "postgresql+psycopg://user:secret@db.internal/quotes?user=other",
        "postgresql+psycopg://user:secret@db.internal/quotes?options=-csearch_path%3Devil",
        "postgresql+psycopg://user:secret@db.internal/quotes?connect_timeout=3",
        "postgresql+psycopg://user:secret@db.internal:70000/quotes",
        "postgresql+psycopg://user:secret@db.internal/quotes?sslmode=require&sslmode=disable",
    ],
)
def test_postgres_url_rejects_missing_target_and_unsupported_overrides(url):
    with pytest.raises(io.UnsafeDatabaseTargetError):
        io._postgres_url(url)


def test_postgres_url_normalizes_port_user_and_ssl_query(monkeypatch):
    monkeypatch.setattr(io.getpass, "getuser", lambda: "os_repair_user")

    url = io._postgres_url(
        "postgresql+psycopg://db.internal/quotes?sslmode=verify-full&sslrootcert=%2Ftmp%2Fca.pem"
    )

    assert url.host == "db.internal"
    assert url.database == "quotes"
    assert url.port == 5432
    assert url.username == "os_repair_user"
    assert dict(url.query) == {"sslmode": "verify-full", "sslrootcert": "/tmp/ca.pem"}


def test_postgres_libpq_env_uses_normalized_target_not_ambient(monkeypatch):
    monkeypatch.setattr(io.getpass, "getuser", lambda: "os_repair_user")
    monkeypatch.setenv("PGHOST", "wrong.internal")
    monkeypatch.setenv("PGPORT", "9999")
    monkeypatch.setenv("PGUSER", "wrong_user")
    monkeypatch.setenv("PGDATABASE", "wrong_db")
    url = io._postgres_url("postgresql+psycopg://db.internal/quotes?sslmode=require")

    env = io._postgres_libpq_env(url)

    assert env["PGHOST"] == "db.internal"
    assert env["PGPORT"] == "5432"
    assert env["PGUSER"] == "os_repair_user"
    assert env["PGDATABASE"] == "quotes"
    assert env["PGSSLMODE"] == "require"


def test_postgres_writer_uses_read_committed_and_local_timeouts(monkeypatch):
    events = []
    captured = {}

    class Transaction:
        is_active = True

        def commit(self):
            events.append("commit")
            self.is_active = False

        def rollback(self):
            events.append("rollback")
            self.is_active = False

    class Connection:
        def execution_options(self, **kwargs):
            events.append(("execution_options", kwargs))
            return self

        def begin(self):
            events.append("begin")
            return Transaction()

        def exec_driver_sql(self, sql):
            events.append(sql)

        def close(self):
            events.append("close")

    class Engine:
        def connect(self):
            events.append("connect")
            return Connection()

        def dispose(self):
            events.append("dispose")

    def fake_create_engine(url, **kwargs):
        captured["url"] = url
        return Engine()

    monkeypatch.setattr(io, "create_engine", fake_create_engine)

    with io.writer_connection("postgresql+psycopg://user:secret@db/quotes", "/unused") as conn:
        events.append(("yield", conn.__class__.__name__))

    assert ("execution_options", {"isolation_level": "READ COMMITTED"}) in events
    assert f"SET LOCAL statement_timeout = {io.POSTGRES_STATEMENT_TIMEOUT_MS}" in events
    assert f"SET LOCAL lock_timeout = {io.POSTGRES_LOCK_TIMEOUT_MS}" in events
    assert events.index("begin") < events.index(f"SET LOCAL statement_timeout = {io.POSTGRES_STATEMENT_TIMEOUT_MS}")
    assert events.index("commit") < events.index("close")
    assert captured["url"].host == "db"
    assert captured["url"].port == 5432
    assert captured["url"].database == "quotes"
    assert captured["url"].username == "user"
