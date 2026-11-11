"""Read-only schema readiness; no provider calls, seeding or startup mutations."""
from sqlalchemy import select


def check_database_ready(connection):
    from app.database import Base
    import app.models  # noqa: F401
    # Select every mapped column without loading business rows. A simple SELECT 1
    # cannot detect a missing migration; checking only table names misses columns.
    for table in Base.metadata.sorted_tables:
        connection.execute(select(table).limit(0))
    return {"status": "ready", "database": "ok", "schema": "ok"}
