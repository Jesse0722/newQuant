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
    evidence_score: int = Field(default=0, ge=0, le=100)
    mapping_confidence: int = Field(default=0, ge=0, le=100)
    action_suggestion: str = "watch"
    reason: Optional[str] = None
    catalysts: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    source_platforms: list[str] = Field(default_factory=list)
    source_links: list[str] = Field(default_factory=list)
    review_status: str = "reviewed"
    review_reason: Optional[str] = None
    generated_by: str = "manual"
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
    evidence_score: int = 0
    mapping_confidence: int = 0
    action_suggestion: str
    reason: Optional[str] = None
    catalysts: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    source_platforms: list[str] = Field(default_factory=list)
    source_links: list[str] = Field(default_factory=list)
    review_status: str = "reviewed"
    review_reason: Optional[str] = None
    generated_by: str = "manual"
    accepted_at: Optional[datetime] = None
    dismissed_at: Optional[datetime] = None
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}

    @field_validator("catalysts", "risks", "source_platforms", "source_links", mode="before")
    @classmethod
    def _none_to_list(cls, value):
        return value or []


class MessageOpportunityReviewRequest(BaseModel):
    review_status: str = Field(default="reviewed", max_length=16)
    review_reason: Optional[str] = None


class MessageOpportunityDismissRequest(BaseModel):
    review_reason: Optional[str] = None


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


class MessageEvidenceCreate(BaseModel):
    source_item_id: str
    trade_date: str = Field(pattern=r"^\d{8}$")
    channel: str = Field(min_length=1, max_length=32)
    theme: Optional[str] = Field(default=None, max_length=64)
    ts_code: Optional[str] = Field(default=None, max_length=16)
    evidence_text: str = Field(min_length=1)
    stance: str = "neutral"
    quality_score: int = Field(default=60, ge=0, le=100)
    credibility_score: int = Field(default=50, ge=0, le=100)
    confidence: int = Field(default=60, ge=0, le=100)
    extraction_method: str = "rule"
    extractor_name: str = "rule_evidence_cleaner"
    extractor_version: str = "1.0"
    raw_json: dict | None = None
    status: str = "active"


class MessageEvidenceOut(BaseModel):
    id: str
    source_item_id: str
    trade_date: str
    channel: str
    theme: Optional[str] = None
    ts_code: Optional[str] = None
    evidence_text: str
    stance: str
    quality_score: int
    credibility_score: int
    confidence: int
    extraction_method: str
    extractor_name: str
    extractor_version: str
    raw_json: dict = Field(default_factory=dict)
    status: str
    created_at: datetime
    source_item: Optional[MessageSourceItemOut] = None

    model_config = {"from_attributes": True}

    @field_validator("raw_json", mode="before")
    @classmethod
    def _none_to_dict(cls, value):
        return value or {}


class MessageOpportunityEvidenceOut(BaseModel):
    id: str
    opportunity_id: str
    evidence_id: str
    role: str
    weight: int
    created_at: datetime
    evidence: MessageEvidenceOut | None = None

    model_config = {"from_attributes": True}


class MessageAgentRunCreate(BaseModel):
    agent_name: str = Field(min_length=1, max_length=64)
    agent_version: str = Field(default="1.0", max_length=16)
    trade_date: Optional[str] = Field(default=None, pattern=r"^\d{8}$")
    input_ref_type: Optional[str] = Field(default=None, max_length=32)
    input_ref_id: Optional[str] = Field(default=None, max_length=64)
    input_digest: Optional[str] = Field(default=None, max_length=64)
    output_json: dict | None = None
    model_provider: str = Field(default="rules", max_length=32)
    model_name: str = Field(default="deterministic-rule", max_length=80)
    prompt_version: Optional[str] = Field(default=None, max_length=16)
    status: str = Field(default="success", max_length=16)
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    duration_ms: Optional[int] = None


