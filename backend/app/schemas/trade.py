from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Optional, Union
from pydantic import BaseModel, Field, field_validator

PositivePrice = Annotated[float, Field(gt=0, allow_inf_nan=False)]
NonnegativeFee = Annotated[float, Field(ge=0, allow_inf_nan=False)]
PositiveQuantity = Annotated[int, Field(gt=0, strict=True)]
PlanStatus = Literal["pending", "active", "completed", "cancelled"]


class ExecutionFields(BaseModel):
    @field_validator("trade_date", check_fields=False)
    @classmethod
    def valid_date(cls, value):
        if value is not None:
            if len(value) != 8 or not value.isdigit():
                raise ValueError("成交日期必须是 YYYYMMDD")
            datetime.strptime(value, "%Y%m%d")
        return value

    @field_validator("trade_time", check_fields=False)
    @classmethod
    def valid_time(cls, value):
        if value:
            datetime.strptime(value, "%H:%M:%S" if len(value) == 8 else "%H:%M")
        return value


class TradePlanStockCreate(BaseModel):
    ts_code: str
    risk_level: int = Field(2, ge=1, le=3)  # 1=低 2=中 3=高
    trigger_strategy: Optional[str] = None
    planned_buy_price: Optional[PositivePrice] = None
    target_price: Optional[PositivePrice] = None
    stop_loss_price: Optional[PositivePrice] = None
    position_plan: Optional[Union[str, int, float]] = None  # 数字百分比，如 30
    note: Optional[str] = None


class TradePlanStockOut(BaseModel):
    id: str
    plan_id: str
    ts_code: str
    stock_name: Optional[str] = None
    risk_level: int = 2  # 1=低 2=中 3=高
    trigger_strategy: Optional[str] = None
    planned_buy_price: Optional[float] = None
    target_price: Optional[float] = None
    stop_loss_price: Optional[float] = None
    risk_reward_ratio: Optional[float] = None
    position_plan: Optional[str] = None
    note: Optional[str] = None
    details: list["TradeDetailOut"] = []
    model_config = {"from_attributes": True}


class TradePlanCreate(BaseModel):
    title: str = Field(min_length=1, max_length=64)
    stocks: list[TradePlanStockCreate] = Field(min_length=1)
    alert_id: Optional[str] = None
    note: Optional[str] = None


class TradePlanStockUpdate(BaseModel):
    risk_level: Optional[int] = None
    trigger_strategy: Optional[str] = None
    planned_buy_price: Optional[float] = None
    target_price: Optional[float] = None
    stop_loss_price: Optional[float] = None
    position_plan: Optional[str] = None
    note: Optional[str] = None


class TradePlanUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=64)
    status: Optional[PlanStatus] = None
    note: Optional[str] = None
    stocks: Optional[list[TradePlanStockCreate]] = Field(None, min_length=1)

    @field_validator("title", "status", "stocks")
    @classmethod
    def not_null(cls, value):
        if value is None:
            raise ValueError("该字段不能为 null；不修改时请省略")
        return value


class ReviewSubmit(BaseModel):
    review_summary: str
    lessons_learned: Optional[str] = None


class TradeDetailCreate(ExecutionFields):
    trade_date: str
    trade_time: Optional[str] = None
    direction: Literal["buy", "sell"]
    price: PositivePrice
    quantity: PositiveQuantity
    commission: NonnegativeFee = 0
    exec_note: Optional[str] = None


class TradeDetailUpdate(ExecutionFields):
    trade_date: Optional[str] = None
    trade_time: Optional[str] = None
    direction: Optional[Literal["buy", "sell"]] = None
    price: Optional[PositivePrice] = None
    quantity: Optional[PositiveQuantity] = None
    commission: Optional[NonnegativeFee] = None
    exec_note: Optional[str] = None

    @field_validator("trade_date", "direction", "price", "quantity", "commission")
    @classmethod
    def not_null(cls, value):
        if value is None:
            raise ValueError("该字段不能为 null；不修改时请省略")
        return value


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
    title: str
    status: str
    alert_id: Optional[str] = None
    actual_pnl: Optional[float] = None
    review_pnl_snapshot: Optional[float] = None
    pnl_scope: Literal["stock_lifetime"] = "stock_lifetime"
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
