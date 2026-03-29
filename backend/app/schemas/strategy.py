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
    total: int = 0
