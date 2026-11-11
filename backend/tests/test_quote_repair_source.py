from __future__ import annotations

from dataclasses import replace
from datetime import datetime
import json

import pandas as pd
import pytest
from sqlalchemy import create_engine

from app.models.stock import DailyQuote, StockBasic
from app.services.daily_quote_repair_service import normalized_source_row
from app.services.market_data_capabilities import ProviderCapabilities
from app.services.quote_repair_source_service import fetch_repair_snapshot, repair_dates, select_repair_source
from app.services.source_identity import attach_identity
from scripts import repair_daily_quotes as cli

CAPS = ProviderCapabilities("baostock", False, True, False, ("SH", "SZ"), "share", "cny", False, True, True)
DATES = ["20261008", "20261009"]


def raw(day="20261008", **overrides):
    return {**dict(ts_code="000001.SZ", trade_date=day, open=10, close=10, high=11, low=9,
                   pre_close=10, change=0, pct_chg=0, vol=1000, amount=20000, turnover_rate=2), **overrides}


class Provider:
    capabilities = CAPS
    def __init__(self, rows=(), error=False):
        self.rows, self.error, self.calls = rows, error, []
    def get_daily(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise ConnectionError("https://secret-token@example.invalid")
        frame = pd.DataFrame(self.rows)
        if frame.empty:
            return frame
        identities = [{"provider": "baostock", "raw_code": row["ts_code"].split(".")[1].lower() + "." + row["ts_code"].split(".")[0],
                       "trade_date": row["trade_date"]} for row in self.rows]
        return attach_identity(frame, "baostock", identities, self.rows)


@pytest.mark.parametrize("kind,outcome", [("empty", "no_data"), ("error", "failed"), ("wrong_code", "failed"),
                                         ("bad_amount", "failed"), ("duplicate", "failed")])
def test_zero_valid_source_rows_cannot_report_success(kind, outcome):
    rows = [] if kind in ("empty", "error") else [raw(ts_code="000002.SZ")] if kind == "wrong_code" else [raw(amount=-1)] if kind == "bad_amount" else [raw(), raw()]
    source = Provider(rows, error=kind == "error")
    result = fetch_repair_snapshot(source, CAPS, [DATES[0]], ["000001.SZ"], {}, request_interval=0)
    assert result["outcome"] == outcome and result["valid_row_count"] == 0
    assert "secret-token" not in json.dumps(result)


def test_source_snapshot_keeps_raw_units_and_same_row_metadata():
    source = Provider([raw(), raw(day=DATES[1])])
    result = fetch_repair_snapshot(source, CAPS, DATES, ["000001.SZ"], {}, request_interval=0)
    assert result["outcome"] == "success" and result["valid_row_count"] == 2
    assert result["rows"][0]["vol"] == 1000 and result["rows"][0]["amount"] == 20000
    normalized = normalized_source_row(result["rows"][0], result["source"])
    assert normalized["vol"] == 10 and normalized["amount"] == 20 and normalized["turnover_rate"] == 2
    assert source.calls == [{"ts_code": "000001.SZ", "start_date": DATES[0], "end_date": DATES[1]}]


def test_partial_and_market_unsupported_are_explicit():
    result = fetch_repair_snapshot(Provider([raw()]), CAPS, DATES, ["000001.SZ"], {}, request_interval=0)
    assert result["outcome"] == "partial"
    source = Provider()
    result = fetch_repair_snapshot(source, CAPS, DATES, ["920001.BJ"], {}, request_interval=0)
    assert result["outcome"] == "unsupported" and source.calls == []


def test_unconfigured_or_disabled_sources_never_auto_activate():
    source = Provider()
    assert select_repair_source(source, "baostock")[0] is source
    with pytest.raises(ValueError):
        select_repair_source(source, "tushare")
    source.capabilities = replace(CAPS, enabled=False)
    with pytest.raises(ValueError):
        select_repair_source(source, "baostock")


def test_calendar_selects_empty_db_dates_and_rejects_incomplete_or_future(tmp_path):
    calendar = tmp_path / "calendar.csv"
    calendar.write_text("trade_date,is_open\n20261007,0\n20261008,1\n20261009,1\n")
    dates, _ = repair_dates("20261007", "20261009", calendar, now=datetime(2026, 10, 9, 17))
    assert dates == DATES
    with pytest.raises(ValueError):
        repair_dates("20261007", "20261009", calendar, now=datetime(2026, 10, 9, 15))
    with pytest.raises(ValueError):
        repair_dates("20261006", "20261009", calendar, now=datetime(2026, 10, 9, 17))


def test_cli_outage_writes_evidence_but_returns_nonzero_and_plan_refuses(tmp_path, monkeypatch, capsys):
    from app.services import tushare_adapter as adapters
    dbpath = tmp_path / "quotes.db"
    engine = create_engine("sqlite:///" + str(dbpath))
    DailyQuote.__table__.create(engine)
    StockBasic.__table__.create(engine)
    engine.dispose()
    monkeypatch.setenv("DATABASE_URL", "sqlite:///" + str(dbpath))
    monkeypatch.setattr(adapters, "tushare_adapter", Provider(error=True))
    calendar = tmp_path / "calendar.csv"
    calendar.write_text("trade_date,is_open\n20261008,1\n20261009,1\n")
    snapshot = tmp_path / "snapshot.json"
    assert cli.main(["fetch", "--source", "baostock", "--from-date", DATES[0], "--to-date", DATES[1],
                     "--codes", "000001.SZ", "--calendar-csv", str(calendar), "--output", str(snapshot)]) == 2
    output = capsys.readouterr()
    assert json.loads(output.out)["status"] == "failed"
    assert "secret-token" not in output.out + output.err
    assert cli.main(["plan", "--snapshot", str(snapshot), "--output", str(tmp_path / "plan.json")]) == 1
    assert not (tmp_path / "plan.json").exists()
