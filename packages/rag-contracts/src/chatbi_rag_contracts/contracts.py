from __future__ import annotations

from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RagExecutionContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    workspace_id: str = Field(min_length=1, max_length=64)
    user_id: str = Field(min_length=1, max_length=64)
    roles: frozenset[str] = Field(min_length=1)
    allowed_datasources: frozenset[str]
    allowed_semantic_models: frozenset[str]
    allowed_tools: frozenset[str]
    trace_id: str = Field(min_length=8, max_length=96)
    timeout_ms: int = Field(ge=100, le=120_000)
    max_steps: int = Field(ge=1, le=20)
    token_budget: int = Field(ge=1, le=32_768)


class RagRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    query: str = Field(min_length=1, max_length=4_000)
    scenario_id: str = Field(default="chatbi", min_length=1, max_length=64)
    limit: int = Field(default=5, ge=1, le=10)
    context: RagExecutionContext

    @model_validator(mode="after")
    def require_retrieval_tool(self) -> "RagRequest":
        if "RETRIEVE_KNOWLEDGE" not in self.context.allowed_tools:
            raise ValueError("RETRIEVE_KNOWLEDGE is not allowed")
        return self


class Citation(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True)

    citation_id: str
    document_id: str
    document_version_id: str
    chunk_id: str
    title: str
    text: str
    source: str
    locator: str | None = None
    score: float = Field(ge=0, le=1)


class RagResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["SUCCEEDED", "REFUSED", "FAILED"]
    citations: tuple[Citation, ...] = ()
    answer: str | None = None
    retrieval_mode: str | None = None
    refusal_reason: str | None = None
    trace_id: str
    run_id: str | None = None
    adapter: str
    shadow: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class RerankCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    chunk_id: str
    text: str
    score: float = 0
    metadata: dict[str, Any] = Field(default_factory=dict)


class CitationVerification(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    passed: bool
    reason: str | None = None
    verified_ids: tuple[str, ...] = ()


@runtime_checkable
class RagAdapter(Protocol):
    def retrieve(self, request: RagRequest) -> RagResult: ...


@runtime_checkable
class EmbeddingProvider(Protocol):
    def embed(self, texts: tuple[str, ...], *, trace_id: str) -> tuple[tuple[float, ...], ...]: ...


@runtime_checkable
class RerankProvider(Protocol):
    def rerank(
        self,
        query: str,
        candidates: tuple[RerankCandidate, ...],
        *,
        limit: int,
        trace_id: str,
    ) -> tuple[RerankCandidate, ...]: ...


@runtime_checkable
class CitationVerifier(Protocol):
    def verify(self, query: str, citations: tuple[Citation, ...]) -> CitationVerification: ...
