"""Create repair-audit tables in an existing SQLite database.

This compatibility migration is deliberately opt-in and is not registered in the
application startup migration list.  PostgreSQL environments should use Alembic.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import inspect
from sqlalchemy.engine import make_url

from app.config import DATABASE_URL
from app.database import Base
from app.models.daily_quote_repair import DailyQuoteRepairAudit, DailyQuoteRepairBatch
from app.services.quote_repair_io import writer_connection


TABLES = (DailyQuoteRepairBatch.__table__, DailyQuoteRepairAudit.__table__)


def migrate(database_url: str | None = None) -> dict[str, list[str]]:
    """Idempotently create only the two repair tables in a SQLite database."""

    url = database_url or DATABASE_URL
    if make_url(url).get_backend_name() != "sqlite":
        raise ValueError("兼容迁移脚本仅支持 SQLite；PostgreSQL 请使用 Alembic")

    with writer_connection(url, str(Path.cwd())) as conn:
        before = set(inspect(conn).get_table_names())
        if "daily_quote" not in before:
            raise ValueError("目标不是已有行情库；请先确认主库")
        Base.metadata.create_all(bind=conn, tables=list(TABLES), checkfirst=True)
        after = set(inspect(conn).get_table_names())
        names = {table.name for table in TABLES}
        return {
            "created": sorted((after - before) & names),
            "existing": sorted(before & names),
        }


if __name__ == "__main__":
    migrate()
