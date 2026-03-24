from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class RunMode(StrEnum):
    PREVIEW = "preview"
    REVIEW = "review"


class RunState(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class RunInput(BaseModel):
    ticker: str = Field(min_length=1, max_length=12)
    mode: RunMode = RunMode.REVIEW
    event_date: date
    peer_set: list[str] = Field(default_factory=list)
    prior_view: str | None = None


class RunConfig(BaseModel):
    max_iterations: int = 5
    target_score: int = 85
    min_improvement: int = 2
    patience: int = 2


class Scorecard(BaseModel):
    factual_grounding: int
    kpi_completeness: int
    guidance_capture: int
    peer_relevance: int
    valuation_coherence: int
    narrative_consistency: int
    writing_quality: int
    total: int
    major_issues: list[str] = Field(default_factory=list)
    missing_data: list[str] = Field(default_factory=list)


class AgentBrief(BaseModel):
    name: str
    role: str
    status: str
    detail: str


class AgentAction(BaseModel):
    agent: str
    tool: str
    status: str
    output: str


class EvidenceItem(BaseModel):
    agent: str
    claim: str
    support: str
    source_label: str
    source_url: str | None = None


class IterationArtifact(BaseModel):
    summary: str
    kpi_table: list[dict[str, str]]
    guidance_notes: str
    peer_table: list[dict[str, str]]
    valuation_summary: str
    risks_and_catalysts: str
    analyst_note: str
    citations: list[str]
    agent_briefs: list[AgentBrief] = Field(default_factory=list)
    agent_actions: list[AgentAction] = Field(default_factory=list)
    evidence_items: list[EvidenceItem] = Field(default_factory=list)


class RevisionPlan(BaseModel):
    focus_areas: list[str]
    actions: list[str]


class IterationResult(BaseModel):
    index: int
    artifact: IterationArtifact
    scorecard: Scorecard
    revision_plan: RevisionPlan
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


@dataclass(slots=True)
class RunSnapshot:
    run_id: str
    state: RunState
    payload: dict[str, Any]
    config: dict[str, Any]
    summary: str | None
    best_iteration: int | None
    best_score: int | None
    stop_reason: str | None
    created_at: str
    updated_at: str
