from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.models.stock import DailyQuote, StockBasic
from app.routers.health import router
from app.services.market_data_quality_service import readonly_connection
from app.services.quote_repair_io import create_backup
from scripts.adopt_legacy_schema import adopt_legacy_schema, BASELINE, AUDIT
from scripts.deployment_database import restore_database
from test_reliability_migrations import run_alembic, assert_schema_matches


def test_unversioned_complete_schema_is_validated_before_stamp(tmp_path):
    url = "sqlite:///" + str(tmp_path / "legacy.db")
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(StockBasic.__table__.insert(), {"ts_code": "000001.SZ", "name": "preserved"})
    assert adopt_legacy_schema(url, dry_run=True) == "would_stamp:" + AUDIT
    assert "alembic_version" not in inspect(engine).get_table_names()
    assert adopt_legacy_schema(url) == AUDIT
    assert adopt_legacy_schema(url) == "already_versioned"
    run_alembic(url, "upgrade", "head")
    assert_schema_matches(engine)
    with engine.connect() as conn:
        assert conn.execute(select(StockBasic.__table__.c.name)).scalar_one() == "preserved"
    engine.dispose()


def test_partial_unknown_schema_is_never_stamped(tmp_path):
    url = "sqlite:///" + str(tmp_path / "partial.db")
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE stock_basic (ts_code TEXT PRIMARY KEY)")
    with pytest.raises(ValueError, match="baseline"):
        adopt_legacy_schema(url)
    assert "alembic_version" not in inspect(engine).get_table_names()
    engine.dispose()


def test_missing_unique_constraint_blocks_legacy_stamp(tmp_path):
    import re
    url = "sqlite:///" + str(tmp_path / "drift.db")
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        ddl = conn.exec_driver_sql("SELECT sql FROM sqlite_master WHERE name='watch_stock'").scalar_one()
        altered = re.sub(r",\s*CONSTRAINT uq_pool_stock UNIQUE \(pool_id, ts_code\)", "", ddl)
        assert ddl != altered
        conn.exec_driver_sql("DROP TABLE watch_stock")
        conn.exec_driver_sql(altered)
    with pytest.raises(ValueError, match="unique-constraint"):
        adopt_legacy_schema(url)
    assert "alembic_version" not in inspect(engine).get_table_names()
    engine.dispose()


def test_baseline_with_explicit_audit_bootstrap_is_validated_then_adopted(tmp_path):
    url = "sqlite:///" + str(tmp_path / "baseline-with-audit.db")
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    run_alembic(url, "stamp", BASELINE)
    assert adopt_legacy_schema(url, dry_run=True) == "would_stamp:" + AUDIT
    assert adopt_legacy_schema(url) == AUDIT
    run_alembic(url, "upgrade", "head")
    assert_schema_matches(engine)
    engine.dispose()


def test_audit_unique_constraint_drift_is_not_stamped(tmp_path):
    import re
    url = "sqlite:///" + str(tmp_path / "audit-drift.db")
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        ddl = conn.exec_driver_sql("SELECT sql FROM sqlite_master WHERE name='daily_quote_repair_batch'").scalar_one()
        altered = re.sub(r",\s*CONSTRAINT uq_daily_quote_repair_batch_plan_hash UNIQUE \(plan_hash\)", "", ddl)
        assert ddl != altered
        conn.exec_driver_sql("DROP TABLE daily_quote_repair_batch")
        conn.exec_driver_sql(altered)
    with pytest.raises(ValueError, match="unique-constraint"):
        adopt_legacy_schema(url, dry_run=True)
    assert "alembic_version" not in inspect(engine).get_table_names()
    engine.dispose()


def test_full_sqlite_backup_restore_and_manifest_guard(tmp_path):
    url = "sqlite:///" + str(tmp_path / "source.db")
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(StockBasic.__table__.insert(), {"ts_code": "000001.SZ", "name": "before"})
        conn.execute(DailyQuote.__table__.insert(), {"ts_code": "000001.SZ", "trade_date": "20261110", "close": 10})
    engine.dispose()
    manifest = create_backup(url, str(tmp_path), str(tmp_path / "backups"))
    with engine.begin() as conn:
        conn.execute(StockBasic.__table__.update().values(name="after"))
        conn.execute(DailyQuote.__table__.update().values(close=99))
    engine.dispose()
    with pytest.raises(Exception):
        restore_database(url, {**manifest, "sha256": "0" * 64})
    assert restore_database(url, manifest)["status"] == "restored"
    with readonly_connection(url, tmp_path) as (conn, _):
        assert conn.execute(select(StockBasic.__table__.c.name)).scalar_one() == "before"
        assert conn.execute(select(DailyQuote.__table__.c.close)).scalar_one() == 10


