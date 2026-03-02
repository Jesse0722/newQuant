from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.monitor import Alert, MonitorRule
from app.models.stock import StockBasic
from app.models.trade import TradePlan
from app.schemas.monitor import AlertOut, AlertUpdate, AlertPagination
from app.services.monitor_engine import TEMPLATE_INFO
from app.exceptions import AppError

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


def _enrich_alert(db: Session, alert: Alert) -> AlertOut:
    out = AlertOut.model_validate(alert)
    basic = db.query(StockBasic).filter(StockBasic.ts_code == alert.ts_code).first()
    out.stock_name = basic.name if basic else None
    rule = db.query(MonitorRule).filter(MonitorRule.id == alert.rule_id).first()
    if rule and rule.template_id and rule.template_id in TEMPLATE_INFO:
        out.template_name = TEMPLATE_INFO[rule.template_id]["name"]
    return out


@router.get("", response_model=AlertPagination)
def list_alerts(
    status: str = Query(None),
    ts_code: str = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    q = db.query(Alert)
    if status:
        q = q.filter(Alert.status == status)
    if ts_code:
        q = q.filter(Alert.ts_code == ts_code)
    total = q.count()
    items = q.order_by(Alert.created_at.desc()).offset((page - 1) * size).limit(size).all()
    return AlertPagination(
        items=[_enrich_alert(db, a) for a in items],
        total=total,
    )


@router.get("/{alert_id}", response_model=AlertOut)
def get_alert(alert_id: str, db: Session = Depends(get_db)):
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise AppError(code=3003, message="提醒不存在", status_code=404)
    return _enrich_alert(db, alert)


@router.put("/{alert_id}", response_model=AlertOut)
def update_alert(alert_id: str, body: AlertUpdate, db: Session = Depends(get_db)):
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise AppError(code=3003, message="提醒不存在", status_code=404)
    alert.status = body.status
    db.commit()
    db.refresh(alert)
    return _enrich_alert(db, alert)


@router.post("/{alert_id}/create-plan", status_code=201)
def create_plan_from_alert(alert_id: str, db: Session = Depends(get_db)):
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise AppError(code=3003, message="提醒不存在", status_code=404)
    basic = db.query(StockBasic).filter(StockBasic.ts_code == alert.ts_code).first()
    rule = db.query(MonitorRule).filter(MonitorRule.id == alert.rule_id).first()
    trigger_desc = ""
    if rule and rule.template_id and rule.template_id in TEMPLATE_INFO:
        trigger_desc = TEMPLATE_INFO[rule.template_id]["name"]
    plan = TradePlan(
        ts_code=alert.ts_code,
        stock_name=basic.name if basic else None,
        plan_type="short_term",
        trigger_strategy=trigger_desc,
        alert_id=alert.id,
    )
    db.add(plan)
    alert.status = "processed"
    alert.plan_id = plan.id
    db.commit()
    db.refresh(plan)
    return {"id": plan.id, "ts_code": plan.ts_code, "stock_name": plan.stock_name, "status": plan.status}
