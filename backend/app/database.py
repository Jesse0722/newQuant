from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from app.config import DATABASE_URL

connect_args = {"check_same_thread": False} if "sqlite" in DATABASE_URL else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
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
    import app.models  # noqa: F401
    Base.metadata.create_all(bind=engine)
