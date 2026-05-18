from __future__ import annotations

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base
from app.config import DATABASE_URL

connect_args = {"check_same_thread": False, "timeout": 30} if "sqlite" in DATABASE_URL else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)

if "sqlite" in DATABASE_URL:
    @event.listens_for(engine, "connect")
    def _sqlite_wal_and_busy(dbapi_conn, _connection_record):
        """允许读写并发、避免长事务时读连接永久阻塞。"""
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=15000")
        cur.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()
MIGRATION_RUNNERS = (
    ("trade_plan", "scripts.migrate_trade_plan", "migrate"),
    ("plan_stock_fields", "scripts.migrate_plan_stock_fields", "migrate"),
    ("plan_title_remove_type", "scripts.migrate_plan_title_remove_type", "migrate"),
    ("pool_sort_order", "scripts.migrate_pool_sort_order", "migrate"),
    ("limit_up_fields", "scripts.migrate_limit_up_fields", "migrate"),
    ("watch_stock_ai_fields", "scripts.migrate_watch_stock_ai_fields", "migrate"),
    ("stock_ai_analysis", "scripts.migrate_stock_ai_analysis", "migrate"),
    ("daily_quote_turnover", "scripts.migrate_daily_quote_turnover", "migrate"),
    ("float_share", "scripts.migrate_float_share", "migrate"),
    ("alert_buy_radar", "scripts.migrate_alert_buy_radar", "migrate"),
)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def run_startup_migrations():
    from importlib import import_module

    for _name, module_name, attr_name in MIGRATION_RUNNERS:
        getattr(import_module(module_name), attr_name)()


def create_schema():
    import app.models  # noqa: F401
    Base.metadata.create_all(bind=engine)
    _ensure_alert_buy_radar_columns(engine)


def init_db(run_migrations: bool = True, create_tables: bool = True):
    if run_migrations:
        run_startup_migrations()
    if create_tables:
        create_schema()


def _ensure_alert_buy_radar_columns(engine):
    """启动后校验 alert 表结构；若仍缺列则再执行一次迁移（避免路径不一致导致未迁移）。"""
    from sqlalchemy import inspect

    if "sqlite" not in str(engine.url):
        return
    insp = inspect(engine)
    if not insp.has_table("alert"):
        return
    names = {c["name"] for c in insp.get_columns("alert")}
    if "source" in names and "buy_strategy_id" in names:
        return
    from scripts.migrate_alert_buy_radar import migrate as migrate_alert_buy_radar

    migrate_alert_buy_radar()
