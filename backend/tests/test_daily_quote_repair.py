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
                  pre_close=10., change=0., pct_chg=0., vol=1000., amount=10000.,
                  turnover_rate=None, float_share=None)
    return {**values, **changes}


def snapshot(rows):
    from app.services.source_identity import IDENTITY_POLICY
    rows = [{**r, "source_identity": {"provider": "baostock", "raw_code": r["ts_code"].split(".")[1].lower() + "." + r["ts_code"].split(".")[0],
                                     "trade_date": r["trade_date"], "response_sha256": "1" * 64}} for r in rows]
    dates = sorted({r["trade_date"] for r in rows}) or ["20261008", "20261009"]
    return {"version": SNAPSHOT_VERSION, "id": "fixture-snapshot", "dates": dates,
            "codes": ["000001.SZ"], "rows": rows, "requests": [], "outcome": "success", "source": {
                "name": "baostock", "volume_unit": "share", "amount_unit": "cny",
                "identity_policy": IDENTITY_POLICY,
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
    assert item["new_values"]["vol"] == 10 and item["new_values"]["amount"] == 10
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
    with pytest.raises(RepairError, match="无效行情"):
        plan(db, rows=[bad_row])


def test_duplicate_source_keys_rejected_and_empty_snapshot_does_not_delete(db):
    initial = states(db)
    with pytest.raises(RepairError, match="网格"):
        plan(db, rows=[row(), row()])
    with pytest.raises(RepairError, match="网格"):
        plan(db, rows=[])
    assert states(db) == initial


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


def test_unapplied_legacy_plan_cannot_bypass_upstream_identity_gate(db):
    proposal = plan(db)
    proposal["policy"].pop("input_validation")
    proposal.pop("input_grid")
    proposal.pop("input_grid_digest")
    proposal["source"].pop("identity_policy")
    validate_plan(proposal, allow_legacy=True)  # Archived audit proofs remain readable.
    initial = states(db)
    manifest = backup(db)
    with pytest.raises(RepairError, match="原始身份"):
        with writer_connection(db[0], str(db[1])) as conn:
            apply_repair_plan(conn, proposal, manifest)
    assert states(db) == initial


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


@pytest.mark.parametrize('volume,amount', [(1000, 20000), (0, 10000), (1000, 0)])
def test_new_source_rejects_impossible_vwap_and_zero_pair(volume, amount):
    from app.services.daily_quote_repair_service import normalized_source_row
    snap = snapshot([row(vol=volume, amount=amount)])
    with pytest.raises(RepairError, match='均价|零量|量额'):
        normalized_source_row(snap['rows'][0], snap['source'])


@pytest.mark.parametrize('defect', ['missing_row', 'duplicate_code', 'duplicate_row', 'invalid_row'])
def test_success_label_cannot_replace_complete_valid_input_grid(db, defect):
    snap = snapshot([row(amount=10000), row(day='20261009', amount=10000)])
    if defect == 'missing_row':
        snap['rows'].pop()
    elif defect == 'duplicate_code':
        snap['codes'].append(snap['codes'][0])
    elif defect == 'duplicate_row':
        snap['rows'][1] = deepcopy(snap['rows'][0])
    else:
        snap['rows'][1]['pre_close'] = None
    snap['valid_row_count'] = 2  # Deliberately forged status/count metadata.
    with readonly_connection(db[0], db[1]) as (conn, _):
        with pytest.raises(RepairError, match='网格|完整|重复|有效'):
            make_repair_plan(conn, snap)


def test_plan_requested_cells_cannot_be_forged(db):
    proposal = plan(db, rows=[row(amount=10000), row(day='20261009', amount=10000)])
    proposal['summary']['requested_cells'] += 1
    with pytest.raises(RepairError, match='网格|汇总|完整'):
        validate_plan(proposal)


def test_removed_plan_item_cannot_be_relabelled_as_unchanged(db):
    proposal = plan(db, rows=[row(amount=10000), row(day='20261009', amount=10000)])
    removed = proposal['items'].pop()
    field = 'inserts' if removed['operation'] == 'insert' else 'updates'
    proposal['summary'][field] -= 1
    proposal['summary']['unchanged'] += 1
    with pytest.raises(RepairError, match='网格|证明|完整'):
        validate_plan(proposal)


def test_cli_forged_success_with_missing_cell_never_writes_plan(db, monkeypatch, capsys):
    monkeypatch.setenv('DATABASE_URL', db[0])
    source = db[1] / 'forged-success.json'
    forged = snapshot([row(amount=10000)])
    forged['dates'] = ['20261008', '20261009']
    source.write_text(json.dumps(forged))
    output = db[1] / 'forged-plan.json'
    assert cli.main(['plan', '--snapshot', str(source), '--output', str(output)]) == 1
    capsys.readouterr()
    assert not output.exists()


@pytest.mark.parametrize('name,vol,amount', [('baostock', 1000, 10000), ('akshare', 10, 10000), ('tushare', 10, 10)])
def test_volume_price_check_uses_declared_units_before_checking_average(name, vol, amount):
    from app.services.daily_quote_repair_service import normalized_source_row, SPECS
    source = dict(name=name, volume_unit=SPECS[name][0], amount_unit=SPECS[name][1], data_stage='final', adjustment='none')
    canonical_row = normalized_source_row(row(vol=vol, amount=amount), source)
    assert canonical_row['vol'] == 10 and canonical_row['amount'] == 10


def test_zero_volume_and_zero_amount_are_valid_together():
    from app.services.daily_quote_repair_service import normalized_source_row
    source = snapshot([row(vol=0, amount=0)])
    result = normalized_source_row(source['rows'][0], source['source'])
    assert result['vol'] == result['amount'] == 0


@pytest.mark.parametrize('tampering', ['missing_cell', 'duplicate_cell', 'bad_digest', 'forged_skipped', 'wrong_raw_hash'])
def test_full_grid_proof_rejects_tampering(db, tampering):
    proposal = plan(db)
    if tampering == 'missing_cell':
        proposal['input_grid'].pop()
    elif tampering == 'duplicate_cell':
        proposal['input_grid'][1] = deepcopy(proposal['input_grid'][0])
    elif tampering == 'bad_digest':
        proposal['input_grid_digest'] = '0' * 64
    elif tampering == 'forged_skipped':
        proposal['skipped'].append(dict(ts_code='000001.SZ', trade_date='20261008', reason='optional_field_loss', fields=['float_share']))
    else:
        proposal['input_grid'][0]['raw_hash'] = '0' * 64
    with pytest.raises(RepairError, match='网格|证明|跳过'):
        validate_plan(proposal)


def test_full_grid_proves_unchanged_and_optional_skip_without_clearing(db):
    from app.services.daily_quote_repair_service import normalized_source_row
    snap = snapshot([row(), row(day='20261009')])
    normalized = [normalized_source_row(r, snap['source']) for r in snap['rows']]
    with writer_connection(db[0], str(db[1])) as conn:
        conn.execute(update(Q).where(Q.c.ts_code == '000001.SZ').values(**{k: v for k, v in normalized[0].items() if k not in ('ts_code', 'trade_date')}))
        conn.execute(insert(Q).values(**{**normalized[1], 'float_share': 200}))
    proposal = plan(db)
    assert proposal['summary'] == dict(updates=0, inserts=0, unchanged=1, skipped=1, requested_cells=2)
    assert [r['disposition'] for r in proposal['input_grid']] == ['unchanged', 'skipped']
    validate_plan(proposal)
    initial = states(db)
    with writer_connection(db[0], str(db[1])) as conn:
        assert apply_repair_plan(conn, proposal, None)['status'] == 'no_changes'
    assert states(db) == initial
    tampered = deepcopy(proposal)
    tampered['input_grid'][1]['proof']['old_values']['float_share'] = None
    with pytest.raises(RepairError, match='保护|证明'):
        validate_plan(tampered)


def test_unapplied_identity_only_plan_requires_new_grid_proof(db):
    proposal = plan(db)
    proposal['policy'].pop('input_validation')
    proposal.pop('input_grid')
    proposal.pop('input_grid_digest')
    validate_plan(proposal, allow_legacy=True)
    manifest = backup(db)
    with pytest.raises(RepairError, match='完整输入网格'):
        with writer_connection(db[0], str(db[1])) as conn:
            apply_repair_plan(conn, proposal, manifest)


def test_mixed_grid_audit_retains_unchanged_and_protected_skip_evidence(db):
    from app.services.daily_quote_repair_service import normalized_source_row
    source = snapshot([row(), row(day='20261009'), row(day='20261012')])
    normalized = [normalized_source_row(raw, source['source']) for raw in source['rows']]
    with writer_connection(db[0], str(db[1])) as conn:
        conn.execute(update(Q).where(Q.c.ts_code == '000001.SZ').values(**{key: value for key, value in normalized[0].items() if key not in ('ts_code', 'trade_date')}))
        conn.execute(insert(Q).values(**{**normalized[1], 'float_share': 200}))
    initial = states(db)
    proposal = plan(db, rows=[row(), row(day='20261009'), row(day='20261012')])
    assert proposal['summary'] == dict(updates=0, inserts=1, unchanged=1, skipped=1, requested_cells=3)
    manifest = backup(db)
    with writer_connection(db[0], str(db[1])) as conn:
        batch = apply_repair_plan(conn, proposal, manifest)['batch_id']
    with readonly_connection(db[0], db[1]) as (conn, _):
        assert verify_repair_batch(conn, batch)['matches']
        stored = conn.execute(select(B).where(B.c.id == batch)).mappings().one()
        assert stored['summary']['input_grid_digest'] == proposal['input_grid_digest']
        assert len(stored['summary']['input_grid']) == 3
    manifest = backup(db)
    with writer_connection(db[0], str(db[1])) as conn:
        rollback_repair_batch(conn, batch, manifest)
    assert states(db) == initial


def test_legacy_applied_batch_with_old_volume_rules_remains_verifiable_and_reversible(db):
    """An archived v1 batch is validated by its historical rules, never re-applied."""
    import uuid
    from app.services import daily_quote_repair_service as service
    legacy = plan(db)
    legacy['policy'].pop('input_validation')
    legacy.pop('input_grid')
    legacy.pop('input_grid_digest')
    legacy['source'].pop('identity_policy')
    for item in legacy['items']:
        raw = item['source_json']['raw_values']
        raw['amount'] = 20000  # Old fixture implies VWAP20 outside OHLC9..11.
        new = service.normalized_source_row(raw, legacy['source'], enforce_market_consistency=False)
        raw_hash = service.digest(raw)
        item['source_json'].update(raw_hash=raw_hash, field_source={field: raw_hash for field in service.VALUE_FIELDS})
        item['new_values'], item['new_hash'] = new, service.digest(new)
        old = item['old_values']
        item['changed_fields'] = [field for field in service.VALUE_FIELDS if old is None or old[field] != new[field]]
    service.validate_plan(legacy, allow_legacy=True)
    initial = states(db)
    batch, now = str(uuid.uuid4()), service.utc_now()
    audits = [dict(id=str(uuid.uuid4()), batch_id=batch, sequence=index, ts_code=item['ts_code'],
        trade_date=item['trade_date'], operation=item['operation'], old_values=item['old_values'],
        new_values=item['new_values'], changed_fields=item['changed_fields'], old_hash=item['old_hash'],
        new_hash=item['new_hash'], source_json=item['source_json'], applied_at=now, rolled_back_at=None)
        for index, item in enumerate(legacy['items'])]
    summary = {**legacy['summary'], 'source':legacy['source'], 'snapshot_id':legacy['snapshot_id'],
        'snapshot_hash':legacy['snapshot_hash'], 'audit_hash':service._audit_digest(audits)}
    with writer_connection(db[0], str(db[1])) as conn:
        identity = service.database_identity(conn)
        conn.execute(insert(B).values(id=batch, plan_hash=service.digest(legacy), status='applied',
            database_identity=identity, policy=legacy['policy'], summary=summary, created_at=now, applied_at=now))
        for item in legacy['items']:
            if item['operation'] == 'insert':
                conn.execute(insert(Q).values(**item['new_values']))
            else:
                conn.execute(update(Q).where(Q.c.ts_code == item['ts_code'], Q.c.trade_date == item['trade_date']).values(
                    **{key:value for key,value in item['new_values'].items() if key in service.VALUE_FIELDS}))
        conn.execute(insert(A), audits)
    with readonly_connection(db[0], db[1]) as (conn, _):
        assert verify_repair_batch(conn, batch)['matches']
    with writer_connection(db[0], str(db[1])) as conn:
        assert apply_repair_plan(conn, legacy, None)['status'] == 'already_applied'
    manifest = backup(db)
    with writer_connection(db[0], str(db[1])) as conn:
        rollback_repair_batch(conn, batch, manifest)
    assert states(db) == initial
    with readonly_connection(db[0], db[1]) as (conn, _):
        assert verify_repair_batch(conn, batch)['matches']


def _proposal_with_nonwrite_cell(db, disposition):
    from app.services.daily_quote_repair_service import normalized_source_row
    source = snapshot([row(), row(day='20261009')])
    canonical_row = normalized_source_row(source['rows'][0], source['source'])
    with writer_connection(db[0], str(db[1])) as conn:
        if disposition == 'unchanged':
            conn.execute(update(Q).where(Q.c.ts_code == '000001.SZ').values(
                **{key:value for key,value in canonical_row.items() if key not in ('ts_code','trade_date')}))
        else:
            conn.execute(update(Q).where(Q.c.ts_code == '000001.SZ').values(float_share=200))
    proposal = plan(db)
    assert proposal['input_grid'][0]['disposition'] == disposition
    assert len(proposal['items']) == 1 and proposal['items'][0]['operation'] == 'insert'
    return proposal


def test_forged_unchanged_proof_is_rejected_against_actual_locked_database(db):
    from app.services import daily_quote_repair_service as service
    proposal = plan(db)
    removed = proposal['items'].pop(0)
    assert removed['operation'] == 'update'
    proposal['summary']['updates'] = 0
    proposal['summary']['unchanged'] = 1
    proposal['input_grid'][0].update(disposition='unchanged', proof={
        'raw_values':removed['source_json']['raw_values'], 'old_values':removed['new_values']})
    proposal['input_grid_digest'] = service._input_grid_digest(proposal)
    validate_plan(proposal)  # Structurally consistent, but the old-state claim is false.
    initial, manifest = states(db), backup(db)
    with pytest.raises(RepairError, match='冲突'):
        with writer_connection(db[0], str(db[1])) as conn:
            apply_repair_plan(conn, proposal, manifest)
    assert states(db) == initial
    with readonly_connection(db[0], db[1]) as (conn, _):
        assert conn.execute(select(B)).all() == [] and conn.execute(select(A)).all() == []


@pytest.mark.parametrize('disposition', ['unchanged', 'skipped'])
def test_nonwrite_drift_before_fresh_backup_still_blocks_apply(db, disposition):
    proposal = _proposal_with_nonwrite_cell(db, disposition)
    with writer_connection(db[0], str(db[1])) as conn:
        conn.execute(update(Q).where(Q.c.ts_code == '000001.SZ').values(close=10.5))
    drifted, manifest = states(db), backup(db)  # Fresh fingerprint must not hide plan drift.
    with pytest.raises(RepairError, match='冲突'):
        with writer_connection(db[0], str(db[1])) as conn:
            apply_repair_plan(conn, proposal, manifest)
    assert states(db) == drifted


@pytest.mark.parametrize('disposition', ['unchanged', 'skipped'])
def test_new_batch_verify_and_rollback_check_nonwrite_grid_state(db, disposition):
    proposal = _proposal_with_nonwrite_cell(db, disposition)
    manifest = backup(db)
    with writer_connection(db[0], str(db[1])) as conn:
        batch = apply_repair_plan(conn, proposal, manifest)['batch_id']
    with writer_connection(db[0], str(db[1])) as conn:
        conn.execute(update(Q).where(Q.c.ts_code == '000001.SZ', Q.c.trade_date == '20261008').values(close=10.5))
    with readonly_connection(db[0], db[1]) as (conn, _):
        result = verify_repair_batch(conn, batch)
    assert result['audit_integrity'] and not result['matches']
    assert result['verification_scope'] == 'full_input_grid'
    assert result['mismatches'] == [{'ts_code':'000001.SZ','trade_date':'20261008','disposition':disposition}]
    changed, manifest = states(db), backup(db)
    with pytest.raises(RepairError, match='冲突'):
        with writer_connection(db[0], str(db[1])) as conn:
            rollback_repair_batch(conn, batch, manifest)
    assert states(db) == changed


def test_unapplied_empty_legacy_plan_is_not_reported_as_valid_no_changes(db):
    proposal = plan(db)
    proposal['items'] = []
    proposal['summary'].update(updates=0, inserts=0, unchanged=2)
    proposal['policy'].pop('input_validation')
    proposal.pop('input_grid')
    proposal.pop('input_grid_digest')
    proposal['source'].pop('identity_policy')
    with pytest.raises(RepairError, match='原始身份|完整输入网格'):
        with writer_connection(db[0], str(db[1])) as conn:
            apply_repair_plan(conn, proposal, None)


def test_forged_new_empty_change_set_must_check_claimed_unchanged_state(db):
    from app.services import daily_quote_repair_service as service
    proposal = plan(db)
    items = proposal['items']
    proposal['items'] = []
    proposal['summary'].update(updates=0, inserts=0, unchanged=2)
    by_key = {(r['ts_code'],r['trade_date']):r for r in items}
    for cell in proposal['input_grid']:
        removed = by_key[(cell['ts_code'],cell['trade_date'])]
        cell.update(disposition='unchanged',proof={'raw_values':removed['source_json']['raw_values'],
                                                 'old_values':removed['new_values']})
    proposal['input_grid_digest'] = service._input_grid_digest(proposal)
    validate_plan(proposal)
    with pytest.raises(RepairError, match='冲突'):
        with writer_connection(db[0], str(db[1])) as conn:
            apply_repair_plan(conn, proposal, None)


@pytest.mark.parametrize('disposition', ['unchanged', 'skipped'])
def test_trigger_side_effect_on_nonwrite_grid_row_rolls_back_entire_apply(db, disposition):
    proposal = _proposal_with_nonwrite_cell(db, disposition)
    with writer_connection(db[0], str(db[1])) as conn:
        conn.exec_driver_sql("CREATE TRIGGER mutate_nonwrite AFTER INSERT ON daily_quote "
            "WHEN NEW.ts_code='000001.SZ' AND NEW.trade_date='20261009' "
            "BEGIN UPDATE daily_quote SET close=10.5 WHERE ts_code='000001.SZ' AND trade_date='20261008'; END")
    initial, manifest = states(db), backup(db)
    with pytest.raises(RepairError, match='冲突'):
        with writer_connection(db[0], str(db[1])) as conn:
            apply_repair_plan(conn, proposal, manifest)
    assert states(db) == initial
    with readonly_connection(db[0], db[1]) as (conn, _):
        assert conn.execute(select(B)).all() == [] and conn.execute(select(A)).all() == []
