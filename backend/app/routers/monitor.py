from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.monitor import MonitorRule
from app.schemas.monitor import (
    MonitorRuleCreate, MonitorRuleUpdate, MonitorRuleOut, TemplateInfo,
)
from app.services.monitor_engine import TEMPLATE_INFO, scan_pool, scan_all
from app.tasks.background import submit_task
from app.exceptions import AppError

router = APIRouter(prefix="/api/monitor", tags=["monitor"])


@router.get("/templates", response_model=list[TemplateInfo])
def list_templates():
    return [TemplateInfo(id=k, **v) for k, v in TEMPLATE_INFO.items()]


@router.get("/pools/{pool_id}/rules", response_model=list[MonitorRuleOut])
def get_pool_rules(pool_id: str, db: Session = Depends(get_db)):
    rules = db.query(MonitorRule).filter(MonitorRule.pool_id == pool_id).all()
    result = []
    for r in rules:
        out = MonitorRuleOut.model_validate(r)
        if r.template_id and r.template_id in TEMPLATE_INFO:
            out.template_name = TEMPLATE_INFO[r.template_id]["name"]
        result.append(out)
    return result


@router.post("/pools/{pool_id}/rules", response_model=MonitorRuleOut, status_code=201)
def create_pool_rule(pool_id: str, body: MonitorRuleCreate, db: Session = Depends(get_db)):
    rule = MonitorRule(pool_id=pool_id, **body.model_dump())
    db.add(rule)
    db.commit()
    db.refresh(rule)
    out = MonitorRuleOut.model_validate(rule)
    if rule.template_id and rule.template_id in TEMPLATE_INFO:
        out.template_name = TEMPLATE_INFO[rule.template_id]["name"]
    return out


@router.get("/stocks/{stock_id}/rules", response_model=list[MonitorRuleOut])
def get_stock_rules(stock_id: str, db: Session = Depends(get_db)):
    rules = db.query(MonitorRule).filter(MonitorRule.stock_id == stock_id).all()
    result = []
    for r in rules:
        out = MonitorRuleOut.model_validate(r)
        if r.template_id and r.template_id in TEMPLATE_INFO:
            out.template_name = TEMPLATE_INFO[r.template_id]["name"]
        result.append(out)
    return result


@router.post("/stocks/{stock_id}/rules", response_model=MonitorRuleOut, status_code=201)
def create_stock_rule(stock_id: str, body: MonitorRuleCreate, db: Session = Depends(get_db)):
    rule = MonitorRule(stock_id=stock_id, **body.model_dump())
    db.add(rule)
    db.commit()
    db.refresh(rule)
    out = MonitorRuleOut.model_validate(rule)
    if rule.template_id and rule.template_id in TEMPLATE_INFO:
        out.template_name = TEMPLATE_INFO[rule.template_id]["name"]
    return out


@router.put("/rules/{rule_id}", response_model=MonitorRuleOut)
def update_rule(rule_id: str, body: MonitorRuleUpdate, db: Session = Depends(get_db)):
    rule = db.query(MonitorRule).filter(MonitorRule.id == rule_id).first()
    if not rule:
        raise AppError(code=3001, message="规则不存在", status_code=404)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(rule, k, v)
    db.commit()
    db.refresh(rule)
    out = MonitorRuleOut.model_validate(rule)
    if rule.template_id and rule.template_id in TEMPLATE_INFO:
        out.template_name = TEMPLATE_INFO[rule.template_id]["name"]
    return out


@router.delete("/rules/{rule_id}", status_code=204)
def delete_rule(rule_id: str, db: Session = Depends(get_db)):
    rule = db.query(MonitorRule).filter(MonitorRule.id == rule_id).first()
    if not rule:
        raise AppError(code=3001, message="规则不存在", status_code=404)
    db.delete(rule)
    db.commit()


@router.post("/scan")
def manual_scan_all():
    task_id = submit_task("scan", scan_all)
    return {"task_id": task_id}


@router.post("/scan/{pool_id}")
def manual_scan_pool(pool_id: str):
    task_id = submit_task("scan", scan_pool, pool_id)
    return {"task_id": task_id}
