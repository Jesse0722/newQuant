"""
迁移脚本：为 watch_pool 添加 sort_order 列。
运行：cd backend && python -m scripts.migrate_pool_sort_order
"""

from __future__ import annotations
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from app.database import engine
from app.config import DATABASE_URL


def _pool_has_sort_order(conn) -> bool:
    r = conn.execute(text("PRAGMA table_info(watch_pool)"))
    cols = [row[1] for row in r.fetchall()]
    return "sort_order" in cols


def migrate():
    with engine.connect() as conn:
        if "sqlite" not in DATABASE_URL:
            print("仅支持 SQLite 迁移，跳过")
            return
        try:
            r = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='watch_pool'"))
            if not r.fetchone():
                print("watch_pool 表不存在，无需迁移")
                return
        except Exception as e:
            print(f"检查表失败: {e}")
            return

        if _pool_has_sort_order(conn):
            print("sort_order 已存在，跳过")
            return

        print("添加 watch_pool.sort_order...")
        conn.execute(text("ALTER TABLE watch_pool ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0"))
        # 按 created_at 回填顺序
        rows = conn.execute(text("SELECT id FROM watch_pool ORDER BY created_at DESC")).fetchall()
        for i, (pid,) in enumerate(rows):
            conn.execute(text("UPDATE watch_pool SET sort_order = :ord WHERE id = :id"), {"ord": i, "id": pid})

        conn.commit()
        print("迁移完成")


if __name__ == "__main__":
    migrate()
