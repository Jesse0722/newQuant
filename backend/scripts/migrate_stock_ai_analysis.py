"""
迁移脚本：新增 stock_ai_analysis 表。
运行：cd backend && python -m scripts.migrate_stock_ai_analysis
"""

from __future__ import annotations
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from app.database import engine
from app.config import DATABASE_URL


def migrate():
    with engine.connect() as conn:
        if "sqlite" not in DATABASE_URL:
            print("仅支持 SQLite 迁移，跳过")
            return

        exists = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='stock_ai_analysis'")
        ).fetchone()
        if exists:
            print("stock_ai_analysis 表已存在，跳过")
            return

        conn.execute(text("""
            CREATE TABLE stock_ai_analysis (
                id VARCHAR(36) NOT NULL PRIMARY KEY,
                ts_code VARCHAR(16) NOT NULL,
                scope VARCHAR(32) NOT NULL DEFAULT 'stock_detail',
                pool_id VARCHAR(36),
                watch_stock_id VARCHAR(36),
                mode VARCHAR(16) NOT NULL DEFAULT 'deep',
                model_provider VARCHAR(32) NOT NULL,
                model_name VARCHAR(80) NOT NULL,
                prompt_version VARCHAR(16) NOT NULL DEFAULT '1.0',
                snapshot_json JSON,
                analysis_json JSON,
                raw_response TEXT,
                data_trade_date VARCHAR(8),
                status VARCHAR(16) NOT NULL DEFAULT 'success',
                error_message TEXT,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL
            )
        """))
        conn.execute(text("CREATE INDEX ix_stock_ai_analysis_ts_code ON stock_ai_analysis (ts_code)"))
        conn.execute(text("CREATE INDEX ix_stock_ai_analysis_pool_id ON stock_ai_analysis (pool_id)"))
        conn.execute(text("CREATE INDEX ix_stock_ai_analysis_watch_stock_id ON stock_ai_analysis (watch_stock_id)"))
        conn.execute(text("CREATE INDEX ix_stock_ai_analysis_data_trade_date ON stock_ai_analysis (data_trade_date)"))
        conn.execute(text("CREATE INDEX ix_stock_ai_analysis_code_created ON stock_ai_analysis (ts_code, created_at)"))
        conn.commit()
        print("stock_ai_analysis 迁移完成")


if __name__ == "__main__":
    migrate()
