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
