from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class PoolCreate(BaseModel):
    name: str
    description: Optional[str] = None
    default_monitor_rule: Optional[dict] = None


class PoolUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    default_monitor_rule: Optional[dict] = None
    trigger_target_pool_id: Optional[str] = None


class PoolOut(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    default_monitor_rule: Optional[dict] = None
    trigger_target_pool_id: Optional[str] = None
    stock_count: int = 0
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}


class WatchStockCreate(BaseModel):
    ts_code: str
    added_price: Optional[float] = None
    note: Optional[str] = None


class WatchStockUpdate(BaseModel):
    added_price: Optional[float] = None
    note: Optional[str] = None
    monitor_status: Optional[str] = None
    pinned: Optional[bool] = None


class WatchStockOut(BaseModel):
    id: str
    pool_id: str
    ts_code: str
    stock_name: Optional[str] = None
    added_at: datetime
    added_price: Optional[float] = None
    latest_price: Optional[float] = None
    pct_chg: Optional[float] = None
    industry: Optional[str] = None
    trade_date: Optional[str] = None
    source: str
    monitor_status: str
    pinned: bool = False
    note: Optional[str] = None
    limit_up_date: Optional[str] = None
    created_at: datetime
    model_config = {"from_attributes": True}


class CSVImportResult(BaseModel):
    imported: int = 0
    skipped: int = 0
    errors: list[str] = []


class BatchAddStocks(BaseModel):
    ts_codes: list[str]
    added_price: Optional[float] = None
    note: Optional[str] = None


class BatchAddResult(BaseModel):
    added: int = 0
    skipped: int = 0
    errors: list[str] = []


class QuickCreatePool(BaseModel):
    name: str
    ts_codes: list[str]
    description: Optional[str] = None


class WatchStockPagination(BaseModel):
    items: list[WatchStockOut]
    total: int


class CoreWatchCodesOut(BaseModel):
    pool_id: Optional[str] = None
    ts_codes: list[str]


class CoreWatchToggleBody(BaseModel):
    ts_code: str
    starred: bool
    limit_up_date: Optional[str] = Field(None, description="涨停日 YYYYMMDD，与买点雷达一致")


class CoreWatchToggleOut(BaseModel):
    starred: bool
    pool_id: Optional[str] = None
    stock_id: Optional[str] = None
    ts_code: str
