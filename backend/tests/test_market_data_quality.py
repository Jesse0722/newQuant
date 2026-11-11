from __future__ import annotations

import hashlib
import copy
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
from test_market_universe_evidence import synthetic_universe


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


def test_provided_universe_missing_vs_suspended(db_file, tmp_path):
    # Independent universe excludes suspended 600001.SH on day 1, includes day 2.
    u, info = synthetic_universe(tmp_path / "synthetic", {"20261102": {"000001.SZ"}, "20261103": {"000001.SZ", "600001.SH"}})
    r = audit(db_file, universe=u, universe_info=info)
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


def test_extra_unknown_share_blocks_supplied_universe(db_file, tmp_path):
    with sqlite3.connect(db_file) as conn:
        conn.execute("INSERT INTO daily_quote VALUES ('000099.SZ','20261102',1,1,1,1,1,0,1,1,1)")
    u, info = synthetic_universe(tmp_path / "synthetic", {d: {"000001.SZ"} for d in ["20261102", "20261103"]})
    r = audit(db_file, universe=u, universe_info=info)
    assert r["days"][0]["unexpected_a_share_codes"] == ["000099.SZ"]
    assert not r["days"][0]["scoring_allowed"]


def test_unverified_small_supplied_universe_cannot_pass(db_file):
    r = audit(db_file, universe={d: {"000001.SZ"} for d in ["20261102", "20261103"]})
    assert r["days"][0]["coverage_ratio"] == 1
    assert not r["days"][0]["scoring_allowed"]


def test_duplicate_threshold_blocks_otherwise_high_coverage(db_file, tmp_path):
    with sqlite3.connect(db_file) as conn:
        conn.executemany("INSERT INTO daily_quote VALUES (?,'20261102',1,1,1,1,1,0,1,1,1)",
                         [(f"600{i:03d}.SH",) for i in range(100)])
        conn.execute("INSERT INTO daily_quote SELECT * FROM daily_quote WHERE ts_code='600001.SH'")
    u = {"000001.SZ"} | {f"600{i:03d}.SH" for i in range(100)}
    u, info = synthetic_universe(tmp_path / "synthetic", {d: u for d in ["20261102", "20261103"]})
    r = audit(db_file, universe=u, universe_info=info)
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
    assert info["counts_match"] is True
    assert info["control_totals_verified"] is False


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


@pytest.mark.parametrize('body', [
    'ts_code,ts_code\n000001.SZ,000002.SZ\n',
    'ts_code,\n000001.SZ,unused\n',
    'ts_code, note\n000001.SZ\n',
    'ts_code\n000001.SZ,extra\n',
])
def test_strict_csv_rejects_ambiguous_shape(tmp_path, body):
    from app.services.market_data_quality_service import read_csv
    path = tmp_path / 'bad-shape.csv'
    path.write_text(body)
    with pytest.raises(ValueError):
        read_csv(path, {'ts_code'})


