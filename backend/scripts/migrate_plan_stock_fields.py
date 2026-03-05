"""
迁移脚本：将 risk_level、trigger_strategy、event_note、action_suggestion 从计划级下放到股票级。
运行：cd backend && python -m scripts.migrate_plan_stock_fields
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from app.database import engine
from app.config import DATABASE_URL


def _stock_has_new_fields(conn) -> bool:
    """检测 trade_plan_stock 是否已有 risk_level 列"""
    r = conn.execute(text("PRAGMA table_info(trade_plan_stock)"))
    cols = [row[1] for row in r.fetchall()]
    return "risk_level" in cols


def _plan_has_old_fields(conn) -> bool:
    """检测 trade_plan 是否仍有 risk_level 列"""
    r = conn.execute(text("PRAGMA table_info(trade_plan)"))
    cols = [row[1] for row in r.fetchall()]
    return "risk_level" in cols


def migrate():
    with engine.connect() as conn:
        if "sqlite" not in DATABASE_URL:
            print("仅支持 SQLite 迁移，跳过")
            return
        try:
            r = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='trade_plan_stock'"))
            if not r.fetchone():
                print("trade_plan_stock 表不存在，无需迁移")
                return
        except Exception as e:
            print(f"检查表失败: {e}")
            return

        if _stock_has_new_fields(conn):
            print("trade_plan_stock 已是新 schema，无需迁移")
            return

        print("开始迁移 plan_stock 字段...")
        conn.execute(text("PRAGMA foreign_keys=OFF"))

        # 1. 给 trade_plan_stock 添加 4 列
        conn.execute(text("ALTER TABLE trade_plan_stock ADD COLUMN risk_level INTEGER DEFAULT 3"))
        conn.execute(text("ALTER TABLE trade_plan_stock ADD COLUMN trigger_strategy TEXT"))
        conn.execute(text("ALTER TABLE trade_plan_stock ADD COLUMN event_note TEXT"))
        conn.execute(text("ALTER TABLE trade_plan_stock ADD COLUMN action_suggestion VARCHAR(16)"))

        # 2. 从 trade_plan 回填到 trade_plan_stock（若 plan 仍有这些列）
        if _plan_has_old_fields(conn):
            conn.execute(text("""
                UPDATE trade_plan_stock
                SET risk_level = COALESCE(
                    (SELECT risk_level FROM trade_plan WHERE trade_plan.id = trade_plan_stock.plan_id),
                    3
                ),
                trigger_strategy = (SELECT trigger_strategy FROM trade_plan WHERE trade_plan.id = trade_plan_stock.plan_id),
                event_note = (SELECT event_note FROM trade_plan WHERE trade_plan.id = trade_plan_stock.plan_id),
                action_suggestion = (SELECT action_suggestion FROM trade_plan WHERE trade_plan.id = trade_plan_stock.plan_id)
            """))

        # 3. 从 trade_plan 删除 4 列（SQLite 需重建表）
        if _plan_has_old_fields(conn):
            conn.execute(text("""
                CREATE TABLE trade_plan_new (
                    id VARCHAR(36) PRIMARY KEY,
                    plan_type VARCHAR(16) NOT NULL,
                    status VARCHAR(16) NOT NULL DEFAULT 'pending',
                    alert_id VARCHAR(36),
                    actual_pnl FLOAT,
                    review_summary TEXT,
                    lessons_learned TEXT,
                    note TEXT,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL
                )
            """))
            conn.execute(text("""
                INSERT INTO trade_plan_new (id, plan_type, status, alert_id, actual_pnl, review_summary, lessons_learned, note, created_at, updated_at)
                SELECT id, plan_type, status, alert_id, actual_pnl, review_summary, lessons_learned, note, created_at, updated_at
                FROM trade_plan
            """))
            conn.execute(text("DROP TABLE trade_plan"))
            conn.execute(text("ALTER TABLE trade_plan_new RENAME TO trade_plan"))

        conn.execute(text("PRAGMA foreign_keys=ON"))
        conn.commit()
        print("迁移完成")


if __name__ == "__main__":
    migrate()
