from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, model_validator


class QuestionRoute(StrEnum):
    DATA_QUERY = "DATA_QUERY"
    KNOWLEDGE_QUERY = "KNOWLEDGE_QUERY"
    HYBRID_ANALYSIS = "HYBRID_ANALYSIS"
    COMPLEX_ANALYSIS = "COMPLEX_ANALYSIS"
    GENERAL_CHAT = "GENERAL_CHAT"
    FILE_QUERY = "FILE_QUERY"
    MULTIMODAL_QUERY = "MULTIMODAL_QUERY"
    CLARIFICATION = "CLARIFICATION"
    UNSUPPORTED = "UNSUPPORTED"


class AgentRole(StrEnum):
    PLANNER = "PlannerAgent"
    DATA_ANALYST = "DataAnalystAgent"
    KNOWLEDGE = "KnowledgeAgent"
    VERIFICATION = "VerificationAgent"
    INSIGHT = "InsightAgent"


class ToolName(StrEnum):
    QUERY_DATA = "QUERY_DATA"
    RETRIEVE_KNOWLEDGE = "RETRIEVE_KNOWLEDGE"
    VERIFY_RESULT = "VERIFY_RESULT"
    VERIFY_CITATION = "VERIFY_CITATION"
    GENERATE_CHART = "GENERATE_CHART"
    GENERATE_INSIGHT = "GENERATE_INSIGHT"


class ProgressStage(StrEnum):
    UNDERSTANDING = "UNDERSTANDING"
    QUERYING_DATA = "QUERYING_DATA"
    RETRIEVING_KNOWLEDGE = "RETRIEVING_KNOWLEDGE"
    VERIFYING = "VERIFYING"
    GENERATING_INSIGHT = "GENERATING_INSIGHT"
    COMPLETED = "COMPLETED"


class AgentExecutionContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    workspace_id: str = Field(min_length=1, max_length=64)
    user_id: str = Field(min_length=1, max_length=64)
    roles: frozenset[str] = Field(min_length=1)
    allowed_datasources: frozenset[str]
    allowed_semantic_models: frozenset[str]
    allowed_tools: frozenset[str]
    trace_id: str = Field(min_length=8, max_length=96)
    timeout_ms: int = Field(ge=100, le=30_000)
    max_steps: int = Field(default=8, ge=1, le=8)
    max_tool_calls: int = Field(default=12, ge=1, le=12)
    max_replan: int = Field(default=2, ge=0, le=2)
    max_agent_depth: int = Field(default=2, ge=1, le=2)
    token_budget: int = Field(ge=1, le=32_768)


class ToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tool_name: str = Field(min_length=1, max_length=96)
    agent_role: AgentRole
    arguments: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str = Field(min_length=8, max_length=128)
    agent_depth: int = Field(default=1, ge=1, le=2)
    replan_count: int = Field(default=0, ge=0, le=2)


class ToolResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tool_name: str
    status: Literal["SUCCEEDED", "REFUSED", "FAILED", "TIMEOUT"]
    output: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = None
    duration_ms: int = Field(default=0, ge=0)


class OrchestrationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    question: str = Field(min_length=1, max_length=4_000)
    route: QuestionRoute
    context: AgentExecutionContext
    datasource_id: str | None = None
    semantic_model_id: str | None = None
    include_knowledge: bool = True
    idempotency_key: str = Field(min_length=8, max_length=128)
    prompt_versions: dict[str, str] = Field(default_factory=dict)

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
    agent_role: AgentRole
    tool_name: str | None = None
    status: Literal["SUCCEEDED", "REFUSED", "FAILED", "TIMEOUT"]
    detail: dict[str, Any] = Field(default_factory=dict)
    duration_ms: int = Field(default=0, ge=0)


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
    verification: dict[str, bool] = Field(default_factory=dict)
    performance: dict[str, int] = Field(default_factory=dict)
    tool_call_count: int = Field(default=0, ge=0, le=12)
    replan_count: int = Field(default=0, ge=0, le=2)
    max_depth_observed: int = Field(default=1, ge=1, le=2)
    trace_complete: bool = False


@runtime_checkable
class ToolExecutor(Protocol):
    def execute(self, call: ToolCall, context: AgentExecutionContext) -> ToolResult: ...


@runtime_checkable
class AgentOrchestratorAdapter(Protocol):
    def run(self, request: OrchestrationRequest) -> OrchestrationResult: ...
