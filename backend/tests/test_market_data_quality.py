from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.services.market_data_quality_service import (
    audit_database, audit_dates, load_universe, readonly_connection,
)
from scripts.audit_market_data_quality import configured_database, main


@pytest.fixture
def db_file(tmp_path):
    path = tmp_path / "source.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE stock_basic (ts_code TEXT PRIMARY KEY, list_date TEXT, list_status TEXT)")
        conn.executemany("INSERT INTO stock_basic VALUES (?, ?, ?)", [
            ("000001.SZ", "19910403", "L"), ("600001.SH", "20000101", "L"),
            ("000001.SH", None, None), ("300001.SZ", "20261104", "L")])
        # No primary key deliberately: audit must detect corrupt duplicate imports.
        conn.execute("CREATE TABLE daily_quote (ts_code TEXT, trade_date TEXT, open REAL, high REAL, low REAL, close REAL, pre_close REAL, pct_chg REAL, vol REAL, amount REAL, turnover_rate REAL)")
        conn.execute("INSERT INTO daily_quote VALUES ('000001.SZ','20261102',10,11,9,10,10,0,100,NULL,NULL)")
    return path


def audit(path, **kwargs):
    with readonly_connection("sqlite:///" + str(path), path.parent) as (conn, _):
        return audit_database(conn, dates=["20261102", "20261103"],
                              calendar={"status": "provided_calendar"}, **kwargs)


def test_missing_denominator_never_becomes_pass(db_file):
    r = audit(db_file)
    assert all(d["coverage_ratio"] is None and not d["scoring_allowed"] for d in r["days"])
    assert r["days"][1]["raw_rows"] == 0
    assert r["days"][0]["missing_codes"] == ["600001.SH"]
    assert r["days"][0]["fields"]["amount"]["ratio"] == 0
    assert r["master_inventory"]["code_pattern_excluded"] == ["000001.SH"]


def test_incomplete_master_does_not_hide_quote_fields(db_file):
    with sqlite3.connect(db_file) as conn:
        conn.execute("UPDATE stock_basic SET list_status=NULL, list_date=NULL")
    day = audit(db_file)["days"][0]
    assert day["scoped_rows"] == 1
    assert day["fields"]["amount"]["valid"] == 0
    assert day["expected_count"] is None


def test_provided_universe_missing_vs_suspended(db_file):
    # Independent universe excludes suspended 600001.SH on day 1, includes day 2.
    r = audit(db_file, universe={"20261102": {"000001.SZ"}, "20261103": {"000001.SZ", "600001.SH"}},
              universe_info={"control_totals_verified": True})
    assert r["days"][0]["coverage_ratio"] == 1
    assert r["days"][0]["scoring_allowed"]
    assert not r["days"][0]["amount_metrics_allowed"]
    assert r["days"][1]["coverage_ratio"] == 0
    assert r["days"][1]["quality_status"] == "fail"


def test_bad_ohlc_and_duplicate_are_invalid(db_file):
    with sqlite3.connect(db_file) as conn:
        conn.execute("UPDATE daily_quote SET high=8, amount=-1")
        conn.execute("INSERT INTO daily_quote SELECT * FROM daily_quote")
    day = audit(db_file)["days"][0]
    assert day["duplicate_codes"] == 1
    assert day["valid_core_codes"] == 0
    assert {"ohlc_order", "amount", "duplicate_key"} <= set(day["invalid_rows"][0]["issues"])


def test_zero_price_unknown_master_and_illegal_db_date(db_file):
    with sqlite3.connect(db_file) as conn:
        conn.execute("INSERT INTO daily_quote VALUES ('000099.SZ','20261102',0,1,1,1,1,0,1,1,1)")
        conn.execute("INSERT INTO daily_quote (ts_code,trade_date) VALUES ('000001.SZ','20261301')")
    r = audit(db_file)
    assert r["invalid_date_rows"] == [{"trade_date": "20261301", "rows": 1}]
    assert "000099.SZ" in r["days"][0]["unknown_master_codes"]
    assert "open" in r["days"][0]["invalid_rows"][0]["issues"]


def test_extra_unknown_share_blocks_supplied_universe(db_file):
    with sqlite3.connect(db_file) as conn:
        conn.execute("INSERT INTO daily_quote VALUES ('000099.SZ','20261102',1,1,1,1,1,0,1,1,1)")
    r = audit(db_file, universe={"20261102": {"000001.SZ"}}, universe_info={"control_totals_verified": True})
    assert r["days"][0]["unexpected_a_share_codes"] == ["000099.SZ"]
    assert not r["days"][0]["scoring_allowed"]


def test_unverified_small_supplied_universe_cannot_pass(db_file):
    r = audit(db_file, universe={"20261102": {"000001.SZ"}})
    assert r["days"][0]["coverage_ratio"] == 1
    assert not r["days"][0]["scoring_allowed"]


def test_duplicate_threshold_blocks_otherwise_high_coverage(db_file):
    with sqlite3.connect(db_file) as conn:
        conn.executemany("INSERT INTO daily_quote VALUES (?,'20261102',1,1,1,1,1,0,1,1,1)",
                         [(f"600{i:03d}.SH",) for i in range(100)])
        conn.execute("INSERT INTO daily_quote SELECT * FROM daily_quote WHERE ts_code='600001.SH'")
    u = {"000001.SZ"} | {f"600{i:03d}.SH" for i in range(100)}
    r = audit(db_file, universe={"20261102": u}, universe_info={"control_totals_verified": True})
    day = r["days"][0]
    assert day["coverage_ratio"] >= .95 and day["anomaly_ratio"] > .001
    assert not day["scoring_allowed"]


