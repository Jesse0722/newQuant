"""CLI tests use synthetic evidence and disposable databases, never market data."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import subprocess
import sys

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from scripts import audit_market_data_quality as cli
from test_market_universe_evidence import write_synthetic_bundle


@pytest.fixture
def case(tmp_path, monkeypatch):
    database = tmp_path / "source.db"
    with sqlite3.connect(database) as conn:
        conn.execute("CREATE TABLE stock_basic(ts_code TEXT, list_date TEXT, list_status TEXT)")
        conn.execute("INSERT INTO stock_basic VALUES ('000001.SZ','19910403','L')")
        conn.execute("CREATE TABLE daily_quote(ts_code TEXT,trade_date TEXT,open REAL,high REAL,low REAL,close REAL,pre_close REAL,pct_chg REAL,vol REAL,amount REAL,turnover_rate REAL)")
        conn.execute("INSERT INTO daily_quote VALUES ('000001.SZ','20261102',10,11,9,10,10,0,100,100,1)")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///" + str(database))
    calendar = tmp_path / "calendar.csv"
    calendar.write_text("trade_date,is_open\n20261102,1\n", encoding="utf-8")
    universe, controls, manifest = write_synthetic_bundle(
        tmp_path / "package", {"20261102": {"000001.SZ"}})
    return {"database": database, "calendar": calendar, "universe": universe,
            "controls": controls, "manifest": manifest, "prefix": tmp_path / "output" / "report"}


def arguments(case, *, evidence=True):
    argv = ["--end-date", "20261102", "--days", "1", "--calendar-csv", str(case["calendar"]),
            "--universe-csv", str(case["universe"]), "--universe-counts-csv", str(case["controls"]),
            "--output-prefix", str(case["prefix"])]
    if evidence:
        argv += ["--universe-evidence-manifest", str(case["manifest"]),
                 "--universe-evidence-sha256", hashlib.sha256(case["manifest"].read_bytes()).hexdigest()]
    return argv


def outputs(case):
    return case["prefix"].with_suffix(".json"), case["prefix"].with_suffix(".md")


def test_full_evidence_cli_outputs_effective_qualification_and_private_files(case, capsys, monkeypatch):
    synced = []
    original = os.fsync
    def syncing(fd):
        synced.append(os.fstat(fd).st_ino)
        return original(fd)
    monkeypatch.setattr(cli.os, "fsync", syncing)
    assert cli.main(arguments(case)) == 0
    json_path, markdown_path = outputs(case)
    report = json.loads(json_path.read_text())
    assert report["universe"]["counts_match"] is True
    assert report["universe"]["evidence"]["bound"] is True
    assert report["universe"]["control_totals_verified"] is True
    assert report["summary"]["scoring_allowed"] is True
    assert report["summary"]["amount_metrics_allowed"] is True
    assert {path.stat().st_ino for path in outputs(case)} <= set(synced)
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in outputs(case))
    assert "全市场证据资格：`True`" in markdown_path.read_text()
    assert json.loads(capsys.readouterr().out)["summary"] == report["summary"]


@pytest.mark.parametrize("scope,evidence,bound", [
    ("security_subset", True, True), ("full_market_point_in_time", False, False),
])
def test_subset_or_legacy_counts_remain_diagnostic(case, scope, evidence, bound):
    manifest = json.loads(case["manifest"].read_text())
    manifest["scope"] = scope
    case["manifest"].write_text(json.dumps(manifest))
    assert cli.main(arguments(case, evidence=evidence)) == 2
    report = json.loads(outputs(case)[0].read_text())
    assert report["universe"]["counts_match"] is True
    assert report["universe"]["evidence"]["bound"] is bound
    assert report["universe"]["control_totals_verified"] is False
    assert report["summary"]["scoring_allowed"] is False
    assert report["summary"]["amount_metrics_allowed"] is False


def test_amount_failure_is_explicit_without_changing_price_exit_semantics(case, capsys):
    with sqlite3.connect(case["database"]) as conn:
        conn.execute("UPDATE daily_quote SET amount=200")
    assert cli.main(arguments(case)) == 0
    report = json.loads(outputs(case)[0].read_text())
    assert report["summary"]["scoring_allowed"] is True
    assert report["summary"]["amount_metrics_allowed"] is False
    assert json.loads(capsys.readouterr().out)["summary"]["amount_metrics_allowed"] is False
    assert "amount_metrics_allowed）：`False`" in outputs(case)[1].read_text()


@pytest.mark.parametrize("removed", [
    "--universe-evidence-manifest", "--universe-evidence-sha256",
    "--universe-csv", "--universe-counts-csv",
])
def test_evidence_flags_require_pair_and_both_csvs(case, removed):
    argv = arguments(case)
    index = argv.index(removed)
    del argv[index:index + 2]
    assert cli.main(argv) == 1
    assert not any(path.exists() for path in outputs(case))


def test_wrong_manifest_pin_rejects_without_outputs(case):
    argv = arguments(case)
    argv[argv.index("--universe-evidence-sha256") + 1] = "0" * 64
    assert cli.main(argv) == 1
    assert not case["prefix"].parent.exists()


@pytest.mark.parametrize("suffix", [".json", ".md"])
def test_existing_report_is_preserved_and_new_counterpart_removed(case, suffix):
    case["prefix"].parent.mkdir()
    old = case["prefix"].with_suffix(suffix)
    old.write_bytes(b"FROZEN EVIDENCE")
    assert cli.main(arguments(case, evidence=False)) == 1
    assert old.read_bytes() == b"FROZEN EVIDENCE"
    assert not case["prefix"].with_suffix(".md" if suffix == ".json" else ".json").exists()


@pytest.mark.parametrize("suffix", [".json", ".md"])
def test_existing_symlink_and_target_are_preserved(case, suffix):
    case["prefix"].parent.mkdir()
    target = case["prefix"].parent / "frozen"
    target.write_bytes(b"FROZEN TARGET")
    link = case["prefix"].with_suffix(suffix)
    link.symlink_to(target)
    assert cli.main(arguments(case, evidence=False)) == 1
    assert link.is_symlink() and target.read_bytes() == b"FROZEN TARGET"
    assert not case["prefix"].with_suffix(".md" if suffix == ".json" else ".json").exists()


def test_second_reservation_race_preserves_winner_and_cleans_only_owned_file(case, monkeypatch):
    real_open = os.open
    markdown_path = outputs(case)[1]
    def competing_open(path, flags, *args, **kwargs):
        if Path(path) == markdown_path and flags & os.O_CREAT:
            markdown_path.write_bytes(b"OTHER WRITER")
        return real_open(path, flags, *args, **kwargs)
    monkeypatch.setattr(cli.os, "open", competing_open)
    assert cli.main(arguments(case, evidence=False)) == 1
    assert not outputs(case)[0].exists()
    assert markdown_path.read_bytes() == b"OTHER WRITER"


def test_second_body_write_failure_cleans_both_owned_files(case, monkeypatch):
    original = os.fdopen
    calls = []
    class FailedWrite:
        def __init__(self, stream):
            self.stream = stream
        def __enter__(self):
            return self
        def __exit__(self, *exc):
            self.stream.close()
        def write(self, _body):
            raise OSError("simulated second body write failure")
    def fdopen(fd, *args, **kwargs):
        stream = original(fd, *args, **kwargs)
        calls.append(fd)
        return FailedWrite(stream) if len(calls) == 2 else stream
    monkeypatch.setattr(cli.os, "fdopen", fdopen)
    assert cli.main(arguments(case, evidence=False)) == 1
    assert len(calls) == 2
    assert not any(path.exists() for path in outputs(case))


def test_sync_failure_cleans_both_owned_files(case, monkeypatch):
    original = os.fsync
    calls = []
    def failure(fd):
        calls.append(fd)
        if len(calls) == 2:
            raise OSError("simulated second fsync failure")
        return original(fd)
    monkeypatch.setattr(cli.os, "fsync", failure)
    assert cli.main(arguments(case, evidence=False)) == 1
    assert not any(path.exists() for path in outputs(case))


@pytest.mark.parametrize("replacement", ["file", "symlink"])
def test_cleanup_does_not_remove_replaced_path(case, monkeypatch, replacement):
    real_open = os.open
    json_path, markdown_path = outputs(case)
    target = case["prefix"].parent / "replacement-target"
    def replace_then_fail(path, flags, *args, **kwargs):
        if Path(path) == markdown_path and flags & os.O_CREAT:
            json_path.unlink()
            if replacement == "file":
                json_path.write_bytes(b"REPLACEMENT")
            else:
                target.write_bytes(b"REPLACEMENT")
                json_path.symlink_to(target)
            raise PermissionError("simulated reservation failure")
        return real_open(path, flags, *args, **kwargs)
    monkeypatch.setattr(cli.os, "open", replace_then_fail)
    assert cli.main(arguments(case, evidence=False)) == 1
    assert json_path.read_bytes() == b"REPLACEMENT"
    assert json_path.is_symlink() is (replacement == "symlink")
    assert not markdown_path.exists()


def test_replacement_during_write_prevents_success_and_preserves_replacement(case, monkeypatch):
    real_fsync = os.fsync
    json_path, markdown_path = outputs(case)
    calls = []
    def replacing(fd):
        calls.append(fd)
        if len(calls) == 2:
            json_path.unlink()
            json_path.write_bytes(b"REPLACEMENT AFTER WRITE")
        return real_fsync(fd)
    monkeypatch.setattr(cli.os, "fsync", replacing)
    assert cli.main(arguments(case, evidence=False)) == 1
    assert json_path.read_bytes() == b"REPLACEMENT AFTER WRITE"
    assert not markdown_path.exists()


@pytest.mark.parametrize("phase", ["json", "markdown"])
def test_all_rendering_finishes_before_any_output_is_created(case, monkeypatch, phase):
    if phase == "markdown":
        def failure(_report):
            raise ValueError("simulated render error")
        monkeypatch.setattr(cli, "render_markdown", failure)
    else:
        original = cli.audit_database
        def nonfinite(*args, **kwargs):
            report = original(*args, **kwargs)
            report["unexpected_nonfinite"] = float("inf")
            return report
        monkeypatch.setattr(cli, "audit_database", nonfinite)
    assert cli.main(arguments(case, evidence=False)) == 1
    assert not case["prefix"].parent.exists()


def test_cli_uses_database_readonly_and_preserves_database_bytes(case, monkeypatch):
    before = hashlib.sha256(case["database"].read_bytes()).hexdigest()
    original = cli.readonly_connection
    @contextmanager
    def checked(*args, **kwargs):
        with original(*args, **kwargs) as result:
            with pytest.raises(DBAPIError):
                result[0].execute(text("DELETE FROM daily_quote"))
            yield result
    monkeypatch.setattr(cli, "readonly_connection", checked)
    assert cli.main(arguments(case)) == 0
    assert hashlib.sha256(case["database"].read_bytes()).hexdigest() == before


def test_cli_connection_exception_does_not_echo_credentials(case, monkeypatch, capsys):
    @contextmanager
    def failure(*_args, **_kwargs):
        raise ValueError("postgresql://user:NEVER_PRINT_THIS@host.invalid/db")
        yield
    monkeypatch.setattr(cli, "readonly_connection", failure)
    assert cli.main(arguments(case, evidence=False)) == 1
    captured = capsys.readouterr()
    assert "NEVER_PRINT_THIS" not in captured.out + captured.err
    assert not any(path.exists() for path in outputs(case))


def test_cli_import_has_no_application_database_provider_or_scheduler_dependency():
    script = ("import sys; import scripts.audit_market_data_quality; "
              "assert not [n for n in sys.modules if n == 'app.database' "
              "or n.startswith('app.providers') or 'scheduler' in n]")
    result = subprocess.run([sys.executable, "-c", script],
                            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("scope,pin_valid,expected_exit", [
    ("full_market_point_in_time", True, 0), ("security_subset", True, 2),
    ("full_market_point_in_time", False, 1),
])
def test_real_cli_process_exit_codes(case, scope, pin_valid, expected_exit):
    manifest = json.loads(case["manifest"].read_text())
    manifest["scope"] = scope
    case["manifest"].write_text(json.dumps(manifest))
    argv = arguments(case)
    if not pin_valid:
        argv[argv.index("--universe-evidence-sha256") + 1] = "0" * 64
    result = subprocess.run([sys.executable, str(Path(cli.__file__)), *argv],
                            capture_output=True, text=True)
    assert result.returncode == expected_exit, result.stderr
    if expected_exit == 1:
        assert not any(path.exists() for path in outputs(case))
    else:
        assert all(path.is_file() for path in outputs(case))
        assert json.loads(result.stdout)["summary"]["scoring_allowed"] is (expected_exit == 0)
