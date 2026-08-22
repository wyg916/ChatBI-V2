from __future__ import annotations

import json
import time
from collections.abc import Iterator
from dataclasses import dataclass
from threading import Event, Lock
from time import perf_counter
from typing import Any, Callable
from uuid import uuid4

import httpx

from app.core.config import Settings, get_settings
from app.model_gateway.configuration import ResolvedProvider, configured_providers, load_control_config
from app.model_gateway.contracts import (
    BudgetMode,
    ModelCapability,
    ModelModality,
    ModelRequest,
    ModelResponse,
    ModelUsage,
    RequestContext,
)
from app.model_gateway.policy import RoutingPolicy
from app.model_gateway.ledger import record_model_invocation


class ModelUnavailable(RuntimeError):
    pass


class VisionModelUnavailable(ModelUnavailable):
    pass


class ModelBudgetExceeded(ModelUnavailable):
    pass


@dataclass(frozen=True)
class ModelReply:
    content: str
    provider: str
    model: str
    requested_alias: str = "auto"
    trace: dict[str, Any] | None = None


@dataclass
class _CircuitState:
    consecutive_failures: int = 0
    open_until: float = 0.0


class _CircuitRegistry:
    def __init__(self, *, threshold: int, cooldown_seconds: float, clock: Callable[[], float]) -> None:
        self.threshold = threshold
        self.cooldown_seconds = cooldown_seconds
        self.clock = clock
        self._states: dict[str, _CircuitState] = {}
        self._lock = Lock()

    def available(self, provider: str) -> bool:
        with self._lock:
            state = self._states.setdefault(provider, _CircuitState())
            if state.open_until and self.clock() >= state.open_until:
                state.open_until = 0.0
                state.consecutive_failures = 0
            return state.open_until == 0.0

    def success(self, provider: str) -> None:
        with self._lock:
            self._states[provider] = _CircuitState()

    def failure(self, provider: str) -> None:
        with self._lock:
            state = self._states.setdefault(provider, _CircuitState())
            state.consecutive_failures += 1
            if state.consecutive_failures >= self.threshold:
                state.open_until = self.clock() + self.cooldown_seconds

    def snapshot(self, provider: str) -> dict[str, Any]:
        with self._lock:
            state = self._states.setdefault(provider, _CircuitState())
            return {
                "state": "OPEN" if state.open_until > self.clock() else "CLOSED",
                "consecutive_failures": state.consecutive_failures,
            }


def _usage(payload: dict[str, Any] | None) -> ModelUsage:
    if not payload:
        return ModelUsage()
    prompt = max(0, int(payload.get("prompt_tokens") or payload.get("input_tokens") or 0))
    details = payload.get("prompt_tokens_details") or payload.get("input_tokens_details") or {}
    cached = max(0, int(details.get("cached_tokens") or payload.get("cached_tokens") or 0))
    output = max(0, int(payload.get("completion_tokens") or payload.get("output_tokens") or 0))
    total = max(prompt + output, int(payload.get("total_tokens") or 0))
    return ModelUsage(
        input_tokens=prompt, cached_input_tokens=min(cached, prompt), output_tokens=output,
        total_tokens=total, exact=True,
    )