class MessageAgentRunOut(BaseModel):
    id: str
    agent_name: str
    agent_version: str
    trade_date: Optional[str] = None
    input_ref_type: Optional[str] = None
    input_ref_id: Optional[str] = None
    input_digest: Optional[str] = None
    output_json: dict = Field(default_factory=dict)
    model_provider: str
    model_name: str
    prompt_version: Optional[str] = None
    status: str
    error_message: Optional[str] = None
    started_at: datetime
    finished_at: Optional[datetime] = None
    duration_ms: Optional[int] = None

    model_config = {"from_attributes": True}

    @field_validator("output_json", mode="before")
    @classmethod
    def _none_output_to_dict(cls, value):
        return value or {}


class MessageAgentRunRequest(BaseModel):
    agent_name: str = Field(min_length=1, max_length=64)
    trade_date: Optional[str] = Field(default=None, pattern=r"^\d{8}$")
    source_item_ids: list[str] = Field(default_factory=list)
    limit: int = Field(default=20, ge=1, le=100)
    provider: Optional[str] = Field(default=None, max_length=32)
    model: Optional[str] = Field(default=None, max_length=80)
    dry_run: bool = False


class MessageAgentRunResult(BaseModel):
    agent_name: str
    trade_date: Optional[str] = None
    dry_run: bool
    source_item_count: int
    created_count: int
    updated_count: int
    skipped_count: int
    evidence_count: int
    fallback_count: int = 0
    error_count: int = 0
    run: MessageAgentRunOut | None = None


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
    id: Optional[str] = None
    keyword: str
    type: str
    theme: str
    priority: int
    language: str
    status: str = "active"

    model_config = {"from_attributes": True}


class MessageSeedKeywordCreate(BaseModel):
    keyword: str = Field(min_length=1, max_length=80)
    type: str = Field(default="industry", max_length=24)
    theme: str = Field(min_length=1, max_length=64)
    priority: int = Field(default=3, ge=1, le=5)
    language: str = Field(default="zh", max_length=8)
    status: str = Field(default="active", max_length=16)


class MessageKeywordImportRequest(BaseModel):
    items: list[MessageSeedKeywordCreate] = Field(min_length=1, max_length=500)


class MessageKeywordImportOut(BaseModel):
    created_count: int
    updated_count: int
    skipped_count: int
    items: list[MessageSeedKeywordOut]


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


class MessageConclusionTopic(BaseModel):
    theme: str
    heat_score: int
    credibility_score: int
    crowding_score: int
    lifecycle_stage: str
    source_platforms: list[str] = Field(default_factory=list)
    conclusion: str


class MessageConclusionOpportunity(BaseModel):
    theme: str
    ts_code: Optional[str] = None
    stock_name: Optional[str] = None
    opportunity_score: int
    risk_score: int
    action_suggestion: str
    conclusion: str
    source_links: list[str] = Field(default_factory=list)


class MessageDailyConclusionOut(BaseModel):
    trade_date: str
    generated_at: datetime
    headline: str
    conclusion: str
    next_action: str
    top_topics: list[MessageConclusionTopic]
    top_opportunities: list[MessageConclusionOpportunity]


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


class MessageAgentDailyGenerateRequest(BaseModel):
    trade_date: Optional[str] = Field(default=None, pattern=r"^\d{8}$")
    use_llm: bool = False
    provider: Optional[str] = Field(default=None, max_length=32)
    model: Optional[str] = Field(default=None, max_length=80)
    limit: int = Field(default=5, ge=1, le=10)


class MessageAgentDailyCandidate(BaseModel):
    theme: str
    ts_code: Optional[str] = None
    stock_name: Optional[str] = None
    opportunity_score: int
    evidence_score: int
    risk_score: int
    review_status: str
    evidence_count: int
    conclusion: str


class MessageAgentDailyOut(BaseModel):
    trade_date: str
    generated_at: datetime
    model_provider: str
    model_name: str
    headline: str
    summary: str
    evidence_coverage: dict
    risk_flags: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    candidates: list[MessageAgentDailyCandidate] = Field(default_factory=list)
