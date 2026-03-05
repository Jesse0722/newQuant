from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class TradePlanStockCreate(BaseModel):
    ts_code: str
    risk_level: int = 3
    trigger_strategy: Optional[str] = None
    event_note: Optional[str] = None
    action_suggestion: Optional[str] = None
    planned_buy_price: Optional[float] = None
    target_price: Optional[float] = None
    stop_loss_price: Optional[float] = None
    position_plan: Optional[str] = None
    note: Optional[str] = None


class TradePlanStockOut(BaseModel):
    id: str
    plan_id: str
    ts_code: str
    stock_name: Optional[str] = None
    risk_level: int = 3
    trigger_strategy: Optional[str] = None
    event_note: Optional[str] = None
    action_suggestion: Optional[str] = None
    planned_buy_price: Optional[float] = None
    target_price: Optional[float] = None
    stop_loss_price: Optional[float] = None
    risk_reward_ratio: Optional[float] = None
    position_plan: Optional[str] = None
    note: Optional[str] = None
    details: list["TradeDetailOut"] = []
    model_config = {"from_attributes": True}


class TradePlanCreate(BaseModel):
    stocks: list[TradePlanStockCreate]
    plan_type: str
    alert_id: Optional[str] = None
    note: Optional[str] = None


class TradePlanStockUpdate(BaseModel):
    risk_level: Optional[int] = None
    trigger_strategy: Optional[str] = None
    event_note: Optional[str] = None
    action_suggestion: Optional[str] = None
    planned_buy_price: Optional[float] = None
    target_price: Optional[float] = None
    stop_loss_price: Optional[float] = None
    position_plan: Optional[str] = None
    note: Optional[str] = None


class TradePlanUpdate(BaseModel):
    plan_type: Optional[str] = None
    status: Optional[str] = None
    note: Optional[str] = None
    stocks: Optional[list[TradePlanStockCreate]] = None


class ReviewSubmit(BaseModel):
    review_summary: str
    lessons_learned: Optional[str] = None


class TradeDetailCreate(BaseModel):
    trade_date: str
    trade_time: Optional[str] = None
    direction: str
    price: float
    quantity: int
    commission: float = 0
    exec_note: Optional[str] = None


class TradeDetailUpdate(BaseModel):
    trade_date: Optional[str] = None
    trade_time: Optional[str] = None
    direction: Optional[str] = None
    price: Optional[float] = None
    quantity: Optional[int] = None
    commission: Optional[float] = None
    exec_note: Optional[str] = None


class TradeDetailOut(BaseModel):
    id: str
    ts_code: str
    trade_date: str
    trade_time: Optional[str] = None
    direction: str
    price: float
    quantity: int
    amount: float
    commission: float
    stamp_tax: float
    exec_note: Optional[str] = None
    created_at: datetime
    model_config = {"from_attributes": True}


TradePlanStockOut.model_rebuild()


class PnlSummary(BaseModel):
    total_buy_amount: float = 0
    total_sell_amount: float = 0
    total_commission: float = 0
    total_stamp_tax: float = 0
    net_pnl: float = 0
    holding_quantity: int = 0


class TradePlanOut(BaseModel):
    id: str
    plan_type: str
    status: str
    alert_id: Optional[str] = None
    actual_pnl: Optional[float] = None
    review_summary: Optional[str] = None
    lessons_learned: Optional[str] = None
    note: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    stocks: list[TradePlanStockOut] = []
    pnl_summary: Optional[PnlSummary] = None
    model_config = {"from_attributes": True}


class TradePlanPagination(BaseModel):
    items: list[TradePlanOut]
    total: int
