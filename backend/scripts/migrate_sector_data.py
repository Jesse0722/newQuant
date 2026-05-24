"""新增板块基础、个股-板块映射、板块日线三张表（SQLite 专用迁移）"""

from __future__ import annotations

import sqlite3

from app.config import DATABASE_URL


def _has_table(cur: sqlite3.Cursor, name: str) -> bool:
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,))
    return cur.fetchone() is not None


def migrate():
    if "sqlite" not in DATABASE_URL:
        return
    db_path = DATABASE_URL.replace("sqlite:///", "")
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    if not _has_table(cur, "sector_basic"):
        cur.execute(
            """
            CREATE TABLE sector_basic (
                id VARCHAR(36) PRIMARY KEY,
                sector_code VARCHAR(32) NOT NULL UNIQUE,
                sector_name VARCHAR(64) NOT NULL,
                sector_type VARCHAR(16) NOT NULL DEFAULT 'concept',
                source VARCHAR(32) NOT NULL DEFAULT 'eastmoney',
                raw_code VARCHAR(32),
                rank INTEGER,
                latest_pct_chg REAL,
                latest_hot REAL,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL
            )
            """
        )
        cur.execute("CREATE INDEX ix_sector_basic_sector_code ON sector_basic (sector_code)")
        cur.execute("CREATE INDEX ix_sector_basic_sector_name ON sector_basic (sector_name)")
        cur.execute("CREATE INDEX ix_sector_basic_sector_type ON sector_basic (sector_type)")
        cur.execute("CREATE INDEX ix_sector_basic_source ON sector_basic (source)")

    if not _has_table(cur, "stock_sector_map"):
        cur.execute(
            """
            CREATE TABLE stock_sector_map (
                id VARCHAR(36) PRIMARY KEY,
                ts_code VARCHAR(16) NOT NULL,
                sector_code VARCHAR(32) NOT NULL,
                sector_name VARCHAR(64) NOT NULL,
                sector_type VARCHAR(16) NOT NULL DEFAULT 'concept',
                source VARCHAR(32) NOT NULL DEFAULT 'eastmoney',
                weight REAL,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                CONSTRAINT uq_stock_sector_source UNIQUE (ts_code, sector_code, source)
            )
            """
        )
        cur.execute("CREATE INDEX ix_stock_sector_map_ts_code ON stock_sector_map (ts_code)")
        cur.execute("CREATE INDEX ix_stock_sector_map_sector_code ON stock_sector_map (sector_code)")
        cur.execute("CREATE INDEX ix_stock_sector_map_sector_name ON stock_sector_map (sector_name)")
        cur.execute("CREATE INDEX ix_stock_sector_map_sector_type ON stock_sector_map (sector_type)")
        cur.execute("CREATE INDEX ix_stock_sector_map_source ON stock_sector_map (source)")
        cur.execute("CREATE INDEX ix_stock_sector_type_code ON stock_sector_map (sector_type, sector_code)")

    if not _has_table(cur, "sector_daily_quote"):
        cur.execute(
            """
            CREATE TABLE sector_daily_quote (
                sector_code VARCHAR(32) NOT NULL,
                trade_date VARCHAR(8) NOT NULL,
                sector_name VARCHAR(64) NOT NULL,
                sector_type VARCHAR(16) NOT NULL DEFAULT 'concept',
                source VARCHAR(32) NOT NULL DEFAULT 'eastmoney',
                open REAL,
                high REAL,
                low REAL,
                close REAL,
                pct_chg REAL,
                change REAL,
                vol REAL,
                amount REAL,
                turnover_rate REAL,
                updated_at DATETIME NOT NULL,
                PRIMARY KEY (sector_code, trade_date)
            )
            """
        )
        cur.execute("CREATE INDEX ix_sector_daily_quote_sector_name ON sector_daily_quote (sector_name)")
        cur.execute("CREATE INDEX ix_sector_daily_quote_sector_type ON sector_daily_quote (sector_type)")
        cur.execute("CREATE INDEX ix_sector_daily_quote_source ON sector_daily_quote (source)")
        cur.execute("CREATE INDEX ix_sector_daily_type_date ON sector_daily_quote (sector_type, trade_date)")

    if not _has_table(cur, "sector_quote_sync_state"):
        cur.execute(
            """
            CREATE TABLE sector_quote_sync_state (
                id VARCHAR(36) PRIMARY KEY,
                sector_code VARCHAR(32) NOT NULL,
                sector_name VARCHAR(64) NOT NULL,
                sector_type VARCHAR(16) NOT NULL DEFAULT 'concept',
                source VARCHAR(32) NOT NULL DEFAULT 'eastmoney_direct',
                status VARCHAR(16) NOT NULL DEFAULT 'pending',
                target_days INTEGER,
                quote_count INTEGER NOT NULL DEFAULT 0,
                first_trade_date VARCHAR(8),
                last_trade_date VARCHAR(8),
                attempts INTEGER NOT NULL DEFAULT 0,
                last_error VARCHAR(512),
                next_retry_at DATETIME,
                last_success_at DATETIME,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                CONSTRAINT uq_sector_quote_sync_source UNIQUE (sector_code, source)
            )
            """
        )
        cur.execute("CREATE INDEX ix_sector_quote_sync_state_sector_code ON sector_quote_sync_state (sector_code)")
        cur.execute("CREATE INDEX ix_sector_quote_sync_state_sector_name ON sector_quote_sync_state (sector_name)")
        cur.execute("CREATE INDEX ix_sector_quote_sync_state_sector_type ON sector_quote_sync_state (sector_type)")
        cur.execute("CREATE INDEX ix_sector_quote_sync_state_source ON sector_quote_sync_state (source)")
        cur.execute("CREATE INDEX ix_sector_quote_sync_state_status ON sector_quote_sync_state (status)")
        cur.execute("CREATE INDEX ix_sector_quote_sync_status_retry ON sector_quote_sync_state (status, next_retry_at)")

    conn.commit()
    conn.close()
