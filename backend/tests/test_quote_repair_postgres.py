"""Opt-in real PG migration, backup/restore and repair round-trip in scratch DBs."""
from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import sys
import uuid

import pytest
from sqlalchemy import create_engine, insert, select
from sqlalchemy.engine import make_url

from app.services.daily_quote_repair_service import (
    Q, SNAPSHOT_VERSION, apply_repair_plan, make_repair_plan, quote_state,
    rollback_repair_batch, verify_repair_batch,
)
from app.services.market_data_quality_service import readonly_connection
from app.services.quote_repair_io import _postgres_libpq_env, create_backup, writer_connection

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.integration
def test_real_postgres_repair_backup_restore_roundtrip(tmp_path):
    admin_url = os.environ.get("QUOTE_REPAIR_POSTGRES_ADMIN_URL")
    if not admin_url:
        pytest.skip("set QUOTE_REPAIR_POSTGRES_ADMIN_URL for isolated scratch DB test")
    admin_url = make_url(admin_url)
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    name = "newquant_repair_test_" + uuid.uuid4().hex[:12]
    names = [name, name + "_restore"]
    engines, created = [], []
    try:
        with admin.connect() as conn:
            for dbname in names:
                assert re.fullmatch(r"newquant_repair_test_[a-f0-9]{12}(_restore)?", dbname)
                conn.exec_driver_sql(f'CREATE DATABASE "{dbname}"')
                created.append(dbname)
        target = admin_url.set(database=name)
        url = target.render_as_string(hide_password=False)
        env = {**os.environ, "DATABASE_URL": url}
        upgrade = subprocess.run([sys.executable, "-m", "alembic", "-c", str(ROOT.parent / "alembic.ini"), "upgrade", "head"],
                                 cwd=ROOT.parent, env=env, capture_output=True, timeout=60)
        assert upgrade.returncode == 0, "scratch PostgreSQL migration failed"
        engine = create_engine(target)
        engines.append(engine)
        raw = dict(ts_code="000001.SZ", trade_date="20261008", open=10., high=11., low=9., close=10.,
                   pre_close=10., pct_chg=0., change=0., vol=1000., amount=20000., turnover_rate=None, float_share=None)
        with engine.begin() as conn:
            conn.execute(insert(Q).values(**{**raw, "amount": None, "pre_close": None}))
        snap = {"version": SNAPSHOT_VERSION, "id": "real-pg-fixture", "codes": ["000001.SZ"],
                "dates": ["20261008", "20261009"], "rows": [raw, {**raw, "trade_date": "20261009"}],
                "source": {"name": "baostock", "volume_unit": "share", "amount_unit": "cny",
                           "data_stage": "final", "adjustment": "none", "captured_at": "2026-11-04T00:00:00Z"}}
        with readonly_connection(url, ROOT) as (conn, _):
            before = [quote_state(r) for r in conn.execute(select(Q)).mappings()]
            plan = make_repair_plan(conn, snap)
        manifest = create_backup(url, str(ROOT), str(tmp_path))
        with writer_connection(url, str(ROOT)) as conn:
            applied = apply_repair_plan(conn, plan, manifest)
        with readonly_connection(url, ROOT) as (conn, _):
            assert verify_repair_batch(conn, applied["batch_id"])["matches"]
        rollback_backup = create_backup(url, str(ROOT), str(tmp_path))
        with writer_connection(url, str(ROOT)) as conn:
            assert rollback_repair_batch(conn, applied["batch_id"], rollback_backup)["status"] == "rolled_back"
        with readonly_connection(url, ROOT) as (conn, _):
            assert [quote_state(r) for r in conn.execute(select(Q)).mappings()] == before
            assert verify_repair_batch(conn, applied["batch_id"])["matches"]
        restore_url = admin_url.set(database=names[1])
        restored = subprocess.run(["pg_restore", "--dbname", names[1], "--exit-on-error", "--no-owner",
                                   "--no-privileges", manifest["path"]],
                                  env=_postgres_libpq_env(restore_url), capture_output=True, timeout=60)
        assert restored.returncode == 0, "scratch backup restore failed"
        restored_engine = create_engine(restore_url)
        engines.append(restored_engine)
        with restored_engine.connect() as conn:
            assert [quote_state(r) for r in conn.execute(select(Q)).mappings()] == before
        down = subprocess.run([sys.executable, "-m", "alembic", "-c", str(ROOT.parent / "alembic.ini"), "downgrade", "c4647a9160ea"],
                              cwd=ROOT.parent, env=env, capture_output=True, timeout=60)
        assert down.returncode == 0, "scratch audit migration downgrade failed"
        with engine.connect() as conn:
            assert conn.execute(select(Q)).mappings().first()["amount"] is None
    finally:
        for engine in engines:
            engine.dispose()
        with admin.connect() as conn:
            for dbname in reversed(created):
                conn.exec_driver_sql(f'DROP DATABASE "{dbname}" WITH (FORCE)')
        admin.dispose()
