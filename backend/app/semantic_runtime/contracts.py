from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class CatalogCandidate(BaseModel):
    object_type: str
    name: str
    qualified_name: str | None = None
    score: float = Field(ge=0, le=1)
    bm25_score: float = Field(ge=0, le=1)
    vector_score: float = Field(ge=0, le=1)
    evidence: list[str] = Field(default_factory=list)


class OpenChatBIState(BaseModel):
    adapter: Literal["openchatbi-selected-source", "openchatbi-clean-room"] = "openchatbi-clean-room"
    upstream_source_commit: str | None = None
    upstream_source_sha256: str | None = None
    upstream_call_count: int = Field(default=0, ge=0)
    workflow: Literal["catalog_retrieval", "schema_linking"] = "schema_linking"
    workspace_id: str
    cache_scope: str
    cache_hit: bool = False
    candidates: list[CatalogCandidate]
    candidate_tables: list[CatalogCandidate]
    candidate_columns: list[CatalogCandidate]
    candidate_metrics: list[CatalogCandidate]
    candidate_relationships: list[CatalogCandidate]
    confidence: float = Field(ge=0, le=1)
    clarification_required: bool = False
    clarification_reason: str | None = None
    elapsed_ms: float = Field(ge=0)
    state_history: list[str] = Field(default_factory=list)


class SemanticQuery(BaseModel):
    metrics: list[str]
    dimensions: list[str]
    filters: list[dict[str, Any]]
    time_range: dict[str, Any] | None = None
    relationships: list[dict[str, Any]]
    comparison: str | None = None
    confidence: float = Field(ge=0, le=1)
    evidence: list[str] = Field(default_factory=list)
    clarification_required: bool = False
    clarification_reason: str | None = None


class WrenMDL(BaseModel):
    adapter: Literal["wrenai-selected-source", "wren-clean-room"] = "wren-clean-room"
    upstream_source_commit: str | None = None
    upstream_source_sha256: list[str] = Field(default_factory=list)
    upstream_call_count: int = Field(default=0, ge=0)
    catalog: str = "chatbi"
    schema_name: str
    semantic_model_id: str
    semantic_model_version: int
    models: list[dict[str, Any]]
    metrics: list[dict[str, Any]]
    dimensions: list[dict[str, Any]]
    relationships: list[dict[str, Any]]
    mapping_coverage: float = Field(ge=0, le=1)


class WrenDryPlan(BaseModel):
    adapter: Literal["wrenai-selected-source", "wren-clean-room"] = "wren-clean-room"
    upstream_source_commit: str | None = None
    upstream_call_count: int = Field(default=0, ge=0)
    semantic_sql: str | None = None
    upstream_ast: str | None = None
    status: Literal["READY", "CLARIFICATION_REQUIRED", "ERROR"]
    semantic_model_version: int
    nodes: list[dict[str, Any]]
    selected_models: list[str]
    selected_metrics: list[str]
    selected_dimensions: list[str]
    structured_error: dict[str, Any] | None = None


class SemanticRuntimeTrace(BaseModel):
    mode: Literal["wren", "local"]
    openchatbi_called: bool
    supersonic_called: bool
    wren_called: bool
    call_chain: list[str]
    stage_latency_ms: dict[str, float]
    schema_linking: OpenChatBIState | None = None
    semantic_query: SemanticQuery | None = None
    wren_mdl: WrenMDL | None = None
    wren_dry_plan: WrenDryPlan | None = None
    upstream_runtime_call_count: dict[str, int] = Field(default_factory=dict)


class SemanticRuntimeError(RuntimeError):
    def __init__(self, code: str, stage: str, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.trace: SemanticRuntimeTrace | None = None
        self.payload = {
            "code": code,
            "stage": stage,
            "message": message,
            "retryable": retryable,
        }
