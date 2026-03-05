"""
迁移脚本：添加 title、移除 plan_type；移除 trade_plan_stock 的 event_note、action_suggestion。
运行：cd backend && python -m scripts.migrate_plan_title_remove_type
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from app.database import engine
from app.config import DATABASE_URL


def _plan_has_title(conn) -> bool:
    r = conn.execute(text("PRAGMA table_info(trade_plan)"))
    cols = [row[1] for row in r.fetchall()]
    return "title" in cols


def _plan_has_plan_type(conn) -> bool:
    r = conn.execute(text("PRAGMA table_info(trade_plan)"))
    cols = [row[1] for row in r.fetchall()]
    return "plan_type" in cols


def _stock_has_event_note(conn) -> bool:
    r = conn.execute(text("PRAGMA table_info(trade_plan_stock)"))
    cols = [row[1] for row in r.fetchall()]
    return "event_note" in cols


def migrate():
    with engine.connect() as conn:
        if "sqlite" not in DATABASE_URL:
            print("仅支持 SQLite 迁移，跳过")
            return
        try:
            r = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='trade_plan'"))
            if not r.fetchone():
                print("trade_plan 表不存在，无需迁移")
                return
        except Exception as e:
            print(f"检查表失败: {e}")
            return

        conn.execute(text("PRAGMA foreign_keys=OFF"))

        # 1. trade_plan: 添加 title，移除 plan_type
        if not _plan_has_title(conn):
            print("添加 trade_plan.title...")
            conn.execute(text("ALTER TABLE trade_plan ADD COLUMN title VARCHAR(64)"))
            # 回填：用首股名称或代码
            conn.execute(text("""
                UPDATE trade_plan SET title = COALESCE(
                    (SELECT stock_name FROM trade_plan_stock WHERE trade_plan_stock.plan_id = trade_plan.id LIMIT 1),
                    (SELECT ts_code FROM trade_plan_stock WHERE trade_plan_stock.plan_id = trade_plan.id LIMIT 1),
                    '未命名计划'
                )
            """))
            conn.execute(text("UPDATE trade_plan SET title = '未命名计划' WHERE title IS NULL"))

        if _plan_has_plan_type(conn):
            print("移除 trade_plan.plan_type...")
            conn.execute(text("""
                CREATE TABLE trade_plan_new (
                    id VARCHAR(36) PRIMARY KEY,
                    title VARCHAR(64) NOT NULL,
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
                INSERT INTO trade_plan_new (id, title, status, alert_id, actual_pnl, review_summary, lessons_learned, note, created_at, updated_at)
                SELECT id, COALESCE(title, '未命名计划'), status, alert_id, actual_pnl, review_summary, lessons_learned, note, created_at, updated_at
                FROM trade_plan
            """))
            conn.execute(text("DROP TABLE trade_plan"))
            conn.execute(text("ALTER TABLE trade_plan_new RENAME TO trade_plan"))

        # 2. trade_plan_stock: 移除 event_note, action_suggestion
        if _stock_has_event_note(conn):
            print("移除 trade_plan_stock.event_note, action_suggestion...")
            conn.execute(text("""
                CREATE TABLE trade_plan_stock_new (
                    id VARCHAR(36) PRIMARY KEY,
                    plan_id VARCHAR(36) NOT NULL,
                    ts_code VARCHAR(16) NOT NULL,
                    stock_name VARCHAR(32),
                    risk_level INTEGER NOT NULL DEFAULT 2,
                    trigger_strategy TEXT,
                    planned_buy_price FLOAT,
                    target_price FLOAT,
                    stop_loss_price FLOAT,
                    risk_reward_ratio FLOAT,
                    position_plan VARCHAR(32),
                    note TEXT,
                    FOREIGN KEY (plan_id) REFERENCES trade_plan(id)
                )
            """))
            conn.execute(text("""
                INSERT INTO trade_plan_stock_new (id, plan_id, ts_code, stock_name, risk_level, trigger_strategy,
                    planned_buy_price, target_price, stop_loss_price, risk_reward_ratio, position_plan, note)
                SELECT id, plan_id, ts_code, stock_name, risk_level, trigger_strategy,
                    planned_buy_price, target_price, stop_loss_price, risk_reward_ratio, position_plan, note
                FROM trade_plan_stock
            """))
            conn.execute(text("DROP TABLE trade_plan_stock"))
            conn.execute(text("ALTER TABLE trade_plan_stock_new RENAME TO trade_plan_stock"))

        conn.execute(text("PRAGMA foreign_keys=ON"))
        conn.commit()
        print("迁移完成")


if __name__ == "__main__":
    migrate()
