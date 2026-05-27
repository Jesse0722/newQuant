from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, select

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
