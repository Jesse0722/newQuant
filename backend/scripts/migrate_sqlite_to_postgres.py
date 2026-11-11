from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Iterable

from sqlalchemy import Column, create_engine, func, inspect, select
from sqlalchemy.engine import Connection, make_url
from contextlib import nullcontext

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.config import DATABASE_URL  # noqa: E402
from app.database import Base  # noqa: E402
import app.models  # noqa: F401,E402
from app.services.market_data_quality_service import readonly_connection  # noqa: E402

logger = logging.getLogger(__name__)


def _default_sqlite_url() -> str:
    return f"sqlite:///{ROOT_DIR / 'data' / 'quant.db'}"


def _batched(rows: Iterable[dict], size: int) -> Iterable[list[dict]]:
    batch: list[dict] = []
    for row in rows:
        batch.append(row)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def _count_rows(conn: Connection, table_name: str) -> int:
    if not inspect(conn).has_table(table_name):
        return 0
    return int(conn.execute(select(func.count()).select_from(Base.metadata.tables[table_name])).scalar_one())


def _source_id_set(conn: Connection, table_name: str) -> set[str]:
    if not inspect(conn).has_table(table_name):
        return set()
    table = Base.metadata.tables[table_name]
    return {str(row[0]) for row in conn.execute(select(table.c.id)) if row[0]}


def _copy_table(source: Connection, target: Connection | None, table_name: str, batch_size: int, dry_run: bool) -> int:
    if not inspect(source).has_table(table_name):
        return 0
    table = Base.metadata.tables[table_name]
    source_columns = {column["name"] for column in inspect(source).get_columns(table_name)}
    selected_columns = [column for column in table.columns if column.name in source_columns]
    if not selected_columns:
        return 0
    fk_context = {
        "trade_plan_ids": _source_id_set(source, "trade_plan") if table_name == "alert" else set(),
        "monitor_rule_ids": _source_id_set(source, "monitor_rule") if table_name == "alert" else set(),
        "watch_stock_ids": _source_id_set(source, "watch_stock") if table_name == "alert" else set(),
    }
    result = source.execute(select(*selected_columns))
    rows = (
        normalized for row in result
        for normalized in [_normalize_legacy_row(table_name, _row_with_defaults(dict(row._mapping), table.columns), fk_context)]
        if normalized is not None
    )
    if dry_run:
        return sum(1 for _ in rows)
    copied = 0
    for batch in _batched(rows, batch_size):
        target.execute(table.insert(), batch)
        copied += len(batch)
    return copied


def _default_value(column: Column):
    if column.default is None:
        return None
    arg = column.default.arg
    if callable(arg):
        try:
            return arg()
        except TypeError:
            return arg(None)
    return arg


def _row_with_defaults(row: dict, columns) -> dict:
    for column in columns:
        if column.name in row:
            continue
        value = _default_value(column)
        if value is not None or column.nullable:
            row[column.name] = value
    return row


def _normalize_legacy_row(table_name: str, row: dict, context: dict) -> dict | None:
    if table_name != "alert":
        return row
    plan_id = row.get("plan_id")
    if plan_id and str(plan_id) not in context["trade_plan_ids"]:
        row["plan_id"] = None
    rule_id = row.get("rule_id")
    if rule_id and str(rule_id) not in context["monitor_rule_ids"]:
        row["rule_id"] = None
    stock_id = row.get("stock_id")
    if stock_id and str(stock_id) not in context["watch_stock_ids"]:
        return None
    return row


def migrate(
    *, sqlite_url: str, target_url: str, batch_size: int = 1000,
    create_schema: bool = True, truncate: bool = False, dry_run: bool = False,
) -> list[dict[str, int | str]]:
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    source_url, destination = make_url(sqlite_url), make_url(target_url)
    if source_url.get_backend_name() != "sqlite":
        raise ValueError("source database must be SQLite")
    if destination.get_backend_name() == "sqlite" and destination.database:
        if Path(source_url.database or "").resolve() == Path(destination.database).resolve():
            raise ValueError("target database must be different from source database")
    # A single read-only snapshot and a single target transaction. A failure in a
    # later table must also undo earlier copies and an explicitly requested clear.
    target = None if dry_run else create_engine(target_url)
    try:
        if target is not None and create_schema:
            Base.metadata.create_all(bind=target)
        with readonly_connection(sqlite_url, ROOT_DIR) as (source, _):
            with target.begin() if target is not None else nullcontext(None) as target_conn:
                if target_conn is not None:
                    if truncate:
                        for table in reversed(Base.metadata.sorted_tables):
                            target_conn.execute(table.delete())
                    elif any(_count_rows(target_conn, table.name) for table in Base.metadata.sorted_tables):
                        raise ValueError("target must be empty; back up first and explicitly use --truncate to replace")
                summaries = []
                for table in Base.metadata.sorted_tables:
                    name = table.name
                    source_count = _count_rows(source, name)
                    copied = _copy_table(source, target_conn, name, batch_size, dry_run) if source_count else 0
                    target_count = _count_rows(target_conn, name) if target_conn is not None else 0
                    if target_conn is not None and target_count != copied:
                        raise ValueError("row-count validation failed for " + name)
                    skipped = source_count - copied
                    status = "dry_run" if dry_run else "empty" if not source_count else "ok_with_legacy_cleanup" if skipped else "ok"
                    summaries.append({"table": name, "source_count": source_count,
                                      "copied_count": copied, "skipped_count": skipped,
                                      "target_count": target_count, "status": status})
                return summaries
    finally:
        if target is not None:
            target.dispose()


def _print_summary(summaries: list[dict[str, int | str]]) -> None:
    for row in summaries:
        print(
            "{table}: source={source_count} copied={copied_count} skipped={skipped_count} target={target_count} status={status}".format(
                **row
            )
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Migrate the legacy SQLite database into PostgreSQL.")
    parser.add_argument("--sqlite-url", default=_default_sqlite_url(), help="Source SQLite SQLAlchemy URL.")
    parser.add_argument(
        "--target-url",
        default=DATABASE_URL,
        help="Target SQLAlchemy URL. Defaults to DATABASE_URL from backend/.env.",
    )
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument("--no-create-schema", action="store_true", help="Do not create target tables first.")
    parser.add_argument("--truncate", action="store_true", help="Delete target rows before copying.")
    parser.add_argument("--dry-run", action="store_true", help="Count source rows without writing target rows.")
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = parse_args()
    summaries = migrate(
        sqlite_url=args.sqlite_url,
        target_url=args.target_url,
        batch_size=args.batch_size,
        create_schema=not args.no_create_schema,
        truncate=args.truncate,
        dry_run=args.dry_run,
    )
    _print_summary(summaries)


if __name__ == "__main__":
    main()
