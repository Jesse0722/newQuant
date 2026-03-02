from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class PoolCreate(BaseModel):
    name: str
    description: Optional[str] = None
    default_monitor_rule: Optional[dict] = None


class PoolUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    default_monitor_rule: Optional[dict] = None


class PoolOut(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    default_monitor_rule: Optional[dict] = None
    stock_count: int = 0
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}


class WatchStockCreate(BaseModel):
    ts_code: str
    added_price: Optional[float] = None
    note: Optional[str] = None


class WatchStockUpdate(BaseModel):
    note: Optional[str] = None
    monitor_status: Optional[str] = None


class WatchStockOut(BaseModel):
    id: str
    pool_id: str
    ts_code: str
    stock_name: Optional[str] = None
    added_at: datetime
    added_price: Optional[float] = None
    source: str
    monitor_status: str
    note: Optional[str] = None
    created_at: datetime
    model_config = {"from_attributes": True}


class CSVImportResult(BaseModel):
    imported: int = 0
    skipped: int = 0
    errors: list[str] = []