class ModelGateway:
    """The sole provider-network boundary for ChatBI model execution."""

    def __init__(
        self,
        settings: Settings | None = None,
        transport: httpx.BaseTransport | None = None,
        *,
        provider_overrides: dict[str, ResolvedProvider] | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.settings = settings or get_settings()
        self.transport = transport
        self.providers = provider_overrides or configured_providers(self.settings)
        self.policy = RoutingPolicy()
        self.health_config = load_control_config("provider_health.yaml")
        self.sleeper = sleeper
        self.clock = clock
        self.last_response: ModelResponse | None = None
        self._circuits = _CircuitRegistry(
            threshold=int(self.health_config["circuit_failure_threshold"]),
            cooldown_seconds=float(self.health_config["circuit_cooldown_seconds"]),
            clock=clock,
        )

    @staticmethod
    def _default_context(question: str = "") -> RequestContext:
        request_id = f"REQ-{uuid4()}"
        return RequestContext(request_id=request_id, trace_id=f"TRACE-{uuid4()}", question=question)

    def _candidates(self, request: ModelRequest) -> list[ResolvedProvider]:
        configured = self.providers
        candidates: list[ResolvedProvider] = []
        over_budget = False
        for provider_id in self.policy.provider_candidates(request):
            provider = configured.get(provider_id)
            if provider is None or not self.policy.supports(provider_id, request):
                continue
            if not self.policy.within_budget(provider_id, request):
                over_budget = True
                continue
            if self._circuits.available(provider_id):
                candidates.append(provider)
        limit = int(self.policy.policy["limits"]["max_model_escalations"]) + 1
        candidates = candidates[:limit]
        if not candidates and over_budget:
            raise ModelBudgetExceeded("No configured model provider fits the request budget")
        if not candidates:
            error = VisionModelUnavailable if request.modality == ModelModality.VISION else ModelUnavailable
            raise error("No configured model provider is available")
        return candidates

    def _payload(self, provider: ResolvedProvider, request: ModelRequest, *, stream: bool) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": provider.model_name,
            "stream": stream,
            "messages": list(request.messages),
            provider.max_tokens_field: self.policy.max_output_tokens(request),
            **provider.request_options,
        }
        if request.json_mode:
            payload["response_format"] = {"type": "json_object"}
        if request.tools:
            payload["tools"] = list(request.tools)
            payload["tool_choice"] = request.tool_choice or "auto"
        if provider.provider_id in {"mimo", "deepseek", "kimi"}:
            payload["thinking"] = {"type": "enabled" if request.thinking else "disabled"}
            if request.thinking:
                payload["reasoning_effort"] = request.reasoning_effort
        return payload

    @staticmethod
    def _headers(provider: ResolvedProvider) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            provider.auth_header: f"{provider.auth_prefix}{provider.api_key}",
        }

    def _retryable(self, exc: httpx.HTTPError) -> bool:
        if isinstance(exc, httpx.TransportError):
            return True
        if isinstance(exc, httpx.HTTPStatusError):
            statuses = set(int(value) for value in self.health_config["retryable_statuses"])
            return exc.response.status_code in statuses or exc.response.status_code >= 500
        return False

    def _retry_delay(self, exc: httpx.HTTPError, attempt: int) -> float:
        response = getattr(exc, "response", None)
        retry_after = response.headers.get("Retry-After") if response is not None else None
        maximum = float(self.health_config["retry_after_max_seconds"])
        try:
            return min(maximum, max(0.0, float(retry_after))) if retry_after is not None else min(maximum, 0.25 * (attempt + 1))
        except ValueError:
            return min(maximum, 0.25 * (attempt + 1))

    @staticmethod
    def _cancelled(cancellation_event: Event | None) -> None:
        if cancellation_event is not None and cancellation_event.is_set():
            raise ModelUnavailable("Model request cancelled")

    def execute(
        self,
        request: ModelRequest,
        context: RequestContext | None = None,
        *,
        cancellation_event: Event | None = None,
    ) -> ModelResponse:
        context = context or self._default_context()
        self.last_response = None
        self._cancelled(cancellation_event)
        failures: list[str] = []
        started = perf_counter()
        retries_total = 0
        try:
            candidates = self._candidates(request)
        except ModelUnavailable as exc:
            record_model_invocation(
                context, request, response=None, provider="none", status="FAILED",
                latency_ms=round((perf_counter() - started) * 1000), error_code=type(exc).__name__,
            )
            raise
        attempts = max(1, int(self.health_config["retry_attempts"]))
        for fallback_count, provider in enumerate(candidates):
            provider_attempts = 1 if provider.provider_id == "kimi" else attempts
            for attempt in range(provider_attempts):
                self._cancelled(cancellation_event)
                attempt_started = perf_counter()
                try:
                    timeout = request.timeout_seconds or float(self.health_config["request_timeout_seconds"])
                    with httpx.Client(timeout=timeout, transport=self.transport) as client:
                        response = client.post(
                            f"{provider.base_url}/chat/completions",
                            headers=self._headers(provider),
                            json=self._payload(provider, request, stream=False),
                        )
                        response.raise_for_status()
                    body = response.json()
                    choice = body["choices"][0]
                    message = choice["message"]
                    content = message.get("content") or ""
                    tool_calls = tuple(message.get("tool_calls") or ())
                    if not str(content).strip() and not tool_calls:
                        raise ValueError("model returned empty content")
                    usage = _usage(body.get("usage"))
                    result = ModelResponse(
                        content=str(content).strip(),
                        requested_alias=request.requested_alias,
                        resolved_provider=provider.provider_id,
                        resolved_model=str(body.get("model") or provider.model_name),
                        usage=usage,
                        cost_cny=self.policy.cost.calculate(
                            provider.provider_id,
                            input_tokens=usage.input_tokens,
                            cached_input_tokens=usage.cached_input_tokens,
                            output_tokens=usage.output_tokens,
                        ),
                        latency_ms=round((perf_counter() - started) * 1000),
                        fallback_used=fallback_count > 0,
                        fallback_count=fallback_count,
                        retry_count=retries_total,
                        finish_reason=choice.get("finish_reason"),
                        tool_calls=tool_calls,
                        reasoning_observed=bool(message.get("reasoning_content")),
                        pricing_version=self.policy.cost.version,
                    )
                    self._circuits.success(provider.provider_id)
                    self.last_response = result
                    record_model_invocation(
                        context, request, response=result, provider=result.resolved_provider,
                        model=result.resolved_model, status="SUCCEEDED",
                        latency_ms=round((perf_counter() - attempt_started) * 1000),
                        circuit_state=self._circuits.snapshot(provider.provider_id)["state"],
                    )
                    return result
                except httpx.HTTPError as exc:
                    status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else "transport"
                    failures.append(f"{provider.provider_id}:{type(exc).__name__}:{status}:attempt{attempt + 1}")
                    self._circuits.failure(provider.provider_id)
                    record_model_invocation(
                        context, request, response=None, provider=provider.provider_id,
                        model=provider.model_name, status="FAILED",
                        latency_ms=round((perf_counter() - attempt_started) * 1000),
                        fallback_count=fallback_count, retry_count=attempt,
                        error_code=f"HTTP_{status}" if isinstance(status, int) else type(exc).__name__,
                        circuit_state=self._circuits.snapshot(provider.provider_id)["state"],
                    )
                    if attempt + 1 < provider_attempts and self._retryable(exc):
                        retries_total += 1
                        self.sleeper(self._retry_delay(exc, attempt))
                        continue
                    break
                except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                    failures.append(f"{provider.provider_id}:{type(exc).__name__}:attempt{attempt + 1}")
                    self._circuits.failure(provider.provider_id)
                    record_model_invocation(
                        context, request, response=None, provider=provider.provider_id,
                        model=provider.model_name, status="FAILED",
                        latency_ms=round((perf_counter() - attempt_started) * 1000),
                        fallback_count=fallback_count, retry_count=attempt,
                        error_code=type(exc).__name__,
                        circuit_state=self._circuits.snapshot(provider.provider_id)["state"],
                    )
                    break
                except ModelUnavailable as exc:
                    if cancellation_event is None or not cancellation_event.is_set():
                        raise
                    record_model_invocation(
                        context, request, response=None, provider=provider.provider_id,
                        model=provider.model_name, status="CANCELLED",
                        latency_ms=round((perf_counter() - attempt_started) * 1000),
                        fallback_count=fallback_count, retry_count=attempt,
                        error_code="REQUEST_CANCELLED",
                        circuit_state=self._circuits.snapshot(provider.provider_id)["state"],
                    )
                    raise
        error = VisionModelUnavailable if request.modality == ModelModality.VISION else ModelUnavailable
        raise error("All configured model providers failed: " + ", ".join(failures))

    def complete(
        self,
        *,
        system: str,
        user: str,
        history: list[dict[str, str]] | None = None,
        image_data_urls: list[str] | None = None,
        json_mode: bool = False,
        vision: bool = False,
        context: RequestContext | None = None,
        capability: ModelCapability = ModelCapability.GENERAL,
        complexity_score: int = 25,
        budget_mode: BudgetMode | None = None,
        requested_alias: str | None = None,
        premium_triggers: frozenset[str] | None = None,
        cancellation_event: Event | None = None,
    ) -> ModelReply:
        messages: list[dict[str, Any]] = [{"role": "system", "content": system}, *(history or [])]
        if image_data_urls:
            content: list[dict[str, Any]] = [{"type": "text", "text": user}]
            content.extend({"type": "image_url", "image_url": {"url": value}} for value in image_data_urls)
            messages.append({"role": "user", "content": content})
        else:
            messages.append({"role": "user", "content": user})
        configured_request = self.settings.vision_model_provider if vision else self.settings.general_model_provider
        alias = requested_alias or (configured_request if configured_request.strip().lower() != "auto" else "auto")
        mode = budget_mode or BudgetMode(self.settings.model_budget_mode)
        governed_triggers = set(premium_triggers or ())
        if len(image_data_urls or ()) > 1:
            governed_triggers.add("multi_image")
        request = ModelRequest(
            capability=ModelCapability.VISION if vision else capability,
            modality=ModelModality.VISION if vision else ModelModality.TEXT,
            messages=tuple(messages), requested_alias=alias, json_mode=json_mode,
            complexity_score=complexity_score, budget_mode=mode,
            thinking=complexity_score >= 55,
            reasoning_effort="high" if complexity_score >= 80 else "medium",
            image_count=len(image_data_urls or ()),
            premium_triggers=frozenset(governed_triggers),
        )
        result = self.execute(request, context or self._default_context(user), cancellation_event=cancellation_event)
        return ModelReply(
            content=result.content, provider=result.resolved_provider, model=result.resolved_model,
            requested_alias=result.requested_alias, trace=result.trace_payload(),
        )

    def stream(
        self,
        *,
        system: str,
        user: str,
        history: list[dict[str, str]] | None = None,
        image_data_urls: list[str] | None = None,
        vision: bool = False,
        context: RequestContext | None = None,
        capability: ModelCapability = ModelCapability.GENERAL,
        complexity_score: int = 25,
        budget_mode: BudgetMode | None = None,
        requested_alias: str | None = None,
        premium_triggers: frozenset[str] | None = None,
        cancellation_event: Event | None = None,
    ) -> Iterator[ModelReply]:
        context = context or self._default_context(user)
        self.last_response = None
        messages: list[dict[str, Any]] = [{"role": "system", "content": system}, *(history or [])]
        if image_data_urls:
            content: list[dict[str, Any]] = [{"type": "text", "text": user}]
            content.extend({"type": "image_url", "image_url": {"url": value}} for value in image_data_urls)
            messages.append({"role": "user", "content": content})
        else:
            messages.append({"role": "user", "content": user})
        configured_request = self.settings.vision_model_provider if vision else self.settings.general_model_provider
        alias = requested_alias or (configured_request if configured_request.strip().lower() != "auto" else "auto")
        governed_triggers = set(premium_triggers or ())
        if len(image_data_urls or ()) > 1:
            governed_triggers.add("multi_image")
        request = ModelRequest(
            capability=ModelCapability.VISION if vision else capability,
            modality=ModelModality.VISION if vision else ModelModality.TEXT,
            messages=tuple(messages), requested_alias=alias,
            complexity_score=complexity_score,
            budget_mode=budget_mode or BudgetMode(self.settings.model_budget_mode),
            thinking=complexity_score >= 55,
            reasoning_effort="high" if complexity_score >= 80 else "medium",
            image_count=len(image_data_urls or ()),
            premium_triggers=frozenset(governed_triggers),
        )
        failures: list[str] = []
        started = perf_counter()
        retries_total = 0
        attempts = max(1, int(self.health_config["retry_attempts"]))
        try:
            candidates = self._candidates(request)
        except ModelUnavailable as exc:
            record_model_invocation(
                context, request, response=None, provider="none", status="FAILED",
                latency_ms=round((perf_counter() - started) * 1000), error_code=type(exc).__name__,
            )
            raise
        for fallback_count, provider in enumerate(candidates):
            provider_attempts = 1 if provider.provider_id == "kimi" else attempts
            for attempt in range(provider_attempts):
                self._cancelled(cancellation_event)
                attempt_started = perf_counter()
                emitted = False
                chunks: list[str] = []
                usage = ModelUsage()
                finish_reason = None
                ttfe_ms = None
                reasoning_observed = False
                resolved_model = provider.model_name
                try:
                    timeout = request.timeout_seconds or float(self.health_config["request_timeout_seconds"])
                    with httpx.Client(timeout=timeout, transport=self.transport) as client:
                        with client.stream(
                            "POST", f"{provider.base_url}/chat/completions",
                            headers=self._headers(provider), json=self._payload(provider, request, stream=True),
                        ) as response:
                            response.raise_for_status()
                            for line in response.iter_lines():
                                self._cancelled(cancellation_event)
                                if not line or line.startswith(":") or not line.startswith("data:"):
                                    continue
                                data = line[5:].strip()
                                if data == "[DONE]":
                                    break
                                decoded = json.loads(data)
                                resolved_model = str(decoded.get("model") or resolved_model)
                                if decoded.get("usage"):
                                    usage = _usage(decoded["usage"])
                                choice = (decoded.get("choices") or [{}])[0]
                                finish_reason = choice.get("finish_reason") or finish_reason
                                delta = choice.get("delta") or {}
                                reasoning_observed = reasoning_observed or bool(delta.get("reasoning_content"))
                                text_delta = delta.get("content")
                                if isinstance(text_delta, str) and text_delta:
                                    if ttfe_ms is None:
                                        ttfe_ms = round((perf_counter() - started) * 1000)
                                    emitted = True
                                    chunks.append(text_delta)
                                    yield ModelReply(content=text_delta, provider=provider.provider_id, model=provider.model_name, requested_alias=alias)
                    if not emitted:
                        raise ValueError("model returned empty stream")
                    result = ModelResponse(
                        content="".join(chunks), requested_alias=alias,
                        resolved_provider=provider.provider_id, resolved_model=resolved_model,
                        usage=usage,
                        cost_cny=self.policy.cost.calculate(
                            provider.provider_id, input_tokens=usage.input_tokens,
                            cached_input_tokens=usage.cached_input_tokens, output_tokens=usage.output_tokens,
                        ),
                        latency_ms=round((perf_counter() - started) * 1000),
                        time_to_first_token_ms=ttfe_ms,
                        fallback_used=fallback_count > 0, fallback_count=fallback_count,
                        retry_count=retries_total, finish_reason=finish_reason,
                        reasoning_observed=reasoning_observed, pricing_version=self.policy.cost.version,
                    )
                    self._circuits.success(provider.provider_id)
                    self.last_response = result
                    record_model_invocation(
                        context, request, response=result, provider=result.resolved_provider,
                        model=result.resolved_model, status="SUCCEEDED",
                        latency_ms=round((perf_counter() - attempt_started) * 1000),
                        circuit_state=self._circuits.snapshot(provider.provider_id)["state"],
                    )
                    return
                except httpx.HTTPError as exc:
                    if emitted:
                        record_model_invocation(
                            context, request, response=None, provider=provider.provider_id,
                            model=provider.model_name, status="FAILED",
                            latency_ms=round((perf_counter() - started) * 1000),
                            fallback_count=fallback_count, retry_count=retries_total,
                            error_code="STREAM_HTTP_ERROR",
                            circuit_state=self._circuits.snapshot(provider.provider_id)["state"],
                        )
                        raise ModelUnavailable("Provider stream failed after content was emitted") from exc
                    status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else "transport"
                    failures.append(f"{provider.provider_id}:{type(exc).__name__}:{status}:attempt{attempt + 1}")
                    self._circuits.failure(provider.provider_id)
                    record_model_invocation(
                        context, request, response=None, provider=provider.provider_id,
                        model=provider.model_name, status="FAILED",
                        latency_ms=round((perf_counter() - attempt_started) * 1000),
                        fallback_count=fallback_count, retry_count=attempt,
                        error_code=f"HTTP_{status}" if isinstance(status, int) else type(exc).__name__,
                        circuit_state=self._circuits.snapshot(provider.provider_id)["state"],
                    )
                    if attempt + 1 < provider_attempts and self._retryable(exc):
                        retries_total += 1
                        self.sleeper(self._retry_delay(exc, attempt))
                        continue
                    break
                except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                    if emitted:
                        record_model_invocation(
                            context, request, response=None, provider=provider.provider_id,
                            model=provider.model_name, status="FAILED",
                            latency_ms=round((perf_counter() - started) * 1000),
                            fallback_count=fallback_count, retry_count=retries_total,
                            error_code="STREAM_INVALID_RESPONSE",
                            circuit_state=self._circuits.snapshot(provider.provider_id)["state"],
                        )
                        raise ModelUnavailable("Provider stream became invalid after content was emitted") from exc
                    failures.append(f"{provider.provider_id}:{type(exc).__name__}:attempt{attempt + 1}")
                    self._circuits.failure(provider.provider_id)
                    record_model_invocation(
                        context, request, response=None, provider=provider.provider_id,
                        model=provider.model_name, status="FAILED",
                        latency_ms=round((perf_counter() - attempt_started) * 1000),
                        fallback_count=fallback_count, retry_count=attempt,
                        error_code=type(exc).__name__,
                        circuit_state=self._circuits.snapshot(provider.provider_id)["state"],
                    )
                    break
                except ModelUnavailable as exc:
                    if cancellation_event is None or not cancellation_event.is_set():
                        raise
                    record_model_invocation(
                        context, request, response=None, provider=provider.provider_id,
                        model=provider.model_name, status="CANCELLED",
                        latency_ms=round((perf_counter() - attempt_started) * 1000),
                        fallback_count=fallback_count, retry_count=attempt,
                        error_code="REQUEST_CANCELLED",
                        circuit_state=self._circuits.snapshot(provider.provider_id)["state"],
                    )
                    raise
        error = VisionModelUnavailable if vision else ModelUnavailable
        raise error("All configured model provider streams failed: " + ", ".join(failures))

    def classify(
        self, question: str, *, history_summary: str = "", context: RequestContext | None = None,
        complexity_score: int = 25,
    ) -> str:
        reply = self.complete(
            system=(
                "Classify the request for an enterprise ChatBI router. Return JSON only with key route. "
                "Allowed: DATA_QUERY, KNOWLEDGE_QUERY, HYBRID_ANALYSIS, COMPLEX_ANALYSIS, GENERAL_CHAT, "
                "CLARIFICATION, UNSUPPORTED. DATA_QUERY requires database facts; KNOWLEDGE_QUERY requires "
                "governed knowledge; HYBRID combines both; COMPLEX needs bounded multi-step analysis."
            ),
            user=json.dumps({"question": question, "conversation_summary": history_summary}, ensure_ascii=False),
            json_mode=True, context=context, capability=ModelCapability.CLASSIFICATION,
            complexity_score=complexity_score,
        )
        try:
            return str(json.loads(reply.content)["route"])
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise ModelUnavailable("Model router returned invalid JSON") from exc

    def probe(self, provider: str) -> dict[str, Any]:
        reply = self.complete(
            system="Return OK only.", user="health probe", requested_alias=provider,
            complexity_score=0, budget_mode=BudgetMode.ECONOMY,
        )
        return {"provider": reply.provider, "model": reply.model, "status": "PASS"}

    def health_snapshot(self) -> dict[str, Any]:
        return {
            provider_id: {
                "configured": True,
                **self._circuits.snapshot(provider_id),
            }
            for provider_id in self.providers
        }
