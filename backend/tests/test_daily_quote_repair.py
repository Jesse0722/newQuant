from __future__ import annotations

from copy import deepcopy
import hashlib
import json

import pytest
from sqlalchemy import create_engine, insert, select, update

from app.database import Base
from app.models.daily_quote_repair import DailyQuoteRepairAudit, DailyQuoteRepairBatch
from app.models.stock import DailyQuote, StockBasic
from app.services.daily_quote_repair_service import (
    A, B, Q, PLAN_VERSION, SNAPSHOT_VERSION, RepairError, apply_repair_plan, digest,
    make_repair_plan, quote_state, rollback_repair_batch, validate_plan, verify_repair_batch,
)
from app.services.market_data_quality_service import readonly_connection
from app.services.quote_repair_io import create_backup, writer_connection
from scripts import repair_daily_quotes as cli


def row(code="000001.SZ", day="20261008", **changes):
    values = dict(ts_code=code, trade_date=day, open=10., high=11., low=9., close=10.,
                  pre_close=10., change=0., pct_chg=0., vol=1000., amount=20000.,
                  turnover_rate=None, float_share=None)
    return {**values, **changes}


def snapshot(rows):
    return {"version": SNAPSHOT_VERSION, "id": "fixture-snapshot", "dates": ["20261008", "20261009"],
            "codes": ["000001.SZ"], "rows": rows, "requests": [], "source": {
                "name": "baostock", "volume_unit": "share", "amount_unit": "cny",
                "data_stage": "final", "adjustment": "none", "captured_at": "2026-11-04T12:00:00+00:00"}}


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "quotes.db"
    url = "sqlite:///" + str(path)
    engine = create_engine(url)
    Base.metadata.create_all(engine, tables=[Q, StockBasic.__table__, B, A])
    with engine.begin() as conn:
        conn.execute(insert(Q).values(**row(pre_close=None, pct_chg=None, amount=None)))
        conn.execute(insert(Q).values(**row(code="600000.SH", close=9.5)))
    engine.dispose()
    return url, tmp_path, path


def plan(db, rows=None, **kwargs):
    url, cwd, _ = db
    with readonly_connection(url, cwd) as (conn, _):
        return make_repair_plan(conn, snapshot(rows if rows is not None else [row(), row(day="20261009")]), **kwargs)


def backup(db):
    url, cwd, _ = db
    return create_backup(url, str(cwd), str(cwd / "backup"))


def states(db):
    with readonly_connection(db[0], db[1]) as (conn, _):
        return [quote_state(r) for r in conn.execute(select(Q).order_by(Q.c.ts_code, Q.c.trade_date)).mappings()]


def test_dry_run_is_readonly_with_exact_field_differences_and_whole_source(db):
    before = hashlib.sha256(db[2].read_bytes()).hexdigest()
    result = plan(db)
    assert hashlib.sha256(db[2].read_bytes()).hexdigest() == before
    assert result["summary"]["updates"] == 1 and result["summary"]["inserts"] == 1
    item = result["items"][0]
    assert {"pre_close", "pct_chg", "vol", "amount"} <= set(item["changed_fields"])
    assert item["new_values"]["vol"] == 10 and item["new_values"]["amount"] == 20
    assert len(set(item["source_json"]["field_source"].values())) == 1
    validate_plan(result)


