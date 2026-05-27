from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Iterable

from sqlalchemy import Column, create_engine, func, inspect, select
from sqlalchemy.engine import Engine

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.config import DATABASE_URL  # noqa: E402
from app.database import Base  # noqa: E402
import app.models  # noqa: F401,E402

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


def _count_rows(engine: Engine, table_name: str) -> int:
    if not inspect(engine).has_table(table_name):
        return 0
    table = Base.metadata.tables[table_name]
    with engine.connect() as conn:
        return int(conn.execute(select(func.count()).select_from(table)).scalar_one())


def _copy_table(source: Engine, target: Engine, table_name: str, batch_size: int, dry_run: bool) -> int:
    if not inspect(source).has_table(table_name):
        return 0
    table = Base.metadata.tables[table_name]
    source_columns = {column["name"] for column in inspect(source).get_columns(table_name)}
    selected_columns = [column for column in table.columns if column.name in source_columns]
    if not selected_columns:
        return 0
    copied = 0
    with source.connect() as source_conn:
        result = source_conn.execute(select(*selected_columns))
        rows = (_row_with_defaults(dict(row._mapping), table.columns) for row in result)
        if dry_run:
            copied = sum(1 for _ in rows)
            return copied

        with target.begin() as target_conn:
            for batch in _batched(rows, batch_size):
                target_conn.execute(table.insert(), batch)
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


def _truncate_target(target: Engine) -> None:
    with target.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())


def migrate(
    *,
    sqlite_url: str,
    target_url: str,
    batch_size: int = 1000,
    create_schema: bool = True,
    truncate: bool = False,
    dry_run: bool = False,
) -> list[dict[str, int | str]]:
    if not sqlite_url.startswith("sqlite"):
        raise ValueError("source database must be SQLite")
    if target_url.startswith("sqlite") and target_url == sqlite_url:
        raise ValueError("target database must be different from source database")

    source = create_engine(sqlite_url, connect_args={"check_same_thread": False})
    target = create_engine(target_url)

    if create_schema and not dry_run:
        Base.metadata.create_all(bind=target)
    if truncate and not dry_run:
        _truncate_target(target)

    summaries: list[dict[str, int | str]] = []
    for table in Base.metadata.sorted_tables:
        table_name = table.name
        source_count = _count_rows(source, table_name)
        if source_count == 0:
            target_count = _count_rows(target, table_name) if not dry_run else 0
            summaries.append(
                {
                    "table": table_name,
                    "source_count": source_count,
                    "copied_count": 0,
                    "target_count": target_count,
                    "status": "empty",
                }
            )
            continue

        copied_count = _copy_table(source, target, table_name, batch_size, dry_run)
        target_count = _count_rows(target, table_name) if not dry_run else 0
        status = "dry_run" if dry_run else ("ok" if target_count >= source_count else "mismatch")
        summaries.append(
            {
                "table": table_name,
                "source_count": source_count,
                "copied_count": copied_count,
                "target_count": target_count,
                "status": status,
            }
        )
    return summaries


def _print_summary(summaries: list[dict[str, int | str]]) -> None:
    for row in summaries:
        print(
            "{table}: source={source_count} copied={copied_count} target={target_count} status={status}".format(
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
