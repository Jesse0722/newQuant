"""
迁移脚本：为 message_opportunity 添加 agent 证据与复核状态字段。
运行：cd backend && python -m scripts.migrate_message_opportunity_review_fields
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text

from app.database import engine


def _table_has_column(conn, table: str, column: str) -> bool:
    result = conn.execute(text(f"PRAGMA table_info({table})"))
    cols = [row[1] for row in result.fetchall()]
    return column in cols


def _add_column(conn, table: str, column: str, ddl: str) -> None:
    if not _table_has_column(conn, table, column):
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {ddl}"))


def migrate():
    if engine.url.get_backend_name() != "sqlite":
        return
    with engine.connect() as conn:
        result = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='message_opportunity'")
        )
        if not result.fetchone():
            return
        _add_column(conn, "message_opportunity", "evidence_score", "evidence_score INTEGER NOT NULL DEFAULT 0")
        _add_column(conn, "message_opportunity", "mapping_confidence", "mapping_confidence INTEGER NOT NULL DEFAULT 0")
        _add_column(conn, "message_opportunity", "review_status", "review_status VARCHAR(16) NOT NULL DEFAULT 'reviewed'")
        _add_column(conn, "message_opportunity", "review_reason", "review_reason TEXT")
        _add_column(conn, "message_opportunity", "generated_by", "generated_by VARCHAR(16) NOT NULL DEFAULT 'manual'")
        _add_column(conn, "message_opportunity", "accepted_at", "accepted_at DATETIME")
        _add_column(conn, "message_opportunity", "dismissed_at", "dismissed_at DATETIME")
        conn.commit()


if __name__ == "__main__":
    migrate()

