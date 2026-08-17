from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, model_validator


class QuestionRoute(StrEnum):
    DATA_QUERY = "DATA_QUERY"
    KNOWLEDGE_QUERY = "KNOWLEDGE_QUERY"
    HYBRID_ANALYSIS = "HYBRID_ANALYSIS"
    COMPLEX_ANALYSIS = "COMPLEX_ANALYSIS"


class AgentExecutionContext(BaseModel):
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


class ToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tool_name: str = Field(min_length=1, max_length=96)
    arguments: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str = Field(min_length=8, max_length=128)


class ToolResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tool_name: str
    status: Literal["SUCCEEDED", "REFUSED", "FAILED", "TIMEOUT"]
    output: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = None


class OrchestrationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    question: str = Field(min_length=1, max_length=4_000)
    route: QuestionRoute
    context: AgentExecutionContext
    datasource_id: str | None = None
    semantic_model_id: str | None = None
    include_knowledge: bool = True
    idempotency_key: str = Field(min_length=8, max_length=128)

    @model_validator(mode="after")
    def enforce_scope(self) -> "OrchestrationRequest":
        if self.datasource_id and self.datasource_id not in self.context.allowed_datasources:
            raise ValueError("datasource is not allowed")
        if self.semantic_model_id and self.semantic_model_id not in self.context.allowed_semantic_models:
            raise ValueError("semantic model is not allowed")
        return self


class OrchestrationStep(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ordinal: int = Field(ge=1)
    code: str
    tool_name: str | None = None
    status: Literal["SUCCEEDED", "REFUSED", "FAILED", "TIMEOUT"]
    detail: dict[str, Any] = Field(default_factory=dict)


class OrchestrationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["SUCCEEDED", "PARTIAL", "REFUSED", "FAILED", "TIMEOUT"]
    route: QuestionRoute
    trace_id: str
    run_id: str
    steps: tuple[OrchestrationStep, ...]
    data_evidence: dict[str, Any] | None = None
    knowledge_evidence: dict[str, Any] | None = None
    answer: str | None = None
    fallback_used: bool = False
    error_code: str | None = None


@runtime_checkable
class ToolExecutor(Protocol):
    def execute(self, call: ToolCall, context: AgentExecutionContext) -> ToolResult: ...


@runtime_checkable
class AgentOrchestratorAdapter(Protocol):
    def run(self, request: OrchestrationRequest) -> OrchestrationResult: ...
