"""为 daily_quote 表新增 turnover_rate 列（SQLite 专用迁移）"""

from __future__ import annotations
import sqlite3
from app.config import DATABASE_URL


def migrate():
    if "sqlite" not in DATABASE_URL:
        return
    db_path = DATABASE_URL.replace("sqlite:///", "")
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='daily_quote'")
    if not cur.fetchone():
        conn.close()
        return
    cur.execute("PRAGMA table_info(daily_quote)")
    cols = [row[1] for row in cur.fetchall()]
    if not cols:
        conn.close()
        return
    if "turnover_rate" not in cols:
        cur.execute("ALTER TABLE daily_quote ADD COLUMN turnover_rate REAL")
        conn.commit()
    conn.close()
