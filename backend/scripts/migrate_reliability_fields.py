"""Idempotent SQLite MVP compatibility; PostgreSQL uses Alembic only."""
from sqlalchemy import inspect, text


def migrate():
    from app.database import engine
    if engine.dialect.name != "sqlite":
        return
    with engine.begin() as conn:
        if not inspect(conn).has_table("industry_daily_report"):
            return
        existing = {c["name"] for c in inspect(conn).get_columns("industry_daily_report")}
        for name, kind in (("input_snapshot", "JSON"), ("raw_response", "TEXT")):
            if name not in existing:
                conn.execute(text(f"ALTER TABLE industry_daily_report ADD COLUMN {name} {kind}"))


if __name__ == "__main__":
    migrate()