def test_nonfinite_is_json_safe(db_file):
    with sqlite3.connect(db_file) as conn:
        conn.execute("UPDATE daily_quote SET close=?, vol=?", (float("inf"), float("-inf")))
    r = audit(db_file)
    assert r["days"][0]["valid_core_codes"] == 0
    json.dumps(r, allow_nan=False)


def test_missing_columns_are_reported(tmp_path):
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE stock_basic (ts_code TEXT)")
        conn.execute("CREATE TABLE daily_quote (ts_code TEXT, trade_date TEXT)")
        conn.execute("INSERT INTO daily_quote VALUES ('000001.SZ','20261102')")
    r = audit(path)
    assert "amount" in r["missing_schema_fields"]
    assert r["days"][0]["valid_core_codes"] == 0


def test_db_enforces_readonly_and_does_not_create_file(db_file, tmp_path):
    before = hashlib.sha256(db_file.read_bytes()).hexdigest()
    with readonly_connection("sqlite:///" + str(db_file), tmp_path) as (conn, _):
        with pytest.raises(DBAPIError):
            conn.execute(text("DELETE FROM daily_quote"))
    assert hashlib.sha256(db_file.read_bytes()).hexdigest() == before
    with pytest.raises(ValueError):
        with readonly_connection("sqlite:///missing.db", tmp_path):
            pass
    assert not (tmp_path / "missing.db").exists()


def test_calendar_includes_entirely_missing_session_and_holiday(tmp_path):
    calendar = tmp_path / "calendar.csv"
    calendar.write_text("trade_date,is_open\n20261030,1\n20261031,0\n20261101,0\n20261102,1\n20261103,0\n", encoding="utf-8")
    dates, info = audit_dates("20261103", 2, calendar)
    assert dates == ["20261030", "20261102"]
    assert info["status"] == "provided_calendar"
    calendar.write_text("trade_date,is_open\n20261101,0\n20261103,1\n", encoding="utf-8")
    with pytest.raises(ValueError):
        audit_dates("20261103", 2, calendar)


def test_weekday_grid_does_not_claim_trading_calendar(db_file):
    dates, info = audit_dates("20261103", 2)
    assert dates == ["20261102", "20261103"]
    with readonly_connection("sqlite:///" + str(db_file), db_file.parent) as (conn, _):
        r = audit_database(conn, dates=dates, calendar=info, universe={d: {"000001.SZ"} for d in dates})
    assert not r["days"][0]["scoring_allowed"]


def test_universe_requires_complete_dates_known_states_no_duplicates(tmp_path):
    path = tmp_path / "universe.csv"
    header = "trade_date,ts_code,security_type,is_listed,is_trading\n"
    path.write_text(header + "20261102,000001.SZ,a_share,1,1\n20261102,600001.SH,a_share,1,0\n", encoding="utf-8")
    u, info = load_universe(path, ["20261102"])
    assert u == {"20261102": {"000001.SZ"}}
    assert info["sha256"]
    with pytest.raises(ValueError):
        load_universe(path, ["20261102", "20261103"])
    path.write_text(header + "20261102,000001.SZ,a_share,1,unknown\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_universe(path, ["20261102"])


def test_independent_control_totals_reject_incomplete_universe(tmp_path):
    path = tmp_path / "universe.csv"
    path.write_text("trade_date,ts_code,security_type,is_listed,is_trading\n20261102,000001.SZ,a_share,1,1\n", encoding="utf-8")
    controls = tmp_path / "controls.csv"
    controls.write_text("trade_date,expected_count,source_url\n20261102,5500,https://example.org/source\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_universe(path, ["20261102"], controls)
    controls.write_text("trade_date,expected_count,source_url\n20261102,1,https://example.org/source\n", encoding="utf-8")
    _, info = load_universe(path, ["20261102"], controls)
    assert info["control_totals_verified"]


@pytest.mark.parametrize("body", ["20261102,1\n20261102,0\n", "20261102,unknown\n"])
def test_invalid_calendar_states_and_duplicates(tmp_path, body):
    path = tmp_path / "calendar.csv"
    path.write_text("trade_date,is_open\n" + body, encoding="utf-8")
    with pytest.raises(ValueError):
        audit_dates("20261102", 1, path)


def test_cli_config_precedence_no_bootstrap_and_output(db_file, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///" + str(db_file))
    url, source = configured_database(tmp_path)
    assert url.endswith(str(db_file)) and source == "process environment DATABASE_URL"
    prefix = tmp_path / "report"
    assert main(["--days", "2", "--end-date", "20261103", "--output-prefix", str(prefix)]) == 2
    assert prefix.with_suffix(".md").exists()
    r = json.loads(prefix.with_suffix(".json").read_text())
    assert r["summary"]["empty_slots"] == 1
    assert "password" not in capsys.readouterr().out


def test_import_does_not_load_application_database():
    result = subprocess.run([sys.executable, "-c", "import sys; import scripts.audit_market_data_quality; assert 'app.database' not in sys.modules"],
                            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_connection_error_never_echoes_secret(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://secret:do-not-print@127.0.0.1:1/none")
    assert main(["--days", "1", "--output-prefix", str(tmp_path / "report")]) == 1
    assert "do-not-print" not in capsys.readouterr().err
