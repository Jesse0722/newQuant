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
