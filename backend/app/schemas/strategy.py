from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field


class ScreenCondition(BaseModel):
    template_id: str
    params: dict = {}


class IndicatorScreenRequest(BaseModel):
    scope: str = Field(..., description="full 全市场，或 pool_id")
    conditions: list[ScreenCondition] = Field(..., max_length=10)
    logic: str = Field("and", description="and | or")


class AiScreenRequest(BaseModel):
    description: str = Field(..., max_length=200)
    scope: Optional[str] = Field(None, description="full 或 pool_id，AI 选股时可选")


class AiAnalyzeRequest(BaseModel):
    ts_code: str = Field(..., description="股票代码，例如 000001.SZ")
    stock_id: str = Field(..., description="观察池股票 ID（watch_stock.id）")


class LimitUpBuyPointRequest(BaseModel):
    trade_date_from: str = Field(..., description="开始日期 YYYYMMDD")
    trade_date_to: str = Field(..., description="结束日期 YYYYMMDD")
    conditions: list[ScreenCondition] = Field(..., max_length=10)
    logic: str = Field("and", description="and | or")


class MainWaveScreenRequest(BaseModel):
    scope: str = Field("full", description="full 全市场，或 pool_id；指定概念板块时仅作为兜底")
    sector_codes: list[str] = Field(default_factory=list, description="东方财富概念板块代码，如 BK1134")
    sector_logic: str = Field("any", description="any | all，多概念板块命中逻辑")
    min_score: int = Field(70, ge=0, le=100)
    statuses: list[str] = Field(
        default_factory=lambda: ["main_wave_confirmed", "breakout_tracking", "watching", "divergence_warning"]
    )
    require_sector_resonance: bool = True
    exclude_effective_break: bool = True
    exclude_st: bool = True
    min_data_days: int = Field(120, ge=60, le=500)
    min_price: Optional[float] = Field(5, ge=0)
    max_price: Optional[float] = Field(None, ge=0)
    min_float_market_cap_yi: Optional[float] = Field(30, ge=0)
    min_avg_amount_20d_yi: Optional[float] = Field(2, ge=0)
    max_return_60d: Optional[float] = Field(150, ge=0)
    max_ma20_distance_pct: Optional[float] = Field(25, ge=0)
    min_sector_return_20d: Optional[float] = Field(5)
    min_relative_strength_20d: Optional[float] = Field(0)


class BacktestRequest(BaseModel):
    trade_date_from: str = Field(..., description="开始日期 YYYYMMDD")
    trade_date_to: str = Field(..., description="结束日期 YYYYMMDD")
    conditions: list[ScreenCondition] = Field(..., max_length=10)
    logic: str = Field("and", description="and | or")


class BacktestSignal(BaseModel):
    ts_code: str
    trigger_date: str
    next_day_pct: float


class BacktestResult(BaseModel):
    signals: list[BacktestSignal] = []
    avg_pct: float = 0.0
    win_rate: float = 0.0
    total_signals: int = 0


class StrategyBacktestRequest(BaseModel):
    strategy_id: str = Field(..., description="策略ID，如 two_phase / ma5_pullback")
    trade_date_from: str = Field(..., description="开始日期 YYYYMMDD")
    trade_date_to: str = Field(..., description="结束日期 YYYYMMDD")
    pool_id: Optional[str] = Field(None, description="股票池ID，不传则默认涨停观察池")


class StrategyBacktestSignal(BaseModel):
    ts_code: str
    name: str
    trigger_date: str
    entry_price: float
    return_1d: Optional[float] = None
    return_3d: Optional[float] = None
    return_5d: Optional[float] = None
    signal_score: int = 0


class StrategyBacktestResult(BaseModel):
    strategy_id: str
    trade_date_from: str
    trade_date_to: str
    total_signals: int = 0
    win_rate_1d: float = 0.0
    win_rate_3d: float = 0.0
    win_rate_5d: float = 0.0
    avg_return_1d: float = 0.0
    avg_return_3d: float = 0.0
    avg_return_5d: float = 0.0
    max_drawdown: float = 0.0
    profit_factor: float = 0.0
    signals: list[StrategyBacktestSignal] = []


class ScreenResultItem(BaseModel):
    ts_code: str
    stock_name: str = ""


class ScreenResult(BaseModel):
    task_id: str
    status: str
    progress: float = 0.0
    message: str = ""
    ts_codes: list[str] = []
    stock_names: dict[str, str] = {}
    items: list[dict] = []
    total: int = 0
