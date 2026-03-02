from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.trade import TradePlan, TradeDetail
from app.models.stock import StockBasic
from app.schemas.trade import (
    TradePlanCreate, TradePlanUpdate, TradePlanOut, TradePlanPagination,
    TradeDetailCreate, TradeDetailUpdate, TradeDetailOut,
    ReviewSubmit, PnlSummary,
)
from app.exceptions import AppError
from app.utils import normalize_ts_code

router = APIRouter(prefix="/api", tags=["plans"])


def _calc_risk_reward(plan: TradePlan) -> float | None:
    if plan.planned_buy_price and plan.target_price and plan.stop_loss_price:
        denom = plan.planned_buy_price - plan.stop_loss_price
        if denom > 0:
            return round((plan.target_price - plan.planned_buy_price) / denom, 2)
    return None


def _calc_pnl(db: Session, plan_id: str) -> PnlSummary:
    details = db.query(TradeDetail).filter(TradeDetail.plan_id == plan_id).all()
    summary = PnlSummary()
    for d in details:
        if d.direction == "buy":
            summary.total_buy_amount += d.amount
            summary.holding_quantity += d.quantity
        elif d.direction == "sell":
            summary.total_sell_amount += d.amount
            summary.holding_quantity -= d.quantity
        summary.total_commission += d.commission
        summary.total_stamp_tax += d.stamp_tax
    summary.net_pnl = round(
        summary.total_sell_amount - summary.total_buy_amount - summary.total_commission - summary.total_stamp_tax, 2
    )
    return summary


def _enrich_plan(db: Session, plan: TradePlan, include_details: bool = False) -> TradePlanOut:
    out = TradePlanOut.model_validate(plan)
    out.risk_reward_ratio = _calc_risk_reward(plan)
    if include_details:
        details = db.query(TradeDetail).filter(TradeDetail.plan_id == plan.id).order_by(TradeDetail.trade_date).all()
        out.details = [TradeDetailOut.model_validate(d) for d in details]
        out.pnl_summary = _calc_pnl(db, plan.id)
    return out


# --- 交易计划 CRUD ---

