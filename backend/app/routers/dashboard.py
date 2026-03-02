from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.database import get_db
from app.models.pool import WatchPool, WatchStock
from app.models.monitor import Alert
from app.models.trade import TradePlan
from app.models.stock import StockBasic

router = APIRouter(prefix="/api", tags=["dashboard"])


@router.get("/dashboard")
def get_dashboard(db: Session = Depends(get_db)):
    total_pools = db.query(func.count(WatchPool.id)).scalar()
    total_stocks = db.query(func.count(WatchStock.id)).scalar()
    monitoring_count = db.query(func.count(WatchStock.id)).filter(
        WatchStock.monitor_status == "monitoring"
    ).scalar()

    recent_alerts_raw = db.query(Alert).order_by(Alert.created_at.desc()).limit(10).all()
    recent_alerts = []
    for a in recent_alerts_raw:
        basic = db.query(StockBasic).filter(StockBasic.ts_code == a.ts_code).first()
        recent_alerts.append({
            "id": a.id,
            "ts_code": a.ts_code,
            "stock_name": basic.name if basic else None,
            "trigger_date": a.trigger_date,
            "status": a.status,
        })

    active_plans_raw = db.query(TradePlan).filter(
        TradePlan.status.in_(["pending", "active"])
    ).order_by(TradePlan.created_at.desc()).all()
    active_plans = []
    for p in active_plans_raw:
        active_plans.append({
            "id": p.id,
            "ts_code": p.ts_code,
            "stock_name": p.stock_name,
            "plan_type": p.plan_type,
            "status": p.status,
            "risk_level": p.risk_level,
            "risk_reward_ratio": p.risk_reward_ratio,
        })

    return {
        "pool_summary": {
            "total_pools": total_pools,
            "total_stocks": total_stocks,
            "monitoring_count": monitoring_count,
        },
        "recent_alerts": recent_alerts,
        "active_plans": active_plans,
    }