def test_apply_verify_idempotence_and_exact_rollback(db):
    initial = states(db)
    proposal = plan(db)
    manifest = backup(db)
    with writer_connection(db[0], str(db[1])) as conn:
        result = apply_repair_plan(conn, proposal, manifest)
    assert result["row_count_before"] == 2 and result["row_count_after"] == 3
    batch_id = result["batch_id"]
    with readonly_connection(db[0], db[1]) as (conn, _):
        assert verify_repair_batch(conn, batch_id)["matches"]
        audits = list(conn.execute(select(A).where(A.c.batch_id == batch_id)).mappings())
        assert len(audits) == 2 and audits[0]["old_values"] is not None
        assert audits[1]["old_values"] is None
    with writer_connection(db[0], str(db[1])) as conn:
        assert apply_repair_plan(conn, proposal, manifest)["status"] == "already_applied"
    restore_backup = backup(db)
    with writer_connection(db[0], str(db[1])) as conn:
        result = rollback_repair_batch(conn, batch_id, restore_backup)
    assert result["status"] == "rolled_back" and states(db) == initial
    with readonly_connection(db[0], db[1]) as (conn, _):
        assert verify_repair_batch(conn, batch_id)["matches"]
    with writer_connection(db[0], str(db[1])) as conn:
        assert rollback_repair_batch(conn, batch_id, restore_backup)["status"] == "already_rolled_back"
    with pytest.raises(RepairError):
        with writer_connection(db[0], str(db[1])) as conn:
            apply_repair_plan(conn, proposal, manifest)


def test_stale_plan_conflict_prevents_all_writes_and_audit(db):
    proposal = plan(db)
    with writer_connection(db[0], str(db[1])) as conn:
        conn.execute(update(Q).where(Q.c.ts_code == "000001.SZ").values(close=10.5))
    initial = states(db)
    manifest = backup(db)
    with pytest.raises(RepairError, match="冲突"):
        with writer_connection(db[0], str(db[1])) as conn:
            apply_repair_plan(conn, proposal, manifest)
    assert states(db) == initial
    with readonly_connection(db[0], db[1]) as (conn, _):
        assert conn.execute(select(B)).all() == []


def test_rollback_refuses_later_modification_of_any_field(db):
    proposal, manifest = plan(db), backup(db)
    with writer_connection(db[0], str(db[1])) as conn:
        batch = apply_repair_plan(conn, proposal, manifest)["batch_id"]
    with writer_connection(db[0], str(db[1])) as conn:
        conn.execute(update(Q).where(Q.c.ts_code == "000001.SZ").values(float_share=123))
    changed = states(db)
    new_backup = backup(db)
    with pytest.raises(RepairError, match="冲突"):
        with writer_connection(db[0], str(db[1])) as conn:
            rollback_repair_batch(conn, batch, new_backup)
    assert states(db) == changed
    with readonly_connection(db[0], db[1]) as (conn, _):
        assert not verify_repair_batch(conn, batch)["matches"]


def test_write_or_audit_failure_rolls_back_both_data_and_batch(db):
    proposal, manifest = plan(db), backup(db)
    with writer_connection(db[0], str(db[1])) as conn:
        conn.exec_driver_sql("CREATE TRIGGER reject_audit BEFORE INSERT ON daily_quote_repair_audit BEGIN SELECT RAISE(ABORT, 'injected'); END")
    initial = states(db)
    with pytest.raises(Exception):
        with writer_connection(db[0], str(db[1])) as conn:
            apply_repair_plan(conn, proposal, manifest)
    assert states(db) == initial
    with readonly_connection(db[0], db[1]) as (conn, _):
        assert conn.execute(select(B)).all() == [] and conn.execute(select(A)).all() == []


def test_silent_audit_write_corruption_aborts_the_whole_batch(db):
    proposal, manifest = plan(db), backup(db)
    with writer_connection(db[0], str(db[1])) as conn:
        conn.exec_driver_sql("CREATE TRIGGER corrupt_audit AFTER INSERT ON daily_quote_repair_audit "
                             "BEGIN UPDATE daily_quote_repair_audit SET source_json='{}' WHERE id=NEW.id; END")
    initial = states(db)
    with pytest.raises(RepairError, match="审计"):
        with writer_connection(db[0], str(db[1])) as conn:
            apply_repair_plan(conn, proposal, manifest)
    assert states(db) == initial
    with readonly_connection(db[0], db[1]) as (conn, _):
        assert conn.execute(select(B)).all() == [] and conn.execute(select(A)).all() == []


