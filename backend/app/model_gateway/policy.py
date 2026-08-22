from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from chatbi_agent_contracts import QuestionRoute

from app.model_gateway.configuration import load_control_config
from app.model_gateway.contracts import BudgetMode, ModelCapability, ModelRequest


@dataclass(frozen=True)
class CostEstimate:
    provider: str
    input_tokens: int
    output_tokens: int
    cost_cny: float
    priced: bool


class CostCalculator:
    def __init__(self) -> None:
        self.config = load_control_config("model_pricing.yaml")

    @property
    def version(self) -> str:
        return f"{self.config['schema_version']}@{self.config['effective_date']}"

    def calculate(
        self, provider: str, *, input_tokens: int, cached_input_tokens: int, output_tokens: int,
    ) -> float:
        pricing = self.config["providers"].get(provider) or {}
        if pricing.get("priced", True) is False:
            return 0.0
        cached = min(max(cached_input_tokens, 0), max(input_tokens, 0))
        uncached = max(input_tokens - cached, 0)
        total = (
            cached * float(pricing.get("cached_input", 0))
            + uncached * float(pricing.get("uncached_input", 0))
            + max(output_tokens, 0) * float(pricing.get("output", 0))
        ) / 1_000_000
        return round(total, 8)

    def estimate(self, provider: str, request: ModelRequest) -> CostEstimate:
        serialized = "".join(str(message.get("content", "")) for message in request.messages)
        input_tokens = max(1, len(serialized) // 3)
        policy = load_control_config("model_policy.yaml")
        mode = policy["budget_modes"][request.budget_mode.value]
        output_tokens = min(request.max_output_tokens or mode["max_output_tokens"], mode["max_output_tokens"])
        priced = (self.config["providers"].get(provider) or {}).get("priced", True)
        return CostEstimate(
            provider=provider,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_cny=self.calculate(
                provider, input_tokens=input_tokens, cached_input_tokens=0, output_tokens=output_tokens,
            ),
            priced=bool(priced),
        )


class ComplexityScorer:
    """Small, explainable heuristic used before any model invocation."""

    _COMPARISON = ("同比", "环比", "趋势", "比较", "对比", "差距", "排名", "异常")
    _MULTI_STEP = ("综合分析", "深度分析", "诊断", "归因", "制定分析步骤", "多维分析")
    _KNOWLEDGE = ("口径", "制度", "规则", "知识", "依据", "文档")

    @classmethod
    def score(
        cls, question: str, *, route: QuestionRoute | None = None, attachment_count: int = 0,
    ) -> int:
        normalized = question.strip()
        score = 5
        if len(normalized) > 40:
            score += 8
        if len(normalized) > 120:
            score += 10
        score += 8 * min(3, sum(marker in normalized for marker in cls._COMPARISON))
        score += 18 * min(2, sum(marker in normalized for marker in cls._MULTI_STEP))
        if any(marker in normalized for marker in cls._KNOWLEDGE):
            score += 10
        if route == QuestionRoute.DATA_QUERY:
            score += 15
        elif route == QuestionRoute.KNOWLEDGE_QUERY:
            score += 12
        elif route == QuestionRoute.HYBRID_ANALYSIS:
            score += 28
        elif route == QuestionRoute.COMPLEX_ANALYSIS:
            score += 40
        if attachment_count:
            score += min(20, 8 + attachment_count * 4)
        if re.search(r"20\d{2}\s*年|本月|今年|去年|季度", normalized):
            score += 5
        return min(100, max(0, score))


class RoutingPolicy:
    def __init__(self) -> None:
        self.capabilities = load_control_config("model_capabilities.yaml")
        self.policy = load_control_config("model_policy.yaml")
        self.cost = CostCalculator()

    def resolve_alias(self, alias: str) -> str | None:
        normalized = alias.strip().lower()
        if normalized in {"", "auto"}:
            return None
        if normalized in self.capabilities["providers"]:
            return normalized
        alias_config = self.capabilities["aliases"].get(normalized)
        return str(alias_config["provider"]) if alias_config else None

    def provider_candidates(self, request: ModelRequest) -> list[str]:
        explicit = self.resolve_alias(request.requested_alias)
        if explicit:
            if (
                request.modality.value == "vision"
                and explicit == "kimi"
                and not request.premium_triggers
            ):
                return []
            return [explicit]
        capability = request.capability.value
        if request.modality.value == "vision":
            capability = "vision"
        candidates = list(self.policy["provider_order"].get(capability, ()))
        premium = self.policy["budget_modes"][request.budget_mode.value]["allow_premium"]
        if request.modality.value == "vision":
            # MiMo is the sole ordinary image route. Kimi may be selected only
            # after an observable Vision Escalation Trigger has been recorded.
            if request.premium_triggers and "kimi" in candidates:
                candidates.remove("kimi")
                candidates.insert(0, "kimi")
            elif "kimi" in candidates:
                candidates.remove("kimi")
        else:
            premium_eligible = request.complexity_score >= 80 or bool(request.premium_triggers)
            if premium and premium_eligible and "kimi" in candidates:
                candidates.remove("kimi")
                candidates.insert(0, "kimi")
            elif not premium and "kimi" in candidates:
                candidates.remove("kimi")
        return candidates

    def supports(self, provider: str, request: ModelRequest) -> bool:
        configured = self.capabilities["providers"].get(provider)
        if configured is None:
            return True
        required = "vision" if request.modality.value == "vision" else request.capability.value
        capabilities = set(configured.get("capabilities") or ())
        return required in capabilities

    def within_budget(self, provider: str, request: ModelRequest) -> bool:
        estimate = self.cost.estimate(provider, request)
        if not estimate.priced:
            return True
        limit = float(self.policy["budget_modes"][request.budget_mode.value]["max_estimated_call_cny"])
        return estimate.cost_cny <= limit

    def max_output_tokens(self, request: ModelRequest) -> int:
        configured = int(self.policy["budget_modes"][request.budget_mode.value]["max_output_tokens"])
        return min(request.max_output_tokens or configured, configured)

    def safe_summary(self) -> dict[str, Any]:
        return {
            "schema_version": self.policy["schema_version"],
            "complexity_bands": self.policy["complexity_bands"],
            "budget_modes": self.policy["budget_modes"],
            "limits": self.policy["limits"],
            "pricing_version": self.cost.version,
        }
