from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class GraphEntityOut(BaseModel):
    id: str
    entity_type: str
    name: str
    normalized_name: str
    ts_code: Optional[str] = None
    aliases: list[str] = Field(default_factory=list)
    confidence: int
    status: str

    model_config = {"from_attributes": True}

    @field_validator("aliases", mode="before")
    @classmethod
    def _none_to_list(cls, value):
        return value or []


class GraphRelationOut(BaseModel):
    id: str
    source_entity_id: str
    relation_type: str
    target_entity_id: str
    confidence: int
    strength: int
    polarity: str
    evidence_count: int
    source_type: str
    status: str

    model_config = {"from_attributes": True}


class GraphEvidenceOut(BaseModel):
    id: str
    relation_id: str
    source_item_id: Optional[str] = None
    evidence_text: str
    evidence_url: Optional[str] = None
    source_channel: Optional[str] = None
    extraction_method: str
    confidence: int
    created_at: datetime

    model_config = {"from_attributes": True}


class GraphSeedImportOut(BaseModel):
    entity_created: int
    entity_updated: int
    relation_created: int
    relation_updated: int
    evidence_created: int


class GraphExtractRequest(BaseModel):
    trade_date: Optional[str] = Field(default=None, pattern=r"^\d{8}$")
    limit: int = Field(default=20, ge=1, le=100)
    provider: str = "deepseek"
    model: str = "deepseek-v4-flash"


class GraphExtractOut(BaseModel):
    processed_count: int
    entity_count: int
    relation_count: int
    evidence_count: int
    error_count: int


class GraphPathStep(BaseModel):
    source: str
    relation: str
    target: str
    confidence: int
    strength: int


class GraphPathOut(BaseModel):
    start: str
    end: str
    depth: int
    score: int
    steps: list[GraphPathStep]


class IndustryReportGenerateRequest(BaseModel):
    trade_date: Optional[str] = Field(default=None, pattern=r"^\d{8}$")
    refresh_seeds: bool = True
    use_llm: Optional[bool] = None


class IndustryReportCandidateOut(BaseModel):
    id: str
    report_id: str
    trade_date: str
    ts_code: str
    stock_name: Optional[str] = None
    theme: str
    path_json: list[dict] = Field(default_factory=list)
    evidence_json: list[dict] = Field(default_factory=list)
    path_score: int
    evidence_score: int
    heat_score: int
    crowding_score: int
    risk_score: int
    final_score: float
    grade: str
    reason: Optional[str] = None
    risks: list[str] = Field(default_factory=list)
    created_at: datetime

    model_config = {"from_attributes": True}

    @field_validator("path_json", "evidence_json", "risks", mode="before")
    @classmethod
    def _none_to_list(cls, value):
        return value or []


class IndustryDailyReportOut(BaseModel):
    id: str
    trade_date: str
    title: str
    headline: Optional[str] = None
    summary: Optional[str] = None
    report_json: dict = Field(default_factory=dict)
    model_provider: Optional[str] = None
    model_name: Optional[str] = None
    prompt_version: str
    status: str
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    candidates: list[IndustryReportCandidateOut] = Field(default_factory=list)

    model_config = {"from_attributes": True}

    @field_validator("report_json", mode="before")
    @classmethod
    def _none_to_dict(cls, value):
        return value or {}