@pytest.mark.parametrize("bad", ["hash", "target", "file"])
def test_missing_invalid_or_wrong_target_backup_prevents_write(db, bad):
    proposal, manifest = plan(db), backup(db)
    if bad == "hash":
        manifest["sha256"] = "0" * 64
    elif bad == "target":
        manifest["database_identity"]["database"] += ".other"
    else:
        manifest["path"] += ".missing"
    initial = states(db)
    with pytest.raises(Exception):
        with writer_connection(db[0], str(db[1])) as conn:
            apply_repair_plan(conn, proposal, manifest)
    assert states(db) == initial


def test_optional_field_loss_skipped_unless_explicit_in_plan(db):
    with writer_connection(db[0], str(db[1])) as conn:
        conn.execute(update(Q).where(Q.c.ts_code == "000001.SZ").values(turnover_rate=1.5, float_share=200))
    proposal = plan(db, rows=[row()])
    assert not proposal["items"] and proposal["skipped"][0]["reason"] == "optional_field_loss"
    allowed = plan(db, rows=[row()], allow_clear_optional=True)
    assert allowed["items"][0]["new_values"]["float_share"] is None
    assert "float_share" in allowed["items"][0]["changed_fields"]
    validate_plan(allowed)


@pytest.mark.parametrize("bad_row", [row(close=float("inf")), row(high=5), row(amount=-1), row(pct_chg=20)])
def test_invalid_source_never_becomes_repair(db, bad_row):
    result = plan(db, rows=[bad_row])
    assert result["summary"]["skipped"] == 1 and result["items"] == []


def test_duplicate_source_keys_rejected_and_empty_snapshot_does_not_delete(db):
    initial = states(db)
    assert plan(db, rows=[row(), row()])["items"] == []
    proposal = plan(db, rows=[])
    assert proposal["items"] == [] and states(db) == initial
    with writer_connection(db[0], str(db[1])) as conn:
        assert apply_repair_plan(conn, proposal, None)["status"] == "no_changes"


def test_tampered_new_values_or_provenance_fails_validation(db):
    original = plan(db)
    for field in ("new_values", "source_json"):
        proposal = deepcopy(original)
        if field == "new_values":
            proposal["items"][0][field]["amount"] = 999
        else:
            proposal["items"][0][field]["raw_values"]["amount"] = 999
        with pytest.raises(RepairError):
            validate_plan(proposal)


@pytest.mark.parametrize("field", ["updates", "inserts"])
def test_plan_summary_cannot_be_tampered(db, field):
    proposal = plan(db)
    proposal["summary"][field] += 1
    with pytest.raises(RepairError, match="汇总"):
        validate_plan(proposal)


def test_backup_state_drift_on_unrelated_row_prevents_apply(db):
    proposal, manifest = plan(db), backup(db)
    with writer_connection(db[0], str(db[1])) as conn:
        conn.execute(update(Q).where(Q.c.ts_code == "600000.SH").values(amount=99))
    initial = states(db)
    with pytest.raises(RepairError, match="备份后"):
        with writer_connection(db[0], str(db[1])) as conn:
            apply_repair_plan(conn, proposal, manifest)
    assert states(db) == initial


@pytest.mark.parametrize("field", ["source_json", "changed_fields", "operation"])
def test_audit_provenance_tampering_blocks_verify_and_rollback(db, field):
    proposal, manifest = plan(db), backup(db)
    with writer_connection(db[0], str(db[1])) as conn:
        batch = apply_repair_plan(conn, proposal, manifest)["batch_id"]
    changed_value = {"source_json": {"tampered": True}, "changed_fields": ["close"], "operation": "insert"}[field]
    with writer_connection(db[0], str(db[1])) as conn:
        conn.execute(update(A).where(A.c.batch_id == batch, A.c.sequence == 0).values(**{field: changed_value}))
    with readonly_connection(db[0], db[1]) as (conn, _):
        result = verify_repair_batch(conn, batch)
        assert not result["audit_integrity"] and not result["matches"]
    saved = states(db)
    new_backup = backup(db)
    with pytest.raises(RepairError, match="审计"):
        with writer_connection(db[0], str(db[1])) as conn:
            rollback_repair_batch(conn, batch, new_backup)
    assert states(db) == saved


