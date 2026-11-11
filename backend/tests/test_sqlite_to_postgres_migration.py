from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, select
import pytest

from app.database import Base
import app.models  # noqa: F401
from app.models.stock import DailyQuote, StockBasic
from scripts.migrate_sqlite_to_postgres import migrate


def _sqlite_url(path: Path) -> str:
    return f"sqlite:///{path}"


def test_migrate_sqlite_to_target_database(tmp_path: Path):
    source_url = _sqlite_url(tmp_path / "source.db")
    target_url = _sqlite_url(tmp_path / "target.db")
    source_engine = create_engine(source_url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=source_engine)

    with source_engine.begin() as conn:
        conn.execute(
            StockBasic.__table__.insert(),
            [
                {
                    "ts_code": "000001.SZ",
                    "symbol": "000001",
                    "name": "平安银行",
                    "area": "深圳",
                    "industry": "银行",
                    "market": "主板",
                    "list_date": "19910403",
                    "list_status": "L",
                    "float_share": 100.0,
                }
            ],
        )
        conn.execute(
            DailyQuote.__table__.insert(),
            [
                {
                    "ts_code": "000001.SZ",
                    "trade_date": "20260528",
                    "open": 10.0,
                    "high": 10.5,
                    "low": 9.9,
                    "close": 10.2,
                    "pre_close": 10.0,
                    "change": 0.2,
                    "pct_chg": 2.0,
                    "vol": 1000.0,
                    "amount": 10000.0,
                    "turnover_rate": 1.2,
                    "float_share": 100.0,
                }
            ],
        )

    summaries = migrate(sqlite_url=source_url, target_url=target_url, batch_size=2)
    summary_by_table = {row["table"]: row for row in summaries}

    assert summary_by_table["stock_basic"]["status"] == "ok"
    assert summary_by_table["daily_quote"]["status"] == "ok"

    target_engine = create_engine(target_url)
    with target_engine.connect() as conn:
        stock_count = conn.execute(select(StockBasic)).all()
        quote_count = conn.execute(select(DailyQuote)).all()

    assert len(stock_count) == 1
    assert len(quote_count) == 1


def test_failed_copy_restores_truncated_target_and_earlier_tables(tmp_path):
    source_url = _sqlite_url(tmp_path / "source.db")
    target_url = _sqlite_url(tmp_path / "target.db")
    source, target = create_engine(source_url), create_engine(target_url)
    for engine, code in ((source, "000001.SZ"), (target, "600000.SH")):
        Base.metadata.create_all(engine)
        with engine.begin() as conn:
            conn.execute(StockBasic.__table__.insert(), {"ts_code": code, "name": "preserved"})
            conn.execute(DailyQuote.__table__.insert(), {"ts_code": code, "trade_date": "20261110", "close": 10})
    with target.begin() as conn:
        conn.exec_driver_sql("CREATE TRIGGER reject_stock BEFORE INSERT ON stock_basic BEGIN SELECT RAISE(ABORT, 'fixture failure'); END")
    with pytest.raises(Exception):
        migrate(sqlite_url=source_url, target_url=target_url, truncate=True, batch_size=1)
    with target.connect() as conn:
        assert conn.execute(select(StockBasic.__table__.c.ts_code)).scalars().all() == ["600000.SH"]
        assert conn.execute(select(DailyQuote.__table__.c.ts_code)).scalars().all() == ["600000.SH"]
    source.dispose()
    target.dispose()


def test_same_file_alias_and_missing_source_cannot_be_truncated(tmp_path):
    path = tmp_path / "same.db"
    source = create_engine(_sqlite_url(path))
    Base.metadata.create_all(source)
    with pytest.raises(ValueError, match="different"):
        migrate(sqlite_url=_sqlite_url(path), target_url=_sqlite_url(tmp_path / "." / "same.db"), truncate=True)
    missing = tmp_path / "missing.db"
    with pytest.raises(ValueError):
        migrate(sqlite_url=_sqlite_url(missing), target_url=_sqlite_url(tmp_path / "target.db"))
    assert not missing.exists()
    source.dispose()
