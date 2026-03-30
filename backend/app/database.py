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

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db():
    from scripts.migrate_trade_plan import migrate as migrate_trade_plan
    migrate_trade_plan()
    from scripts.migrate_plan_stock_fields import migrate as migrate_plan_stock_fields
    migrate_plan_stock_fields()
    from scripts.migrate_plan_title_remove_type import migrate as migrate_plan_title_remove_type
    migrate_plan_title_remove_type()
    from scripts.migrate_pool_sort_order import migrate as migrate_pool_sort_order
    migrate_pool_sort_order()
    from scripts.migrate_limit_up_fields import migrate as migrate_limit_up_fields
    migrate_limit_up_fields()
    from scripts.migrate_watch_stock_ai_fields import migrate as migrate_watch_stock_ai_fields
    migrate_watch_stock_ai_fields()
    from scripts.migrate_daily_quote_turnover import migrate as migrate_daily_quote_turnover
    migrate_daily_quote_turnover()
    from scripts.migrate_float_share import migrate as migrate_float_share
    migrate_float_share()
    from scripts.migrate_alert_buy_radar import migrate as migrate_alert_buy_radar
    migrate_alert_buy_radar()
    import app.models  # noqa: F401
    Base.metadata.create_all(bind=engine)
    _ensure_alert_buy_radar_columns(engine)


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
