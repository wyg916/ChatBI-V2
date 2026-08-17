from typing import Any

from pydantic import BaseModel, Field


class NarrativeEvidence(BaseModel):
    statement: str
    fields: list[str] = Field(default_factory=list)
    row_indexes: list[int] = Field(default_factory=list)
    evidence_type: str


class Narrative(BaseModel):
    conclusion: str
    key_metrics: list[dict[str, Any]] = Field(default_factory=list)
    trends: list[str] = Field(default_factory=list)
    contributions: list[str] = Field(default_factory=list)
    anomalies: list[str] = Field(default_factory=list)
    insights: list[str] = Field(default_factory=list)
    recommended_questions: list[str] = Field(default_factory=list)
    evidence: list[NarrativeEvidence] = Field(default_factory=list)
    source_query_id: str
    result_signature: str | None = None
    semantic_model_version: int
