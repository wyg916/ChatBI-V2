from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Any, Literal

from chatbi_agent_contracts import QuestionRoute
from pydantic import BaseModel, ConfigDict, Field


class BudgetMode(StrEnum):
    ECONOMY = "economy"
    BALANCED = "balanced"
    QUALITY = "quality"


class ModelCapability(StrEnum):
    GENERAL = "general"
    CLASSIFICATION = "classification"
    NL2SQL = "nl2sql"
    VISION = "vision"
    STRUCTURED = "structured"
    TOOL_CALL = "tool_call"


class ModelModality(StrEnum):
    TEXT = "text"
    VISION = "vision"


class RequestContext(BaseModel):
    """Server-owned request identity shared by routing, model, trace, and cache layers."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: str = Field(min_length=1, max_length=128)
    trace_id: str = Field(min_length=8, max_length=128)
    conversation_id: str | None = Field(default=None, max_length=64)
    route: str | None = Field(default=None, max_length=64)
    user_id: str = Field(default="SYSTEM", min_length=1, max_length=128)
    workspace_id: str = Field(default="SYSTEM", min_length=1, max_length=128)
    project_id: str | None = Field(default=None, max_length=128)
    datasource_id: str | None = Field(default=None, max_length=128)
    roles: frozenset[str] = Field(default_factory=lambda: frozenset({"SYSTEM"}))
    permission_hash: str = Field(default="system", min_length=1, max_length=128)
    timezone: str = Field(default="Asia/Shanghai", min_length=1, max_length=64)
    language: str = Field(default="zh-CN", min_length=2, max_length=16)
    question: str = Field(default="", max_length=4_000)
    attachment_ids: tuple[str, ...] = ()
    context_hash: str = Field(default="none", min_length=1, max_length=128)
    budget_mode: BudgetMode = BudgetMode.BALANCED

    def cache_key(self, namespace: str) -> str:
        payload = {
            "namespace": namespace,
            "workspace_id": self.workspace_id,
            "user_id": self.user_id,
            "conversation_id": self.conversation_id,
            "route": self.route,
            "datasource_id": self.datasource_id,
            "permission_hash": self.permission_hash,
            "context_hash": self.context_hash,
            "budget_mode": self.budget_mode.value,
        }
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class RouterDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    route: QuestionRoute
    confidence: float = Field(ge=0, le=1)
    reason: str
    complexity_score: int = Field(ge=0, le=100)
    model_required: bool = False
    requested_alias: str = "none"
    needs_sql: bool = False
    needs_rag: bool = False
    needs_python: bool = False
    needs_vision: bool = False
    needs_clarification: bool = False
    metrics: tuple[str, ...] = ()
    dimensions: tuple[str, ...] = ()
    time_expressions: tuple[str, ...] = ()


class ModelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    capability: ModelCapability = ModelCapability.GENERAL
    modality: ModelModality = ModelModality.TEXT
    messages: tuple[dict[str, Any], ...] = Field(min_length=1)
    requested_alias: str = "auto"
    complexity_score: int = Field(default=25, ge=0, le=100)
    budget_mode: BudgetMode = BudgetMode.BALANCED
    thinking: bool = False
    reasoning_effort: Literal["low", "medium", "high"] = "medium"
    json_mode: bool = False
    tools: tuple[dict[str, Any], ...] = ()
    tool_choice: str | dict[str, Any] | None = None
    max_output_tokens: int | None = Field(default=None, ge=1, le=131_072)
    timeout_seconds: float | None = Field(default=None, gt=0, le=600)
    image_count: int = Field(default=0, ge=0, le=16)
    premium_triggers: frozenset[str] = frozenset()


class ModelUsage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    input_tokens: int = Field(default=0, ge=0)
    cached_input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    exact: bool = False


class ModelResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    content: str
    requested_alias: str
    resolved_provider: str
    resolved_model: str
    usage: ModelUsage = ModelUsage()
    cost_cny: float = Field(default=0, ge=0)
    latency_ms: int = Field(default=0, ge=0)
    time_to_first_token_ms: int | None = Field(default=None, ge=0)
    fallback_used: bool = False
    fallback_count: int = Field(default=0, ge=0)
    retry_count: int = Field(default=0, ge=0)
    finish_reason: str | None = None
    tool_calls: tuple[dict[str, Any], ...] = ()
    reasoning_observed: bool = False
    pricing_version: str = "unknown"

    def trace_payload(self) -> dict[str, Any]:
        return {
            "requested_alias": self.requested_alias,
            "resolved_provider": self.resolved_provider,
            "resolved_model": self.resolved_model,
            "usage": self.usage.model_dump(mode="json"),
            "cost_cny": self.cost_cny,
            "latency_ms": self.latency_ms,
            "time_to_first_token_ms": self.time_to_first_token_ms,
            "fallback_used": self.fallback_used,
            "fallback_count": self.fallback_count,
            "retry_count": self.retry_count,
            "finish_reason": self.finish_reason,
            "reasoning_observed": self.reasoning_observed,
            "pricing_version": self.pricing_version,
        }
