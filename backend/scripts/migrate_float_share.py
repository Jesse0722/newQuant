"""为 stock_basic、daily_quote 增加 float_share（万股，SQLite）"""

from __future__ import annotations
import sqlite3
from app.config import DATABASE_URL


def migrate():
    if "sqlite" not in DATABASE_URL:
        return
    db_path = DATABASE_URL.replace("sqlite:///", "")
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    for table in ("stock_basic", "daily_quote"):
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
        if not cur.fetchone():
            continue
        cur.execute(f"PRAGMA table_info({table})")
        cols = [row[1] for row in cur.fetchall()]
        if not cols:
            continue
        if "float_share" not in cols:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN float_share REAL")
    conn.commit()
    conn.close()
