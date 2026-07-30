"""Shared Pydantic contracts for every block boundary in the pipeline.

Every block (core stage, sector adapter, audience adapter, reporting renderer)
communicates only through these models or the sector-local contracts that wrap
them. Do not branch on sector name or audience name anywhere that consumes
these models — always resolve behavior through a registered profile instead.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, Field


class Attachment(BaseModel):
    attachment_id: str
    filename: str
    content_type: Optional[str] = None
    size_bytes: Optional[int] = None


class UserRequest(BaseModel):
    request_id: str
    question: str
    requested_by: Optional[str] = None
    target_audience: Optional[str] = None
    requested_sector_id: Optional[str] = None
    attachments: list[Attachment] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class EntityExtractionResult(BaseModel):
    request_id: str
    primary_intent: str
    organizations: list[str] = Field(default_factory=list)
    technologies: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)


class SectorProfile(BaseModel):
    sector_id: str
    display_name: str
    status: Literal["active", "template_only", "unsupported"]
    aliases: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    pipeline_entrypoint: Optional[str] = None
    system_prompt_path: Optional[str] = None


class SectorRoute(BaseModel):
    request_id: str
    sector_id: Optional[str] = None
    status: Literal["routed", "unsupported"]
    matched_profile: Optional[SectorProfile] = None
    reason: Optional[str] = None


class PlannedSource(BaseModel):
    name: str
    url: Optional[str] = None
    country: Optional[str] = None
    type: Optional[str] = None
    collection_method: list[str] = Field(default_factory=list)
    frequency: Optional[str] = None
    category: list[str] = Field(default_factory=list)
    reliability_reason: Optional[str] = None
    # Optional, free-text but meant to follow a shared 3-tier convention
    # (confirmed with an SK브로드밴드 domain expert, not invented by us):
    #   "official"       — government/company's own first-party statements
    #   "analyst_media"   — industry press or aggregator/database (interprets
    #                       or curates, doesn't just publish raw fact)
    #   "user_generated"  — audience reviews/reactions; not fact-checked and
    #                       not meant to be — it's a signal of sentiment, not
    #                       a claim to verify. Left unset until a sector
    #                       defines its own tiering (no sector-name branching
    #                       on this — each sector's own registry decides).
    reliability_tier: Optional[str] = None


class SourcePlan(BaseModel):
    request_id: str
    sector_id: str
    planned_sources: list[PlannedSource] = Field(default_factory=list)
    question_keywords: list[str] = Field(default_factory=list)
    notes: Optional[str] = None


class SourceDocument(BaseModel):
    doc_id: str
    source_id: str
    title: str
    url: Optional[str] = None
    published_at: Optional[datetime] = None
    content: Optional[str] = None
    reliability_tier: Optional[str] = None


class DocumentAnalysis(BaseModel):
    doc_id: str
    summary: Optional[str] = None
    key_points: list[str] = Field(default_factory=list)
    sentiment: Optional[str] = None


class TrendSynthesis(BaseModel):
    request_id: str
    sector_id: str
    highlights: list[str] = Field(default_factory=list)
    synthesis_text: Optional[str] = None
    source_count: int = 0


class ReportPlan(BaseModel):
    request_id: str
    audience_id: str
    primary_intent: str
    sections: list[str] = Field(default_factory=list)
    format: Literal["dashboard", "html", "pdf"] = "html"
    intent_emphasis: Optional[str] = None


class AudienceAdaptation(BaseModel):
    request_id: str
    audience_id: str
    tone: Optional[str] = None
    adapted_sections: dict = Field(default_factory=dict)


class DynamicLayout(BaseModel):
    request_id: str
    format: str
    blocks: list[dict] = Field(default_factory=list)
    render_target: Optional[str] = None
