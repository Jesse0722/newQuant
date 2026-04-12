"""
迁移脚本：交易计划从单股改为多股，交易明细从关联计划改为关联股票。
运行：cd backend && python -m scripts.migrate_trade_plan
"""

from __future__ import annotations
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from app.database import engine
from app.config import DATABASE_URL


def _has_old_schema(conn) -> bool:
    """检测是否为旧 schema（trade_plan 有 ts_code 列）"""
    r = conn.execute(text("PRAGMA table_info(trade_plan)"))
    cols = [row[1] for row in r.fetchall()]
    return "ts_code" in cols


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

        if not _has_old_schema(conn):
            print("已是新 schema，无需迁移")
            return

        print("开始迁移...")
        conn.execute(text("PRAGMA foreign_keys=OFF"))

        # 1. 创建 trade_plan_stock 并迁移数据
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS trade_plan_stock (
                id VARCHAR(36) PRIMARY KEY,
                plan_id VARCHAR(36) NOT NULL,
                ts_code VARCHAR(16) NOT NULL,
                stock_name VARCHAR(32),
                planned_buy_price FLOAT,
                target_price FLOAT,
                stop_loss_price FLOAT,
                risk_reward_ratio FLOAT,
                position_plan VARCHAR(32),
                note TEXT
            )
        """))
        conn.execute(text("""
            INSERT INTO trade_plan_stock (id, plan_id, ts_code, stock_name, planned_buy_price, target_price, stop_loss_price, risk_reward_ratio, position_plan, note)
            SELECT id || '_' || ts_code, id, ts_code, stock_name, planned_buy_price, target_price, stop_loss_price, risk_reward_ratio, position_plan, note
            FROM trade_plan
        """))

        # 2. 重建 trade_plan（去掉股票相关列）
        conn.execute(text("""
            CREATE TABLE trade_plan_new (
                id VARCHAR(36) PRIMARY KEY,
                plan_type VARCHAR(16) NOT NULL,
                risk_level INTEGER NOT NULL DEFAULT 3,
                status VARCHAR(16) NOT NULL DEFAULT 'pending',
                trigger_strategy TEXT,
                alert_id VARCHAR(36),
                event_note TEXT,
                action_suggestion VARCHAR(16),
                actual_pnl FLOAT,
                review_summary TEXT,
                lessons_learned TEXT,
                note TEXT,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL
            )
        """))
        conn.execute(text("""
            INSERT INTO trade_plan_new (id, plan_type, risk_level, status, trigger_strategy, alert_id, event_note, action_suggestion, actual_pnl, review_summary, lessons_learned, note, created_at, updated_at)
            SELECT id, plan_type, risk_level, status, trigger_strategy, alert_id, event_note, action_suggestion, actual_pnl, review_summary, lessons_learned, note, created_at, updated_at
            FROM trade_plan
        """))
        conn.execute(text("DROP TABLE trade_plan"))
        conn.execute(text("ALTER TABLE trade_plan_new RENAME TO trade_plan"))

        # 3. 重建 trade_detail（ts_code 替代 plan_id）
        conn.execute(text("""
            CREATE TABLE trade_detail_new (
                id VARCHAR(36) PRIMARY KEY,
                ts_code VARCHAR(16) NOT NULL,
                trade_date VARCHAR(8) NOT NULL,
                trade_time VARCHAR(8),
                direction VARCHAR(4) NOT NULL,
                price FLOAT NOT NULL,
                quantity INTEGER NOT NULL,
                amount FLOAT NOT NULL,
                commission FLOAT DEFAULT 0,
                stamp_tax FLOAT DEFAULT 0,
                exec_note TEXT,
                created_at DATETIME NOT NULL
            )
        """))
        conn.execute(text("""
            INSERT INTO trade_detail_new (id, ts_code, trade_date, trade_time, direction, price, quantity, amount, commission, stamp_tax, exec_note, created_at)
            SELECT d.id, p.ts_code, d.trade_date, d.trade_time, d.direction, d.price, d.quantity, d.amount, d.commission, d.stamp_tax, d.exec_note, d.created_at
            FROM trade_detail d
            JOIN trade_plan_stock p ON d.plan_id = p.plan_id
        """))
        conn.execute(text("DROP TABLE trade_detail"))
        conn.execute(text("ALTER TABLE trade_detail_new RENAME TO trade_detail"))

        conn.execute(text("PRAGMA foreign_keys=ON"))
        conn.commit()
        print("迁移完成")


if __name__ == "__main__":
    migrate()
