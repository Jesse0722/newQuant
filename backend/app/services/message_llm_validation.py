"""Strict shape checks and exact source anchors for untrusted model output."""
from __future__ import annotations

import re
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator

ResearchAction = Literal["观察", "补证", "加入观察池等待买点雷达确认", "风险观察"]
ACTION_ALIASES = {
    "观察": "观察", "关注": "观察", "继续观察": "观察",
    "优先查看 strong/medium 候选": "观察", "优先查看有多条证据的候选": "观察",
    "补证": "补证", "补充证据": "补证", "补充公告或权威媒体证据": "补证",
    "弱证据候选需补充公告或权威媒体证据": "补证",
    "加入观察池等待买点雷达确认": "加入观察池等待买点雷达确认",
    "加入观察池后等待买点雷达确认": "加入观察池等待买点雷达确认",
    "风险观察": "风险观察",
}


class StrictOutput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")


class EvidenceEntity(StrictOutput):
    type: Literal["company", "stock", "theme", "product", "technology", "event"]
    name: str = Field(min_length=1, max_length=128)
    confidence: int = Field(ge=0, le=100)


class EvidenceFragment(StrictOutput):
    text: str = Field(min_length=1, max_length=1000)
    stance: Literal["support", "risk", "contradiction", "neutral"] = "neutral"
    confidence: int = Field(default=50, ge=0, le=100)
    text_kind: Literal["quote", "summary"] = "quote"
    source_quote: str | None = None


class EvidenceOutput(StrictOutput):
    is_relevant: bool = True
    quality_score: int = Field(default=50, ge=0, le=100)
    theme: str | None = Field(default=None, max_length=64)
    ts_code: str | None = Field(default=None, max_length=16)
    entities: list[EvidenceEntity] = Field(default_factory=list, max_length=30)
    evidence: list[EvidenceFragment] = Field(default_factory=list, max_length=10)
    risk_flags: list[str] = Field(default_factory=list, max_length=20)


class DailySummaryOutput(StrictOutput):
    headline: str | None = None
    summary: str | None = None
    risk_flags: list[str] = Field(default_factory=list, max_length=20)
    next_actions: list[ResearchAction] = Field(default_factory=list, max_length=20)

    @field_validator("next_actions", mode="before")
    @classmethod
    def allowed_actions(cls, value):
        if not isinstance(value, list):
            return value
        result = []
        for action in value:
            normalized = ACTION_ALIASES.get(action.strip()) if isinstance(action, str) else None
            if normalized is None:
                raise ValueError("Unsupported research action; only observation, evidence and risk review are allowed")
            if normalized not in result:
                result.append(normalized)
        return result


class ReportPath(StrictOutput):
    theme: str
    path: list[str] = Field(max_length=10)
    evidence_level: Literal["strong", "medium", "weak"]


class ReportCandidate(StrictOutput):
    ts_code: str
    stock_name: str | None = None
    grade: Literal["strong", "medium", "weak", "risk_watch"]
    reason: str | None = None


class IndustryReportOutput(DailySummaryOutput):
    core_catalysts: list[str] = Field(default_factory=list, max_length=20)
    industry_paths: list[ReportPath] = Field(default_factory=list, max_length=20)
    candidate_summary: list[ReportCandidate] = Field(default_factory=list, max_length=30)


def anchored_quote(quote: str, title: str | None, content: str) -> str:
    def normalized(value: str) -> str:
        return re.sub(r"\s+", " ", value).strip()
    if not quote.strip() or not any(normalized(quote) in normalized(part) for part in (title or "", content)):
        raise ValueError("LLM evidence quote is not supported by source title/content")
    return quote.strip()
