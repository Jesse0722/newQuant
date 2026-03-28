"""
迁移脚本：为 watch_stock 添加 AI 分析相关字段。
运行：cd backend && python -m scripts.migrate_watch_stock_ai_fields
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from app.database import engine
from app.config import DATABASE_URL


def _table_has_column(conn, table: str, column: str) -> bool:
    result = conn.execute(text(f"PRAGMA table_info({table})"))
    cols = [row[1] for row in result.fetchall()]
    return column in cols


def migrate():
    with engine.connect() as conn:
        if "sqlite" not in DATABASE_URL:
            print("仅支持 SQLite 迁移，跳过")
            return

        result = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='watch_stock'")
        )
        if not result.fetchone():
            print("watch_stock 表不存在，无需迁移")
            return

        if not _table_has_column(conn, "watch_stock", "ai_analysis"):
            print("添加 watch_stock.ai_analysis...")
            conn.execute(text("ALTER TABLE watch_stock ADD COLUMN ai_analysis TEXT"))
        else:
            print("ai_analysis 已存在，跳过")

        if not _table_has_column(conn, "watch_stock", "ai_analyzed_at"):
            print("添加 watch_stock.ai_analyzed_at...")
            conn.execute(text("ALTER TABLE watch_stock ADD COLUMN ai_analyzed_at DATETIME"))
        else:
            print("ai_analyzed_at 已存在，跳过")

        conn.commit()
        print("迁移完成")


if __name__ == "__main__":
    migrate()
