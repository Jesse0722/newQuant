"""Alert 表：source、buy_strategy_id、rule_id 可空（SQLite 必要时整表重建）。"""
import sqlite3
from app.config import DATABASE_URL


def _needs_rebuild(cur) -> bool:
    cur.execute("PRAGMA table_info(alert)")
    rows = cur.fetchall()
    if not rows:
        return False
    colnames = [r[1] for r in rows]
    if "source" not in colnames or "buy_strategy_id" not in colnames:
        return True
    rule_row = next((r for r in rows if r[1] == "rule_id"), None)
    if rule_row is not None and rule_row[3] == 1:
        return True
    return False


def migrate():
    if "sqlite" not in DATABASE_URL:
        return
    db_path = DATABASE_URL.replace("sqlite:///", "")
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='alert'")
    if not cur.fetchone():
        conn.close()
        return
    if not _needs_rebuild(cur):
        conn.close()
        return
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS alert_new (
            id VARCHAR(36) NOT NULL PRIMARY KEY,
            stock_id VARCHAR(36) NOT NULL,
            rule_id VARCHAR(36),
            ts_code VARCHAR(16) NOT NULL,
            trigger_date VARCHAR(8) NOT NULL,
            status VARCHAR(16) NOT NULL DEFAULT 'pending',
            plan_id VARCHAR(36),
            snapshot JSON,
            created_at DATETIME NOT NULL,
            source VARCHAR(16) NOT NULL DEFAULT 'monitor',
            buy_strategy_id VARCHAR(64),
            FOREIGN KEY(stock_id) REFERENCES watch_stock (id),
            FOREIGN KEY(rule_id) REFERENCES monitor_rule (id),
            FOREIGN KEY(plan_id) REFERENCES trade_plan (id)
        )
        """
    )
    cur.execute(
        """
        INSERT INTO alert_new (
            id, stock_id, rule_id, ts_code, trigger_date, status, plan_id, snapshot, created_at, source, buy_strategy_id
        )
        SELECT id, stock_id, rule_id, ts_code, trigger_date, status, plan_id, snapshot, created_at, 'monitor', NULL
        FROM alert
        """
    )
    cur.execute("DROP TABLE alert")
    cur.execute("ALTER TABLE alert_new RENAME TO alert")
    conn.commit()
    conn.close()
