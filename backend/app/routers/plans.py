from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.trade import TradePlan, TradePlanStock, TradeDetail
from app.models.stock import StockBasic
from app.schemas.trade import (
    TradePlanCreate, TradePlanUpdate, TradePlanOut, TradePlanPagination,
    TradePlanStockCreate, TradePlanStockOut,
    TradeDetailCreate, TradeDetailUpdate, TradeDetailOut,
    ReviewSubmit, PnlSummary,
)
from app.exceptions import AppError
from app.utils import normalize_ts_code

router = APIRouter(prefix="/api", tags=["plans"])


def _calc_risk_reward(ps: TradePlanStock) -> float | None:
    if ps.planned_buy_price and ps.target_price and ps.stop_loss_price:
        denom = ps.planned_buy_price - ps.stop_loss_price
        if denom > 0:
            return round((ps.target_price - ps.planned_buy_price) / denom, 2)
    return None


def _calc_pnl_for_ts_codes(db: Session, ts_codes: list[str]) -> PnlSummary:
    summary = PnlSummary()
    if not ts_codes:
        return summary
    details = (
        db.query(TradeDetail)
        .filter(TradeDetail.ts_code.in_(ts_codes))
        .order_by(TradeDetail.trade_date)
        .all()
    )
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
    ts_codes = [ps.ts_code for ps in plan.stocks]
    pnl = _calc_pnl_for_ts_codes(db, ts_codes)
    out = TradePlanOut(
        id=plan.id,
        title=plan.title,
        status=plan.status,
        alert_id=plan.alert_id,
        actual_pnl=plan.actual_pnl if plan.actual_pnl is not None else pnl.net_pnl,
        review_summary=plan.review_summary,
        lessons_learned=plan.lessons_learned,
        note=plan.note,
        created_at=plan.created_at,
        updated_at=plan.updated_at,
        stocks=[],
        pnl_summary=pnl,
    )
    for ps in plan.stocks:
        stock_out = TradePlanStockOut(
            id=ps.id,
            plan_id=ps.plan_id,
            ts_code=ps.ts_code,
            stock_name=ps.stock_name,
            risk_level=ps.risk_level if ps.risk_level is not None else 2,
            trigger_strategy=ps.trigger_strategy,
            planned_buy_price=ps.planned_buy_price,
            target_price=ps.target_price,
            stop_loss_price=ps.stop_loss_price,
            risk_reward_ratio=_calc_risk_reward(ps) or ps.risk_reward_ratio,
            position_plan=ps.position_plan,
            note=ps.note,
            details=[],
        )
        if include_details:
            details = (
                db.query(TradeDetail)
                .filter(TradeDetail.ts_code == ps.ts_code)
                .order_by(TradeDetail.trade_date)
                .all()
            )
            stock_out.details = [TradeDetailOut.model_validate(d) for d in details]
        out.stocks.append(stock_out)
    return out


# --- 交易计划 CRUD ---

@router.get("/plans", response_model=TradePlanPagination)
def list_plans(
    status: str = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    q = db.query(TradePlan)
    if status:
        q = q.filter(TradePlan.status == status)
    total = q.count()
    items = q.order_by(TradePlan.created_at.desc()).offset((page - 1) * size).limit(size).all()
    return TradePlanPagination(
        items=[_enrich_plan(db, p) for p in items],
        total=total,
    )


@router.post("/plans", response_model=TradePlanOut, status_code=201)
def create_plan(body: TradePlanCreate, db: Session = Depends(get_db)):
    if not body.stocks:
        raise AppError(code=4004, message="至少需要一只股票", status_code=400)
    plan = TradePlan(
        title=body.title,
        alert_id=body.alert_id,
        note=body.note,
    )
    db.add(plan)
    db.flush()
    for s in body.stocks:
        try:
            ts_code = normalize_ts_code(s.ts_code)
        except ValueError as e:
            raise AppError(code=4004, message=str(e))
        basic = db.query(StockBasic).filter(StockBasic.ts_code == ts_code).first()
        rr = None
        if s.planned_buy_price and s.target_price and s.stop_loss_price and (s.planned_buy_price - s.stop_loss_price) > 0:
            rr = round((s.target_price - s.planned_buy_price) / (s.planned_buy_price - s.stop_loss_price), 2)
        ps = TradePlanStock(
            plan_id=plan.id,
            ts_code=ts_code,
            stock_name=basic.name if basic else None,
            risk_level=s.risk_level if s.risk_level is not None else 2,
            trigger_strategy=s.trigger_strategy,
            planned_buy_price=s.planned_buy_price,
            target_price=s.target_price,
            stop_loss_price=s.stop_loss_price,
            risk_reward_ratio=rr,
            position_plan=str(s.position_plan) if s.position_plan is not None else None,
            note=s.note,
        )
        db.add(ps)
    db.commit()
    db.refresh(plan)
    return _enrich_plan(db, plan, include_details=True)


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
        if k == "stocks":
            if v is not None:
                for ps in plan.stocks[:]:
                    db.delete(ps)
                for s in v:
                    ts_code = normalize_ts_code(s.ts_code)
                    basic = db.query(StockBasic).filter(StockBasic.ts_code == ts_code).first()
                    rr = None
                    if s.planned_buy_price and s.target_price and s.stop_loss_price and (s.planned_buy_price - s.stop_loss_price) > 0:
                        rr = round((s.target_price - s.planned_buy_price) / (s.planned_buy_price - s.stop_loss_price), 2)
                    ps = TradePlanStock(
                        plan_id=plan.id,
                        ts_code=ts_code,
                        stock_name=basic.name if basic else None,
                        risk_level=getattr(s, "risk_level", 2) or 2,
                        trigger_strategy=getattr(s, "trigger_strategy", None),
                        planned_buy_price=s.planned_buy_price,
                        target_price=s.target_price,
                        stop_loss_price=s.stop_loss_price,
                        risk_reward_ratio=rr,
                        position_plan=str(s.position_plan) if s.position_plan is not None else None,
                        note=s.note,
                    )
                    db.add(ps)
        else:
            setattr(plan, k, v)
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
    ts_codes = [ps.ts_code for ps in plan.stocks]
    pnl = _calc_pnl_for_ts_codes(db, ts_codes)
    plan.actual_pnl = pnl.net_pnl
    db.commit()
    db.refresh(plan)
    return _enrich_plan(db, plan, include_details=True)


# --- 交易明细（按股票，保留编辑/删除）---

@router.put("/details/{detail_id}", response_model=TradeDetailOut)
def update_detail(detail_id: str, body: TradeDetailUpdate, db: Session = Depends(get_db)):
    detail = db.query(TradeDetail).filter(TradeDetail.id == detail_id).first()
    if not detail:
        raise AppError(code=4003, message="交易明细不存在", status_code=404)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(detail, k, v)
    detail.amount = round(detail.price * detail.quantity, 2)
    detail.stamp_tax = round(detail.amount * 0.0005, 2) if detail.direction == "sell" else 0.0
    db.commit()
    db.refresh(detail)
    return TradeDetailOut.model_validate(detail)


@router.delete("/details/{detail_id}", status_code=204)
def delete_detail(detail_id: str, db: Session = Depends(get_db)):
    detail = db.query(TradeDetail).filter(TradeDetail.id == detail_id).first()
    if not detail:
        raise AppError(code=4003, message="交易明细不存在", status_code=404)
    db.delete(detail)
    db.commit()