def test_legacy_nonfinite_and_invalid_text_round_trip(db):
    with writer_connection(db[0], str(db[1])) as conn:
        conn.exec_driver_sql("UPDATE daily_quote SET high=?,amount=? WHERE ts_code=?", (float("inf"), "bad-legacy", "000001.SZ"))
    initial = states(db)
    proposal, manifest = plan(db), backup(db)
    json.dumps(proposal, allow_nan=False)
    with writer_connection(db[0], str(db[1])) as conn:
        batch_id = apply_repair_plan(conn, proposal, manifest)["batch_id"]
    new_backup = backup(db)
    with writer_connection(db[0], str(db[1])) as conn:
        rollback_repair_batch(conn, batch_id, new_backup)
    assert states(db) == initial


def test_missing_audit_record_prevents_partial_rollback(db):
    proposal, manifest = plan(db), backup(db)
    with writer_connection(db[0], str(db[1])) as conn:
        batch = apply_repair_plan(conn, proposal, manifest)["batch_id"]
    with writer_connection(db[0], str(db[1])) as conn:
        conn.execute(A.delete().where(A.c.batch_id == batch, A.c.sequence == 0))
    changed = states(db)
    new_backup = backup(db)
    with pytest.raises(RepairError, match="数量"):
        with writer_connection(db[0], str(db[1])) as conn:
            rollback_repair_batch(conn, batch, new_backup)
    assert states(db) == changed


def test_cli_plan_apply_verify_rollback_and_hash_guard(db, monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", db[0])
    snap = db[1] / "snapshot.json"
    snap.write_text(json.dumps(snapshot([row(), row(day="20261009")])))
    proposal = db[1] / "plan.json"
    assert cli.main(["plan", "--snapshot", str(snap), "--output", str(proposal)]) == 0
    output = json.loads(capsys.readouterr().out)
    plan_sha = output["plan_sha256"]
    apply = ["apply", "--plan", str(proposal), "--plan-sha256", plan_sha, "--backup-dir", str(db[1] / "backups")]
    bad = list(apply); bad[4] = "0" * 64
    assert cli.main(bad) == 1
    capsys.readouterr()
    assert cli.main(apply) == 0
    batch = json.loads(capsys.readouterr().out)["batch_id"]
    assert cli.main(["verify", "--batch-id", batch]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["matches"] and result["approved_file_sha256"] == plan_sha
    assert result["plan_hash"] == digest(json.loads(proposal.read_text()))
    assert cli.main(["rollback", "--batch-id", batch, "--backup-dir", str(db[1] / "backups")]) == 0
    capsys.readouterr()
    assert cli.main(["verify", "--batch-id", batch]) == 0


def test_immutable_artifacts_cannot_be_overwritten(tmp_path):
    path = tmp_path / "snapshot.json"
    cli.write_json(path, {"test": 1})
    with pytest.raises(FileExistsError):
        cli.write_json(path, {"test": 2})
    assert json.loads(path.read_text()) == {"test": 1}


def test_load_hashes_and_decodes_same_buffer_despite_file_replacement(tmp_path, monkeypatch):
    path = tmp_path / "plan.json"
    original = b'{"reviewed":true}'
    path.write_bytes(original)
    approved_sha = hashlib.sha256(original).hexdigest()
    original_open = type(path).open
    calls = []
    def opening(self, *args, **kwargs):
        if self == path:
            calls.append(1)
            if len(calls) > 1:
                with original_open(self, "wb") as output:
                    output.write(b'{"reviewed":false}')
        return original_open(self, *args, **kwargs)
    monkeypatch.setattr(type(path), "open", opening)
    assert cli.load_json(path, approved_sha) == {"reviewed": True}
    assert len(calls) == 1