@router.get("/plans", response_model=TradePlanPagination)
def list_plans(
    status: str = Query(None),
    plan_type: str = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    q = db.query(TradePlan)
    if status:
        q = q.filter(TradePlan.status == status)
    if plan_type:
        q = q.filter(TradePlan.plan_type == plan_type)
    total = q.count()
    items = q.order_by(TradePlan.created_at.desc()).offset((page - 1) * size).limit(size).all()
    return TradePlanPagination(
        items=[_enrich_plan(db, p) for p in items],
        total=total,
    )


@router.post("/plans", response_model=TradePlanOut, status_code=201)
def create_plan(body: TradePlanCreate, db: Session = Depends(get_db)):
    try:
        ts_code = normalize_ts_code(body.ts_code)
    except ValueError as e:
        raise AppError(code=4004, message=str(e))
    basic = db.query(StockBasic).filter(StockBasic.ts_code == ts_code).first()
    data = body.model_dump()
    data["ts_code"] = ts_code
    plan = TradePlan(**data)
    plan.stock_name = basic.name if basic else None
    plan.risk_reward_ratio = _calc_risk_reward(plan)
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return _enrich_plan(db, plan)


@router.get("/plans/{plan_id}", response_model=TradePlanOut)
def get_plan(plan_id: str, db: Session = Depends(get_db)):
    plan = db.query(TradePlan).filter(TradePlan.id == plan_id).first()
    if not plan:
        raise AppError(code=4001, message="交易计划不存在", status_code=404)
    return _enrich_plan(db, plan, include_details=True)


@router.put("/plans/{plan_id}", response_model=TradePlanOut)
def update_plan(plan_id: str, body: TradePlanUpdate, db: Session = Depends(get_db)):
    plan = db.query(TradePlan).filter(TradePlan.id == plan_id).first()
    if not plan:
        raise AppError(code=4001, message="交易计划不存在", status_code=404)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(plan, k, v)
    plan.risk_reward_ratio = _calc_risk_reward(plan)
    db.commit()
    db.refresh(plan)
    return _enrich_plan(db, plan, include_details=True)


@router.delete("/plans/{plan_id}", status_code=204)
def delete_plan(plan_id: str, db: Session = Depends(get_db)):
    plan = db.query(TradePlan).filter(TradePlan.id == plan_id).first()
    if not plan:
        raise AppError(code=4001, message="交易计划不存在", status_code=404)
    db.delete(plan)
    db.commit()


@router.put("/plans/{plan_id}/review", response_model=TradePlanOut)
def submit_review(plan_id: str, body: ReviewSubmit, db: Session = Depends(get_db)):
    plan = db.query(TradePlan).filter(TradePlan.id == plan_id).first()
    if not plan:
        raise AppError(code=4001, message="交易计划不存在", status_code=404)
    plan.review_summary = body.review_summary
    plan.lessons_learned = body.lessons_learned
    pnl = _calc_pnl(db, plan.id)
    plan.actual_pnl = pnl.net_pnl
    db.commit()
    db.refresh(plan)
    return _enrich_plan(db, plan, include_details=True)


# --- 交易明细 CRUD ---

@router.get("/plans/{plan_id}/details", response_model=list[TradeDetailOut])
def list_details(plan_id: str, db: Session = Depends(get_db)):
    plan = db.query(TradePlan).filter(TradePlan.id == plan_id).first()
    if not plan:
        raise AppError(code=4001, message="交易计划不存在", status_code=404)
    details = db.query(TradeDetail).filter(TradeDetail.plan_id == plan_id).order_by(TradeDetail.trade_date).all()
    return [TradeDetailOut.model_validate(d) for d in details]


@router.post("/plans/{plan_id}/details", response_model=TradeDetailOut, status_code=201)
def create_detail(plan_id: str, body: TradeDetailCreate, db: Session = Depends(get_db)):
    plan = db.query(TradePlan).filter(TradePlan.id == plan_id).first()
    if not plan:
        raise AppError(code=4001, message="交易计划不存在", status_code=404)
    amount = round(body.price * body.quantity, 2)
    stamp_tax = round(amount * 0.0005, 2) if body.direction == "sell" else 0.0
    detail = TradeDetail(
        plan_id=plan_id,
        amount=amount,
        stamp_tax=stamp_tax,
        **body.model_dump(),
    )
    db.add(detail)
    # 更新计划实际盈亏
    db.flush()
    pnl = _calc_pnl(db, plan_id)
    plan.actual_pnl = pnl.net_pnl
    db.commit()
    db.refresh(detail)
    return TradeDetailOut.model_validate(detail)


@router.put("/details/{detail_id}", response_model=TradeDetailOut)
def update_detail(detail_id: str, body: TradeDetailUpdate, db: Session = Depends(get_db)):
    detail = db.query(TradeDetail).filter(TradeDetail.id == detail_id).first()
    if not detail:
        raise AppError(code=4003, message="交易明细不存在", status_code=404)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(detail, k, v)
    detail.amount = round(detail.price * detail.quantity, 2)
    detail.stamp_tax = round(detail.amount * 0.0005, 2) if detail.direction == "sell" else 0.0
    plan = db.query(TradePlan).filter(TradePlan.id == detail.plan_id).first()
    db.flush()
    pnl = _calc_pnl(db, detail.plan_id)
    if plan:
        plan.actual_pnl = pnl.net_pnl
    db.commit()
    db.refresh(detail)
    return TradeDetailOut.model_validate(detail)


@router.delete("/details/{detail_id}", status_code=204)
def delete_detail(detail_id: str, db: Session = Depends(get_db)):
    detail = db.query(TradeDetail).filter(TradeDetail.id == detail_id).first()
    if not detail:
        raise AppError(code=4003, message="交易明细不存在", status_code=404)
    plan_id = detail.plan_id
    db.delete(detail)
    db.flush()
    plan = db.query(TradePlan).filter(TradePlan.id == plan_id).first()
    if plan:
        pnl = _calc_pnl(db, plan_id)
        plan.actual_pnl = pnl.net_pnl
    db.commit()
