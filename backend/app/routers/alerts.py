from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.monitor import Alert, MonitorRule
from app.models.stock import StockBasic
from app.models.trade import TradePlan, TradePlanStock
from app.schemas.monitor import AlertOut, AlertUpdate, AlertPagination, AlertBatchCountOut
from app.services.monitor_engine import TEMPLATE_INFO
from app.services.buy_signal_service import STRATEGY_REGISTRY
from app.exceptions import AppError

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


def _plan_note_from_buy_signal(sig: dict) -> str | None:
    parts: list[str] = []
    if sig.get("signal_score") is not None:
        parts.append(f"评分 {sig['signal_score']}")
    if sig.get("stop_loss_price") is not None:
        parts.append(f"止损 {sig['stop_loss_price']}")
    if sig.get("target_price") is not None:
        parts.append(f"目标 {sig['target_price']}")
    if sig.get("risk_reward_ratio") is not None:
        parts.append(f"盈亏比 {sig['risk_reward_ratio']}")
    return "；".join(parts) if parts else None


def _enrich_alert(db: Session, alert: Alert) -> AlertOut:
    out = AlertOut.model_validate(alert)
    basic = db.query(StockBasic).filter(StockBasic.ts_code == alert.ts_code).first()
    out.stock_name = basic.name if basic else None
    snap = alert.snapshot if isinstance(alert.snapshot, dict) else {}
    sig = snap.get("signal")
    meta = snap.get("scan_meta")
    if isinstance(sig, dict):
        out.buy_signal = sig
    if isinstance(meta, dict):
        out.scan_meta = meta
    if basic and basic.industry:
        out.industry = basic.industry
    elif isinstance(sig, dict) and sig.get("industry"):
        out.industry = sig.get("industry")
    if alert.source == "buy_radar":
        sid = alert.buy_strategy_id or (sig.get("strategy_id") if isinstance(sig, dict) else None)
        out.strategy_name = STRATEGY_REGISTRY.get(sid or "", {}).get("name", sid)
        out.template_name = out.strategy_name
    elif alert.rule_id:
        rule = db.query(MonitorRule).filter(MonitorRule.id == alert.rule_id).first()
        if rule and rule.template_id and rule.template_id in TEMPLATE_INFO:
            out.template_name = TEMPLATE_INFO[rule.template_id]["name"]
    return out


@router.get("/pending-count", response_model=AlertBatchCountOut)
def alerts_pending_count(
    source: str = Query("buy_radar"),
    db: Session = Depends(get_db),
):
    q = db.query(Alert).filter(Alert.status == "pending")
    if source and source != "all":
        q = q.filter(Alert.source == source)
    return AlertBatchCountOut(count=q.count())


@router.get("", response_model=AlertPagination)
def list_alerts(
    status: str = Query(None),
    ts_code: str = Query(None),
    source: str = Query("buy_radar"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    q = db.query(Alert)
    if status:
        q = q.filter(Alert.status == status)
    if ts_code:
        q = q.filter(Alert.ts_code == ts_code)
    if source and source != "all":
        q = q.filter(Alert.source == source)
    total = q.count()
    items = q.order_by(Alert.created_at.desc()).offset((page - 1) * size).limit(size).all()
    return AlertPagination(
        items=[_enrich_alert(db, a) for a in items],
        total=total,
    )


@router.post("/batch-dismiss-pending", response_model=AlertBatchCountOut)
def batch_dismiss_pending(
    source: str = Query("buy_radar"),
    db: Session = Depends(get_db),
):
    q = db.query(Alert).filter(Alert.status == "pending")
    if source and source != "all":
        q = q.filter(Alert.source == source)
    n = q.update({"status": "dismissed"}, synchronize_session=False)
    db.commit()
    return AlertBatchCountOut(count=n)


@router.post("/batch-delete-dismissed", response_model=AlertBatchCountOut)
def batch_delete_dismissed(
    source: str = Query("buy_radar"),
    db: Session = Depends(get_db),
):
    q = db.query(Alert).filter(Alert.status == "dismissed")
    if source and source != "all":
        q = q.filter(Alert.source == source)
    n = q.delete(synchronize_session=False)
    db.commit()
    return AlertBatchCountOut(count=n)


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
    snap = alert.snapshot if isinstance(alert.snapshot, dict) else {}
    sig = snap.get("signal") if isinstance(snap.get("signal"), dict) else {}
    trigger_desc = ""
    note: str | None = None
    if alert.source == "buy_radar":
        sid = alert.buy_strategy_id or sig.get("strategy_id")
        trigger_desc = STRATEGY_REGISTRY.get(sid or "", {}).get("name", sid or "买点策略")
        note = _plan_note_from_buy_signal(sig) if sig else None
    elif alert.rule_id:
        rule = db.query(MonitorRule).filter(MonitorRule.id == alert.rule_id).first()
        if rule and rule.template_id and rule.template_id in TEMPLATE_INFO:
            trigger_desc = TEMPLATE_INFO[rule.template_id]["name"]
    stock_label = basic.name if basic else alert.ts_code
    plan = TradePlan(
        title=f"{stock_label} - 提醒触发",
        alert_id=alert.id,
    )
    db.add(plan)
    db.flush()
    ps = TradePlanStock(
        plan_id=plan.id,
        ts_code=alert.ts_code,
        stock_name=basic.name if basic else None,
        trigger_strategy=trigger_desc or "监控提醒",
        note=note,
        risk_level=2,
    )
    db.add(ps)
    alert.status = "processed"
    alert.plan_id = plan.id
    db.commit()
    db.refresh(plan)
    return {"id": plan.id, "ts_code": alert.ts_code, "stock_name": basic.name if basic else None, "status": plan.status}
