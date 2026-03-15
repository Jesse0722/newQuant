"""
迁移脚本：为 watch_stock 添加 limit_up_date，为 watch_pool 添加 trigger_target_pool_id。
运行：cd backend && python -m scripts.migrate_limit_up_fields
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from app.database import engine
from app.config import DATABASE_URL


def _table_has_column(conn, table: str, column: str) -> bool:
    r = conn.execute(text(f"PRAGMA table_info({table})"))
    cols = [row[1] for row in r.fetchall()]
    return column in cols


def migrate():
    with engine.connect() as conn:
        if "sqlite" not in DATABASE_URL:
            print("仅支持 SQLite 迁移，跳过")
            return
        try:
            r = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='watch_stock'"))
            if not r.fetchone():
                print("watch_stock 表不存在，无需迁移")
                return
        except Exception as e:
            print(f"检查表失败: {e}")
            return

        if not _table_has_column(conn, "watch_stock", "limit_up_date"):
            print("添加 watch_stock.limit_up_date...")
            conn.execute(text("ALTER TABLE watch_stock ADD COLUMN limit_up_date VARCHAR(8)"))
        else:
            print("limit_up_date 已存在，跳过")

        if not _table_has_column(conn, "watch_pool", "trigger_target_pool_id"):
            print("添加 watch_pool.trigger_target_pool_id...")
            conn.execute(text("ALTER TABLE watch_pool ADD COLUMN trigger_target_pool_id VARCHAR(36)"))
        else:
            print("trigger_target_pool_id 已存在，跳过")

        conn.commit()
        print("迁移完成")


if __name__ == "__main__":
    migrate()