def test_readiness_checks_schema_and_returns_no_exception_details():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    factory = sessionmaker(bind=engine)
    app = FastAPI()
    app.include_router(router)
    def dependency():
        with factory() as db:
            yield db
    app.dependency_overrides[get_db] = dependency
    with TestClient(app) as client:
        result = client.get("/api/ready")
        assert result.status_code == 503 and "SELECT" not in result.text
        Base.metadata.create_all(engine)
        assert client.get("/api/ready").json()["schema"] == "ok"
        Base.metadata.tables["message_opportunity_evidence"].drop(engine)
        assert client.get("/api/ready").status_code == 503
    engine.dispose()


def test_release_script_is_valid_shell():
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(["bash", "-n", str(root / "deploy/aliyun/deploy-local-build.sh")], capture_output=True)
    assert result.returncode == 0


@pytest.mark.parametrize("failure", ["", "migration", "backup", "smoke", "stop"])
def test_release_backup_migration_smoke_and_rollback_order(tmp_path, failure):
    """Exercise shell orchestration without Docker, network or any business DB."""
    import io
    import tarfile
    root = Path(__file__).resolve().parents[2]
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    (app_dir / "backend.env").write_text("DATABASE_URL=sqlite:///./data/fixture.db\n")
    repo_dir = tmp_path / "repo"
    (repo_dir / ".git").mkdir(parents=True)
    archive = tmp_path / "release.tar"
    with tarfile.open(archive, "w") as tar:
        data = b"services: {}\n"
        info = tarfile.TarInfo("docker-compose.ecs.yml")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = f'''#!{sys.executable}
import json, os, pathlib, sys
name=pathlib.Path(sys.argv[0]).name
args=sys.argv[1:]
with open(os.environ["CALL_LOG"], "a") as log: log.write(json.dumps([name,*args])+"\\n")
failure=os.environ.get("FAILURE", "")
if name=="git":
    if "rev-parse" in args: print("a"*40)
    if "archive" in args: sys.stdout.buffer.write(pathlib.Path(os.environ["ARCHIVE"]).read_bytes())
elif name=="docker":
    joined=" ".join(args)
    if args[:2]==["image", "inspect"]: print("old-"+args[2].split(":")[0])
    if "backup" in args:
        if failure=="backup": sys.exit(1)
        print("/app/backend/data/deployment-backups/fixture.manifest.json")
    if failure=="migration" and "alembic" in args: sys.exit(1)
    if failure=="stop" and "stop" in args: sys.exit(1)
elif name=="curl" and failure=="smoke" and any("/api/ready" in arg for arg in args): sys.exit(1)
'''
    for name in ("git", "docker", "curl", "flock"):
        executable = bin_dir / name
        executable.write_text(fake)
        executable.chmod(0o700)
    log = tmp_path / "calls.jsonl"
    env = {**os.environ, "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
           "APP_DIR": str(app_dir), "REPO_DIR": str(repo_dir), "CALL_LOG": str(log),
           "ARCHIVE": str(archive), "FAILURE": failure}
    result = subprocess.run(["bash", str(root / "deploy/aliyun/deploy-local-build.sh")],
                            env=env, capture_output=True, text=True, timeout=20)
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    commands = [" ".join(call) for call in calls]
    assert (result.returncode == 0) is (not failure), result.stderr
    if failure == "stop":
        assert not any("restore" in call or "backup" in call for call in calls)
        assert "refusing automatic restore" in result.stderr
        return
    backup_index = next(i for i, call in enumerate(calls) if "backup" in call)
    if failure != "backup":
        migration_index = next(i for i, call in enumerate(calls) if "alembic" in call)
        assert backup_index < migration_index
    restores = [call for call in calls if "restore" in call]
    assert bool(restores) is (failure in {"migration", "smoke"})
    if failure:
        assert not (app_dir / "current-release").exists()
        assert any("rollback.yml" in command for command in commands)
    else:
        assert (app_dir / "current-release").is_symlink()
        assert any("/api/ready" in command for command in commands)