def test_csv_hash_and_rows_use_one_file_read(tmp_path, monkeypatch):
    from app.services.market_data_quality_service import read_csv
    path = tmp_path / 'same-bytes.csv'
    raw = b'\xef\xbb\xbfts_code\n000001.SZ\n'
    path.write_bytes(raw)
    original = Path.open
    reads = []
    def opening(self, *args, **kwargs):
        if self == path:
            reads.append(args[0] if args else 'r')
        return original(self, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', opening)
    rows, provenance = read_csv(path, {'ts_code'})
    assert rows == [{'ts_code':'000001.SZ'}]
    assert provenance['sha256'] == hashlib.sha256(raw).hexdigest()
    assert len(reads) == 1


@pytest.mark.parametrize('code,kind,listed,trading', [
    ('', 'a_share','1','1'), ('000001.SH','a_share','1','1'),
    ('nonsense', 'a_share','1','1'), ('000001.SZ','a_shrae','1','1'),
    ('600000.SH','a_share','0','1'), ('600000.SH','other','0','1'),
])
def test_universe_validates_every_row_before_filtering(tmp_path, code, kind, listed, trading):
    path=tmp_path/'universe-bad-row.csv'
    path.write_text('trade_date,ts_code,security_type,is_listed,is_trading\n'
        '20261102,000002.SZ,a_share,1,1\n'+f'20261102,{code},{kind},{listed},{trading}\n')
    with pytest.raises(ValueError):
        load_universe(path,['20261102'])


@pytest.mark.parametrize('dates,universe', [
    (['20261102','20261102'],None),
    (['20261102','20261103'],{'20261102':{'000001.SZ'}}),
    (['20261102'],{'20261102':{'000001.SH'}}),
    (['20261102'],{'20261102':['000001.SZ']}),
])
def test_audit_entry_refuses_invalid_explicit_grid(db_file, dates, universe):
    with readonly_connection('sqlite:///'+str(db_file),db_file.parent) as (conn,_):
        with pytest.raises(ValueError):
            audit_database(conn,dates=dates,calendar={'status':'provided_calendar'},universe=universe)


def test_audit_marks_preclose_pct_contradiction(db_file):
    with sqlite3.connect(db_file) as conn:
        conn.execute('UPDATE daily_quote SET pre_close=5,pct_chg=0,amount=100')
    day=audit(db_file)['days'][0]
    assert day['valid_core_codes']==0
    assert 'pct_consistency' in day['invalid_rows'][0]['issues']


@pytest.mark.parametrize('volume,amount,issue',[(0,100,'volume_amount_zero_mismatch'),(100,0,'volume_amount_zero_mismatch'),(100,200,'vwap_out_of_range')])
def test_audit_reports_canonical_amount_contradictions(db_file,volume,amount,issue):
    with sqlite3.connect(db_file) as conn:
        conn.execute('UPDATE daily_quote SET vol=?,amount=?',(volume,amount))
    day=audit(db_file)['days'][0]
    assert issue in day['invalid_rows'][0]['issues']


def test_audit_numeric_strings_use_numeric_ohlc(tmp_path):
    path=tmp_path/'text-prices.db'
    with sqlite3.connect(path) as conn:
        conn.execute('CREATE TABLE stock_basic(ts_code TEXT)')
        conn.execute('CREATE TABLE daily_quote(ts_code TEXT,trade_date TEXT,open TEXT,high TEXT,low TEXT,close TEXT,pre_close TEXT,pct_chg TEXT,vol TEXT,amount TEXT,turnover_rate TEXT)')
        conn.execute("INSERT INTO daily_quote VALUES ('000001.SZ','20261102','10','9','1','10','10','0','100','100','1')")
    day=audit(path)['days'][0]
    assert day['valid_core_codes']==0
    assert 'ohlc_order' in day['invalid_rows'][0]['issues']


@pytest.fixture
def qualified(db_file, tmp_path):
    # Structural gate fixture only: this is not actual full-market evidence.
    universe, info = synthetic_universe(tmp_path / 'synthetic-qualified',
        {day: {'000001.SZ'} for day in ['20261102', '20261103']})
    with sqlite3.connect(db_file) as conn:
        conn.execute('UPDATE daily_quote SET amount=100,turnover_rate=1')
        conn.execute("INSERT INTO daily_quote SELECT ts_code,'20261103',open,high,low,close,pre_close,pct_chg,vol,amount,turnover_rate FROM daily_quote")
    return db_file, universe, info


def qualified_audit(qualified):
    path, universe, info = qualified
    return audit(path, universe=universe, universe_info=info)


def test_synthetic_qualified_prices_and_canonical_amount_pass(qualified):
    report = qualified_audit(qualified)
    assert report['version'] == 'market-data-quality-v1.1.0'
    assert report['summary']['scoring_allowed'] is True
    assert report['summary']['amount_metrics_allowed'] is True
    assert report['days'][0]['consistency']['amount_checked_rows'] == 1
    assert report['days'][0]['consistency']['amount_checkable_ratio'] == 1


@pytest.mark.parametrize('volume,amount,issue', [
    (0,100,'volume_amount_zero_mismatch'), (100,0,'volume_amount_zero_mismatch'),
    (100,200,'vwap_out_of_range'),
])
def test_qualified_amount_contradiction_only_vetoes_amount_gate(qualified, volume, amount, issue):
    with sqlite3.connect(qualified[0]) as conn:
        conn.execute("UPDATE daily_quote SET vol=?,amount=? WHERE trade_date='20261102'", (volume, amount))
    report = qualified_audit(qualified)
    day = report['days'][0]
    assert report['summary']['scoring_allowed'] is True
    assert report['summary']['amount_metrics_allowed'] is False
    assert day['fields']['amount']['valid'] == 1  # numerical completeness only
    assert day['consistency']['amount_inconsistent_rows'] == 1
    assert issue in day['invalid_rows'][0]['issues']


def test_zero_amount_and_volume_pair_is_checkable_without_division(qualified):
    with sqlite3.connect(qualified[0]) as conn:
        conn.execute('UPDATE daily_quote SET vol=0,amount=0')
    report = qualified_audit(qualified)
    assert report['summary']['amount_metrics_allowed'] is True
    assert report['days'][0]['consistency']['amount_checked_rows'] == 1


def test_null_volume_cannot_claim_amount_consistency(qualified):
    with sqlite3.connect(qualified[0]) as conn:
        conn.execute('UPDATE daily_quote SET vol=NULL')
    report = qualified_audit(qualified)
    assert report['summary']['scoring_allowed'] is True
    assert report['summary']['amount_metrics_allowed'] is False
    day = report['days'][0]
    assert day['fields']['amount']['ratio'] == 1
    assert day['consistency']['amount_uncheckable_rows'] == 1
    assert day['consistency']['amount_checkable_ratio'] == 0


def test_qualified_pct_mismatch_is_core_failure(qualified):
    with sqlite3.connect(qualified[0]) as conn:
        conn.execute("UPDATE daily_quote SET pre_close=5 WHERE trade_date='20261102'")
    report = qualified_audit(qualified)
    assert report['summary']['scoring_allowed'] is False
    day = report['days'][0]
    assert day['quality_status'] == 'fail'
    assert day['invalid_core_count'] == 1
    assert day['consistency']['pct_inconsistent_rows'] == 1


@pytest.mark.parametrize('pct,expected', [(0.029, True), (0.031, False)])
def test_pct_rounding_tolerance(qualified, pct, expected):
    with sqlite3.connect(qualified[0]) as conn:
        conn.execute('UPDATE daily_quote SET pct_chg=?', (pct,))
    assert qualified_audit(qualified)['summary']['scoring_allowed'] is expected


@pytest.mark.parametrize('mutation', [
    lambda i: i.update(control_totals_verified=1),
    lambda i: i.update(counts_match='true'),
    lambda i: i['evidence'].update(bound=1),
    lambda i: i['evidence'].update(inputs_bound='true'),
    lambda i: i['evidence'].update(originals_verified=1),
    lambda i: i['evidence'].update(scope='security_subset'),
    lambda i: i['evidence'].update(markets=['SH']),
    lambda i: i['evidence'].update(audit_dates=['20261102']),
    lambda i: i['evidence'].update(universe_sha256='0'*64),
    lambda i: i['evidence'].update(counts_sha256='0'*64),
    lambda i: i['controls']['requested_counts'].update({'20261102': 2}),
    lambda i: i['controls']['requested_counts'].update({'20261102': True}),
    lambda i: i['controls']['requested_counts'].pop('20261103'),
    lambda i: i.update(universe_digest='0'*64),
])
def test_qualification_metadata_cannot_be_reused_or_truthy(qualified, mutation):
    assert qualified_audit(qualified)['summary']['scoring_allowed'] is True
    metadata = copy.deepcopy(qualified[2])
    mutation(metadata)
    original = copy.deepcopy(metadata)
    report = audit(qualified[0], universe=qualified[1], universe_info=metadata)
    assert report['summary']['scoring_allowed'] is False
    assert report['universe']['control_totals_verified'] is False
    assert type(report['universe']['evidence']['bound']) is bool
    assert type(report['universe']['evidence']['inputs_bound']) is bool
    assert type(report['universe']['evidence']['originals_verified']) is bool
    assert metadata == original


def test_digest_binds_actual_codes_even_when_counts_identical(qualified):
    from app.services.market_data_quality_service import render_markdown
    from app.services.market_universe_evidence_service import normalized_universe_digest
    original_info = copy.deepcopy(qualified[2])
    universe = {day: {'000002.SZ'} for day in qualified[1]}
    with sqlite3.connect(qualified[0]) as conn:
        conn.execute("UPDATE daily_quote SET ts_code='000002.SZ'")
    report = audit(qualified[0], universe=universe, universe_info=qualified[2])
    assert report['days'][0]['coverage_ratio'] == 1
    assert report['summary']['scoring_allowed'] is False
    assert report['universe']['counts_match'] is True
    assert report['universe']['control_totals_verified'] is False
    assert report['universe']['evidence']['bound'] is False
    assert report['universe']['evidence']['inputs_bound'] is False
    assert report['universe']['universe_digest'] == normalized_universe_digest(universe)
    assert report['universe']['evidence']['universe_digest'] == normalized_universe_digest(universe)
    assert report['universe']['input_claims']['control_totals_verified'] is True
    assert qualified[2] == original_info
    report.update(database='test', generated_at='test',configuration_source='test')
    rendered = render_markdown(report)
    assert '全市场证据资格：`False`' in rendered
    assert '证据绑定：`False`' in rendered


def test_digest_binds_each_date_and_not_just_aggregate_codes(qualified, tmp_path):
    from app.services.market_universe_evidence_service import normalized_universe_digest
    original = {'20261102': {'000001.SZ'}, '20261103': {'000002.SZ'}}
    swapped = {'20261102': {'000002.SZ'}, '20261103': {'000001.SZ'}}
    assert normalized_universe_digest(original) != normalized_universe_digest(swapped)
    assert normalized_universe_digest(original) != normalized_universe_digest({'20261102': {'000001.SZ'}})
    _, info = synthetic_universe(tmp_path / 'other-dates', {'20261029': {'000001.SZ'}, '20261030': {'000001.SZ'}})
    report = audit(qualified[0], universe=qualified[1], universe_info=info)
    assert report['summary']['scoring_allowed'] is False
    assert report['universe']['control_totals_verified'] is False
    assert report['universe']['evidence']['bound'] is False
    assert report['universe']['evidence']['audit_dates'] == sorted(qualified[1])
    assert report['universe']['input_claims']['evidence']['audit_dates'] == ['20261029','20261030']


@pytest.mark.parametrize('bad_date', ['20261101', '20261301'])
def test_global_extra_or_invalid_dates_veto_summary_amount(qualified, bad_date):
    # 11/01 lies outside the requested window; use an in-window non-request day
    # by asking for 10/30 and 11/03 when testing an otherwise valid extra date.
    path, universe, info = qualified
    if bad_date == '20261101':
        with sqlite3.connect(path) as conn:
            conn.execute("UPDATE daily_quote SET trade_date='20261030' WHERE trade_date='20261102'")
        universe, info = synthetic_universe(path.parent / 'wider-window',
            {day: {'000001.SZ'} for day in ['20261030', '20261103']})
    with sqlite3.connect(path) as conn:
        conn.execute('INSERT INTO daily_quote (ts_code,trade_date) VALUES (?,?)', ('000001.SZ',bad_date))
    with readonly_connection('sqlite:///'+str(path),path.parent) as (conn,_):
        report = audit_database(conn, dates=sorted(universe), calendar={'status':'provided_calendar'}, universe=universe, universe_info=info)
    assert all(day['amount_metrics_allowed'] is True for day in report['days'])
    assert report['summary']['scoring_allowed'] is False
    assert report['summary']['amount_metrics_allowed'] is False


def test_non_share_quotes_cannot_dilute_anomaly_ratio(qualified):
    with sqlite3.connect(qualified[0]) as conn:
        conn.execute("UPDATE daily_quote SET turnover_rate=-1 WHERE trade_date='20261102'")
        conn.executemany("INSERT INTO daily_quote VALUES (?,'20261102',10,11,9,10,10,0,100,100,1)",
            [(f'{i:06d}.SH',) for i in range(1000)])
    day = qualified_audit(qualified)['days'][0]
    assert day['raw_rows'] == 1001 and day['scoped_rows'] == 1
    assert day['anomaly_ratio'] == 1
    assert day['scoring_allowed'] is False


def test_one_amount_contradiction_among_thousands_is_absolute_veto(db_file, tmp_path):
    codes = {f'600{i:03d}.SH' for i in range(1000)} | {'000001.SZ'}
    universe, info = synthetic_universe(tmp_path/'large-synthetic', {'20261102': codes})
    with sqlite3.connect(db_file) as conn:
        conn.execute('UPDATE daily_quote SET amount=200,turnover_rate=1')
        conn.executemany("INSERT INTO daily_quote VALUES (?,'20261102',10,11,9,10,10,0,100,100,1)", [(c,) for c in codes-{'000001.SZ'}])
    with readonly_connection('sqlite:///'+str(db_file),db_file.parent) as (conn,_):
        report = audit_database(conn,dates=['20261102'],calendar={'status':'provided_calendar'},universe=universe,universe_info=info)
    day = report['days'][0]
    assert day['anomaly_ratio'] == 0
    assert day['consistency']['amount_inconsistent_rows'] == 1
    assert report['summary']['scoring_allowed'] is True
    assert report['summary']['amount_metrics_allowed'] is False


@pytest.mark.parametrize('sqltype,value,valid', [('TEXT','10',True), ('BOOLEAN',True,False)])
def test_audit_normalizes_text_but_rejects_boolean_prices(tmp_path, sqltype, value, valid):
    path=tmp_path/'typed.db'
    with sqlite3.connect(path) as conn:
        conn.execute('CREATE TABLE stock_basic(ts_code TEXT)')
        conn.execute(f'CREATE TABLE daily_quote(ts_code TEXT,trade_date TEXT,open {sqltype},high REAL,low REAL,close REAL,pre_close REAL,pct_chg REAL,vol REAL,amount REAL,turnover_rate REAL)')
        conn.execute("INSERT INTO daily_quote VALUES ('000001.SZ','20261102',?,11,9,10,10,0,100,100,1)", (value,))
    universe, info = synthetic_universe(tmp_path/'typed-proof', {'20261102': {'000001.SZ'}})
    with readonly_connection('sqlite:///'+str(path),path.parent) as (conn,_):
        report = audit_database(conn,dates=['20261102'],calendar={'status':'provided_calendar'},universe=universe,universe_info=info)
    day = report['days'][0]
    assert day['scoring_allowed'] is valid
    assert day['fields']['open']['valid'] == int(valid)
    assert day['amount_metrics_allowed'] is valid


def test_shared_numeric_helpers_remain_legacy_compatible():
    from app.services.market_data_quality_service import finite, valid_field, _audit_number
    assert finite(True) and valid_field('open', True)
    assert _audit_number(True) is None


@pytest.mark.parametrize('row', [
    '20261101,000001.SZ,a_shrae,1,1', # outside requested grid still validated
    '20261102, 000001.SZ,a_share,1,1',
    '20261102,000001.sz,a_share,1,1',
    '20261102,０００００１.SZ,a_share,1,1',
    '20261102,000002.SZ,a_share,true,1',
])
def test_universe_does_not_normalize_or_hide_bad_rows(tmp_path, row):
    path = tmp_path/'universe.csv'
    path.write_text('trade_date,ts_code,security_type,is_listed,is_trading\n20261102,600001.SH,a_share,1,1\n'+row+'\n')
    with pytest.raises(ValueError):
        load_universe(path,['20261102'])


@pytest.mark.parametrize('subset', [False, True])
def test_markdown_exposes_evidence_scope_and_amount_gate_without_claiming_truth(qualified, tmp_path, subset):
    from app.services.market_data_quality_service import render_markdown
    path, universe, info = qualified
    if subset:
        universe, info = synthetic_universe(tmp_path/'subset-render', universe, scope='security_subset')
    with sqlite3.connect(path) as conn:
        conn.execute('UPDATE daily_quote SET vol=0,amount=100')
    report = audit(path,universe=universe,universe_info=info)
    report.update(database='isolated synthetic test', generated_at='2026-11-11T12:00:00+08:00',configuration_source='test')
    rendered = render_markdown(report)
    assert '真实分母' not in rendered and '真实覆盖率' not in rendered
    assert '清单分母' in rendered and '清单覆盖比例' in rendered
    assert 'counts_match）：`True`' in rendered
    assert '证据绑定：`True`' in rendered
    assert ('security_subset' if subset else 'full_market_point_in_time') in rendered
    assert f'全市场证据资格：`{not subset}`' in rendered
    assert 'amount_metrics_allowed）：`False`' in rendered
    assert '量额可检查率' in rendered and '量额矛盾行' in rendered
    assert report['universe']['evidence']['bound'] is True
    assert report['universe']['control_totals_verified'] is (not subset)


def test_bad_ohlc_does_not_hide_deterministic_zero_pair_contradiction(qualified):
    with sqlite3.connect(qualified[0]) as conn:
        conn.execute('UPDATE daily_quote SET high=8,vol=0,amount=100')
    day = qualified_audit(qualified)['days'][0]
    assert day['consistency']['amount_uncheckable_rows'] == 1
    assert day['consistency']['zero_pair_mismatch_rows'] == 1
    assert 'volume_amount_zero_mismatch' in day['invalid_rows'][0]['issues']
