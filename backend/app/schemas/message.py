from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class MessageTopicCreate(BaseModel):
    trade_date: Optional[str] = Field(default=None, pattern=r"^\d{8}$")
    theme: str
    summary: Optional[str] = None
    lifecycle_stage: str = "early"
    sentiment: str = "neutral"
    heat_score: int = Field(default=50, ge=0, le=100)
    credibility_score: int = Field(default=50, ge=0, le=100)
    crowding_score: int = Field(default=30, ge=0, le=100)
    source_platforms: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class MessageTopicOut(BaseModel):
    id: str
    trade_date: str
    theme: str
    summary: Optional[str] = None
    lifecycle_stage: str
    sentiment: str
    heat_score: int
    credibility_score: int
    crowding_score: int
    source_platforms: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @field_validator("source_platforms", "tags", mode="before")
    @classmethod
    def _none_to_list(cls, value):
        return value or []


class MessageOpportunityCreate(BaseModel):
    topic_id: Optional[str] = None
    trade_date: Optional[str] = Field(default=None, pattern=r"^\d{8}$")
    theme: str
    ts_code: Optional[str] = None
    stock_name: Optional[str] = None
    opportunity_score: int = Field(default=50, ge=0, le=100)
    heat_score: int = Field(default=50, ge=0, le=100)
    credibility_score: int = Field(default=50, ge=0, le=100)
    risk_score: int = Field(default=40, ge=0, le=100)
    action_suggestion: str = "watch"
    reason: Optional[str] = None
    catalysts: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    source_platforms: list[str] = Field(default_factory=list)
    source_links: list[str] = Field(default_factory=list)
    status: str = "active"


class MessageOpportunityOut(BaseModel):
    id: str
    topic_id: Optional[str] = None
    trade_date: str
    theme: str
    ts_code: Optional[str] = None
    stock_name: Optional[str] = None
    opportunity_score: int
    heat_score: int
    credibility_score: int
    risk_score: int
    action_suggestion: str
    reason: Optional[str] = None
    catalysts: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    source_platforms: list[str] = Field(default_factory=list)
    source_links: list[str] = Field(default_factory=list)
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}

    @field_validator("catalysts", "risks", "source_platforms", "source_links", mode="before")
    @classmethod
    def _none_to_list(cls, value):
        return value or []


class MessageSourceItemCreate(BaseModel):
    trade_date: Optional[str] = Field(default=None, pattern=r"^\d{8}$")
    channel: str = Field(min_length=1, max_length=32)
    source_name: Optional[str] = Field(default=None, max_length=64)
    external_id: Optional[str] = Field(default=None, max_length=128)
    title: Optional[str] = Field(default=None, max_length=200)
    content: str = Field(min_length=1)
    url: Optional[str] = Field(default=None, max_length=500)
    published_at: Optional[datetime] = None
    theme: Optional[str] = Field(default=None, max_length=64)
    ts_code: Optional[str] = Field(default=None, max_length=16)
    stock_name: Optional[str] = Field(default=None, max_length=32)
    tags: list[str] = Field(default_factory=list)
    sentiment: str = "neutral"
    heat_score: int = Field(default=50, ge=0, le=100)
    credibility_score: int = Field(default=50, ge=0, le=100)
    raw_payload: dict | None = None


class MessageSourceItemOut(BaseModel):
    id: str
    trade_date: str
    channel: str
    source_name: Optional[str] = None
    external_id: Optional[str] = None
    title: Optional[str] = None
    content: str
    url: Optional[str] = None
    published_at: Optional[datetime] = None
    captured_at: datetime
    theme: Optional[str] = None
    ts_code: Optional[str] = None
    stock_name: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    sentiment: str
    heat_score: int
    credibility_score: int
    dedupe_key: str
    raw_payload: dict | None = None
    status: str

    model_config = {"from_attributes": True}

    @field_validator("tags", mode="before")
    @classmethod
    def _none_to_list(cls, value):
        return value or []


class MessageSourceImportRequest(BaseModel):
    items: list[MessageSourceItemCreate] = Field(min_length=1, max_length=200)
    aggregate: bool = True


class MessageAggregationResult(BaseModel):
    trade_date: str
    topic_count: int
    opportunity_count: int
    source_item_count: int


class MessageSourceImportOut(BaseModel):
    created_count: int
    skipped_count: int
    items: list[MessageSourceItemOut]
    aggregation: MessageAggregationResult | None = None


class MessageSeedKeywordOut(BaseModel):
    keyword: str
    type: str
    theme: str
    priority: int
    language: str


class MessageXAccountOut(BaseModel):
    handle: str
    platform: str
    category: str
    theme: str
    weight: float
    status: str


class MessageXSeedSummaryOut(BaseModel):
    keyword_count: int
    account_count: int
    top_themes: list[str]
    keywords: list[MessageSeedKeywordOut]
    accounts: list[MessageXAccountOut]


class MessageXCollectRequest(BaseModel):
    trade_date: Optional[str] = Field(default=None, pattern=r"^\d{8}$")
    query: Optional[str] = None
    min_priority: int = Field(default=5, ge=1, le=5)
    keyword_limit: int = Field(default=12, ge=1, le=40)
    max_results: int = Field(default=20, ge=10, le=100)
    aggregate: bool = True


class MessageXCollectOut(BaseModel):
    query: str
    raw_count: int
    imported: MessageSourceImportOut


class MessageDailyStats(BaseModel):
    topic_count: int
    opportunity_count: int
    top_score: Optional[int] = None
    leading_theme: Optional[str] = None


class MessageDailyOut(BaseModel):
    trade_date: str
    generated_at: datetime
    stats: MessageDailyStats
    topics: list[MessageTopicOut]
    opportunities: list[MessageOpportunityOut]
