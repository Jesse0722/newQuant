from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class TemplateInfo(BaseModel):
    id: str
    name: str
    description: str
    default_params: dict


class MonitorRuleCreate(BaseModel):
    template_id: Optional[str] = None
    params: Optional[dict] = None
    logic: Optional[str] = "and"


class MonitorRuleUpdate(BaseModel):
    params: Optional[dict] = None
    logic: Optional[str] = None
    is_active: Optional[bool] = None


class MonitorRuleOut(BaseModel):
    id: str
    pool_id: Optional[str] = None
    stock_id: Optional[str] = None
    template_id: Optional[str] = None
    template_name: Optional[str] = None
    params: Optional[dict] = None
    logic: str
    is_active: bool
    created_at: datetime
    model_config = {"from_attributes": True}


class AlertOut(BaseModel):
    id: str
    stock_id: str
    rule_id: str
    ts_code: str
    stock_name: Optional[str] = None
    template_name: Optional[str] = None
    trigger_date: str
    status: str
    plan_id: Optional[str] = None
    snapshot: Optional[dict] = None
    created_at: datetime
    model_config = {"from_attributes": True}


class AlertUpdate(BaseModel):
    status: str


class AlertPagination(BaseModel):
    items: list[AlertOut]
    total: int
