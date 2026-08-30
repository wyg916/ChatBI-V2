from __future__ import annotations

import json
import queue
import time
from collections.abc import Iterator
from dataclasses import dataclass
from threading import Event, Lock, Thread
from time import perf_counter
from typing import Any, Callable
from uuid import uuid4

import httpx

from app.core.config import Settings, get_settings
from app.model_gateway.control import remaining_seconds, resolve_model_request_control
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
from app.model_gateway.normalization import normalize_chat_completion, normalize_usage
from app.model_gateway.test_cost_control import PaidTestAttempt, TestCostControlError, TestCostController


class ModelUnavailable(RuntimeError):
    pass


class VisionModelUnavailable(ModelUnavailable):
    pass


class ModelBudgetExceeded(ModelUnavailable):
    pass


_NETWORK_CONTROL_POLL_SECONDS = 0.01
_NETWORK_WORKER_JOIN_SECONDS = 0.1
_NETWORK_RESPONSE_MAX_BYTES = 16 * 1024 * 1024
_NETWORK_STREAM_QUEUE_MAX_EVENTS = 16
_NETWORK_STREAM_MAX_RESPONSE_BYTES = 16 * 1024 * 1024
_NETWORK_STREAM_MAX_LINE_BYTES = 1024 * 1024
_DECODED_RESPONSE_STALE_HEADERS = frozenset({
    "content-encoding",
    "content-length",
    "transfer-encoding",
})


def _network_cancelled(cancellation_event: Any | None) -> bool:
    return cancellation_event is not None and cancellation_event.is_set()


def _network_checkpoint(
    stop_event: Event,
    cancellation_event: Any | None,
    deadline_monotonic: float,
) -> None:
    if stop_event.is_set() or _network_cancelled(cancellation_event):
        raise ModelUnavailable("Model request cancelled")
    if time.monotonic() >= deadline_monotonic:
        raise httpx.ReadTimeout("Model request exceeded its absolute deadline")


def _stop_network_worker(client: httpx.Client, stop_event: Event, worker: Thread) -> None:
    """Stop network-only work without letting an uncooperative transport hang the caller.

    The worker owns no database session, ledger callback, provider-success
    mutation or public response.  If a third-party/custom transport ignores
    ``close()``, it can only finish into its private buffer after this bounded
    join; every success/publication decision remains on the caller thread.
    """

    stop_event.set()
    try:
        client.close()
    except Exception:
        pass
    worker.join(timeout=_NETWORK_WORKER_JOIN_SECONDS)


class _ModelResponseLimitExceeded(ValueError):
    pass


def _reject_compressed_response(response: httpx.Response) -> None:
    """Prevent HTTPX from allocating an unbounded decoded chunk before caps run."""

    encodings = {
        item.strip().lower()
        for item in response.headers.get("Content-Encoding", "").split(",")
        if item.strip()
    }
    if encodings and encodings != {"identity"}:
        raise _ModelResponseLimitExceeded(
            "Compressed model responses are not accepted"
        )


def _put_stream_line(
    events: queue.Queue[str],
    line: str,
    *,
    stop_event: Event,
    cancellation_event: Any | None,
    deadline_monotonic: float,
) -> None:
    """Apply backpressure without hiding cancellation or deadline expiry."""

    while True:
        _network_checkpoint(stop_event, cancellation_event, deadline_monotonic)
        try:
            events.put(line, timeout=_NETWORK_CONTROL_POLL_SECONDS)
            return
        except queue.Full:
            continue


def _controlled_response(
    client: httpx.Client,
    *,
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    cancellation_event: Any | None,
    timeout_seconds: float,
) -> httpx.Response:
    """Read one response under a total wall-clock deadline, not an idle timeout."""

    deadline = time.monotonic() + max(0.001, timeout_seconds)
    stop_event = Event()
    done = Event()
    outcome: dict[str, Any] = {}

    def request_worker() -> None:
        try:
            with client.stream("POST", url, headers=headers, json=payload) as response:
                response.raise_for_status()
                _reject_compressed_response(response)
                body = bytearray()
                for chunk in response.iter_bytes():
                    _network_checkpoint(stop_event, cancellation_event, deadline)
                    if len(body) + len(chunk) > _NETWORK_RESPONSE_MAX_BYTES:
                        raise _ModelResponseLimitExceeded(
                            "Model response exceeded maximum response bytes"
                        )
                    body.extend(chunk)
                _network_checkpoint(stop_event, cancellation_event, deadline)
                decoded_headers = [
                    (name, value)
                    for name, value in response.headers.multi_items()
                    if name.lower() not in _DECODED_RESPONSE_STALE_HEADERS
                ]
                outcome["response"] = httpx.Response(
                    status_code=response.status_code,
                    headers=decoded_headers,
                    content=bytes(body),
                    request=response.request,
                    extensions=response.extensions,
                )
        except BaseException as exc:
            outcome["error"] = exc
        finally:
            done.set()

    worker = Thread(
        target=request_worker,
        name="chatbi-model-http",
        daemon=True,
    )
    worker.start()
    cancelled = False
    timed_out = False
    while not done.wait(_NETWORK_CONTROL_POLL_SECONDS):
        if _network_cancelled(cancellation_event):
            cancelled = True
            break
        if time.monotonic() >= deadline:
            timed_out = True
            break
    if not cancelled and _network_cancelled(cancellation_event):
        cancelled = True
    if not cancelled and time.monotonic() >= deadline:
        timed_out = True
    if cancelled or timed_out:
        _stop_network_worker(client, stop_event, worker)
        if cancelled:
            raise ModelUnavailable("Model request cancelled")
        raise httpx.ReadTimeout("Model request exceeded its absolute deadline")
    worker.join()
    error = outcome.get("error")
    if error is not None:
        raise error
    return outcome["response"]


def _controlled_stream_lines(
    client: httpx.Client,
    *,
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    cancellation_event: Any | None,
    timeout_seconds: float,
) -> Iterator[str]:
    """Yield bounded SSE lines while retaining ownership of the network reader."""

    deadline = time.monotonic() + max(0.001, timeout_seconds)
    stop_event = Event()
    done = Event()
    events: queue.Queue[str] = queue.Queue(maxsize=_NETWORK_STREAM_QUEUE_MAX_EVENTS)
    outcome: dict[str, BaseException] = {}

    def stream_worker() -> None:
        try:
            with client.stream("POST", url, headers=headers, json=payload) as response:
                response.raise_for_status()
                _reject_compressed_response(response)
                pending = bytearray()
                total_bytes = 0
                skip_lf_after_cr = False
                for chunk in response.iter_bytes():
                    _network_checkpoint(stop_event, cancellation_event, deadline)
                    total_bytes += len(chunk)
                    if total_bytes > _NETWORK_STREAM_MAX_RESPONSE_BYTES:
                        raise _ModelResponseLimitExceeded(
                            "Model stream exceeded maximum response bytes"
                        )

                    for value in chunk:
                        if skip_lf_after_cr:
                            skip_lf_after_cr = False
                            if value == 0x0A:
                                continue
                        if value != 0x0A and value != 0x0D:
                            if len(pending) >= _NETWORK_STREAM_MAX_LINE_BYTES:
                                raise _ModelResponseLimitExceeded(
                                    "Model stream exceeded maximum line bytes"
                                )
                            pending.append(value)
                            continue
                        _put_stream_line(
                            events,
                            bytes(pending).decode("utf-8"),
                            stop_event=stop_event,
                            cancellation_event=cancellation_event,
                            deadline_monotonic=deadline,
                        )
                        pending.clear()
                        skip_lf_after_cr = value == 0x0D
                if pending:
                    _put_stream_line(
                        events,
                        bytes(pending).decode("utf-8"),
                        stop_event=stop_event,
                        cancellation_event=cancellation_event,
                        deadline_monotonic=deadline,
                    )
                _network_checkpoint(stop_event, cancellation_event, deadline)
        except BaseException as exc:
            # The worker owns no ledger/publication state.  Once the caller has
            # stopped it, do not publish even a private late error outcome.
            if not stop_event.is_set():
                outcome["error"] = exc
        finally:
            done.set()

    worker = Thread(
        target=stream_worker,
        name="chatbi-model-stream-http",
        daemon=True,
    )
    worker.start()
    try:
        while True:
            if _network_cancelled(cancellation_event):
                raise ModelUnavailable("Model request cancelled")
            if time.monotonic() >= deadline:
                raise httpx.ReadTimeout("Model stream exceeded its absolute deadline")
            error = outcome.get("error") if done.is_set() else None
            if error is not None:
                raise error
            try:
                line = events.get(timeout=_NETWORK_CONTROL_POLL_SECONDS)
            except queue.Empty:
                if done.is_set():
                    error = outcome.get("error")
                    if error is not None:
                        raise error
                    _network_checkpoint(stop_event, cancellation_event, deadline)
                    return
                continue
            _network_checkpoint(stop_event, cancellation_event, deadline)
            error = outcome.get("error") if done.is_set() else None
            if error is not None:
                raise error
            yield line
    finally:
        _stop_network_worker(client, stop_event, worker)


@dataclass(frozen=True)
class ModelReply:
    content: str
    provider: str
    model: str
    requested_alias: str = "auto"
    trace: dict[str, Any] | None = None


@dataclass(frozen=True)
class _ProviderAttemptPlan:
    fallback_count: int
    provider: ResolvedProvider
    retry_count: int
    max_attempts: int


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
        respect_runtime_enabled: bool = True,
    ) -> None:
        self.settings = settings or get_settings()
        self.transport = transport
        self.providers = provider_overrides or configured_providers(self.settings)
        self.policy = RoutingPolicy(unrestricted=self.settings.provider_usage_unrestricted)
        self.test_cost_control = TestCostController()
        self.health_config = load_control_config("provider_health.yaml")
        self.sleeper = sleeper
        self.clock = clock
        self.respect_runtime_enabled = respect_runtime_enabled
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

    def _candidates(self, request: ModelRequest, context: RequestContext) -> list[ResolvedProvider]:
        configured = self.providers
        disabled: set[str] = set()
        if self.respect_runtime_enabled and context.workspace_id != "SYSTEM":
            from sqlalchemy import select
            from app.model_gateway.ledger import bound_model_invocation_session
            from app.models import ProviderRuntimeSetting

            db = bound_model_invocation_session()
            if db is not None:
                disabled = set(db.scalars(select(ProviderRuntimeSetting.provider_id).where(
                    ProviderRuntimeSetting.workspace_id == context.workspace_id,
                    ProviderRuntimeSetting.enabled.is_(False),
                )))
        candidates: list[ResolvedProvider] = []
        over_budget = False
        for provider_id in self.policy.provider_candidates(request):
            provider = configured.get(provider_id)
            if provider is None or provider_id in disabled or not self.policy.supports(provider_id, request):
                continue
            if not self.policy.within_budget(provider_id, request):
                over_budget = True
                continue
            if self._circuits.available(provider_id):
                candidates.append(provider)
        limit = int(self.policy.policy["limits"]["max_model_escalations"]) + 1
        if self.policy.unrestricted:
            # Keep every explicitly waived MiMo/DeepSeek/Kimi candidate.  A
            # generic or future provider retains the ordinary candidate cap
            # and cannot inherit this operator waiver by accident.
            unrestricted = [
                item for item in candidates
                if self.policy.is_unrestricted_provider(item.provider_id)
            ]
            governed = [
                item for item in candidates
                if not self.policy.is_unrestricted_provider(item.provider_id)
            ]
            governed_slots = max(0, limit - len(unrestricted))
            selected_ids = {
                id(item) for item in (*unrestricted, *governed[:governed_slots])
            }
            candidates = [item for item in candidates if id(item) in selected_ids]
        else:
            candidates = candidates[:limit]
        if not candidates and over_budget:
            raise ModelBudgetExceeded("No configured model provider fits the request budget")
        if not candidates:
            error = VisionModelUnavailable if request.modality == ModelModality.VISION else ModelUnavailable
            raise error("No configured model provider is available")
        return candidates

    def _premium_escalation(self, request: ModelRequest, provider: ResolvedProvider) -> bool:
        """Describe the gateway's resolved premium decision without changing routing."""

        explicit_provider = self.policy.resolve_alias(request.requested_alias)
        return provider.provider_id == "kimi" and explicit_provider != "kimi"

    def _payload(
        self,
        provider: ResolvedProvider,
        request: ModelRequest,
        *,
        stream: bool,
        context: RequestContext | None = None,
    ) -> dict[str, Any]:
        max_output_tokens = self.policy.max_output_tokens(
            request, provider=provider.provider_id,
        )
        if self.transport is None:
            max_output_tokens = self.test_cost_control.limit_output_tokens(
                max_output_tokens,
                context=context,
            )
        payload: dict[str, Any] = {
            "model": provider.model_name,
            "stream": stream,
            "messages": list(request.messages),
            provider.max_tokens_field: max_output_tokens,
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
            "Accept-Encoding": "identity",
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

    def _request_timeout(
        self,
        request: ModelRequest,
        cancellation_event: Event | None,
    ) -> float:
        configured = request.timeout_seconds or float(
            self.health_config["request_timeout_seconds"]
        )
        remaining = remaining_seconds(cancellation_event)
        if remaining is None:
            return configured
        self._cancelled(cancellation_event)
        return max(0.001, min(configured, remaining))

    def _provider_attempt_schedule(
        self,
        candidates: list[ResolvedProvider],
        attempts: int,
    ) -> list[_ProviderAttemptPlan]:
        provider_plans = [
            (
                fallback_count,
                provider,
                attempts
                if self.policy.is_unrestricted_provider(provider.provider_id)
                else (1 if provider.provider_id == "kimi" else attempts),
            )
            for fallback_count, provider in enumerate(candidates)
        ]
        if self.policy.unrestricted:
            return [
                _ProviderAttemptPlan(fallback_count, provider, retry_count, max_attempts)
                for retry_count in range(max(max_attempts for _, _, max_attempts in provider_plans))
                for fallback_count, provider, max_attempts in provider_plans
                if retry_count < max_attempts
            ]
        return [
            _ProviderAttemptPlan(fallback_count, provider, retry_count, max_attempts)
            for fallback_count, provider, max_attempts in provider_plans
            for retry_count in range(max_attempts)
        ]

    def _controlled_sleep(self, delay: float, cancellation_event: Event | None) -> None:
        delay = max(0.0, delay)
        if cancellation_event is None:
            self.sleeper(delay)
            return
        ready_at = self.clock() + delay
        waiter = getattr(cancellation_event, "wait", None)
        while True:
            self._cancelled(cancellation_event)
            delay_remaining = max(0.0, ready_at - self.clock())
            if delay_remaining == 0:
                return
            request_remaining = remaining_seconds(cancellation_event)
            if request_remaining is not None:
                if request_remaining == 0:
                    raise ModelUnavailable("Model request cancelled")
                delay_remaining = min(delay_remaining, request_remaining)
            sleep_slice = min(_NETWORK_CONTROL_POLL_SECONDS, delay_remaining)
            if callable(waiter):
                if waiter(sleep_slice):
                    raise ModelUnavailable("Model request cancelled")
            else:
                self.sleeper(sleep_slice)

    def execute(
        self,
        request: ModelRequest,
        context: RequestContext | None = None,
        *,
        cancellation_event: Event | None = None,
    ) -> ModelResponse:
        context = context or self._default_context()
        cancellation_event = resolve_model_request_control(cancellation_event)
        self.last_response = None
        self._cancelled(cancellation_event)
        failures: list[str] = []
        started = perf_counter()
        retries_total = 0
        try:
            candidates = self._candidates(request, context)
        except ModelUnavailable as exc:
            record_model_invocation(
                context, request, response=None, provider="none", status="FAILED",
                latency_ms=round((perf_counter() - started) * 1000), error_code=type(exc).__name__,
            )
            raise
        attempts = self.test_cost_control.limit_attempts(
            max(1, int(self.health_config["retry_attempts"]))
        )
        retry_ready_at: dict[tuple[int, int], float] = {}
        for plan in self._provider_attempt_schedule(candidates, attempts):
            fallback_count = plan.fallback_count
            provider = plan.provider
            provider_attempts = plan.max_attempts
            for attempt in (plan.retry_count,):
                if attempt > 0:
                    retry_key = (fallback_count, attempt)
                    if retry_key not in retry_ready_at:
                        continue
                    retry_delay = max(
                        0.0,
                        retry_ready_at.pop(retry_key) - self.clock(),
                    )
                    if retry_delay:
                        self._controlled_sleep(retry_delay, cancellation_event)
                    retries_total += 1
                self._cancelled(cancellation_event)
                attempt_started = perf_counter()
                paid_attempt: PaidTestAttempt | None = None
                attempt_response: ModelResponse | None = None
                try:
                    paid_attempt = self.test_cost_control.reserve_attempt(
                        provider=provider.provider_id,
                        model=provider.model_name,
                        request=request,
                        context=context,
                        estimated_cost_cny=self.policy.cost.estimate(provider.provider_id, request).cost_cny,
                        retry_count=attempt,
                        recorded_transport=self.transport is not None,
                        fallback_count=fallback_count,
                        premium_escalation=self._premium_escalation(request, provider),
                    )
                    timeout = self._request_timeout(request, cancellation_event)
                    with httpx.Client(timeout=timeout, transport=self.transport) as client:
                        response = _controlled_response(
                            client,
                            url=f"{provider.base_url}/chat/completions",
                            headers=self._headers(provider),
                            payload=self._payload(
                                provider,
                                request,
                                stream=False,
                                context=context,
                            ),
                            cancellation_event=cancellation_event,
                            timeout_seconds=timeout,
                        )
                    self._cancelled(cancellation_event)
                    body = response.json()
                    self._cancelled(cancellation_event)
                    normalized = normalize_chat_completion(body)
                    usage = normalized.usage
                    result = ModelResponse(
                        content=normalized.content,
                        requested_alias=request.requested_alias,
                        resolved_provider=provider.provider_id,
                        resolved_model=normalized.resolved_model or provider.model_name,
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
                        finish_reason=normalized.finish_reason,
                        tool_calls=normalized.tool_calls,
                        reasoning_observed=normalized.reasoning_observed,
                        pricing_version=self.policy.cost.version,
                    )
                    attempt_response = result
                    # This is the success publication boundary. Cancellation
                    # or the absolute deadline must win before any ledger,
                    # circuit, or public response state is committed.
                    self._cancelled(cancellation_event)
                    self.test_cost_control.complete_attempt(
                        paid_attempt,
                        status="SUCCEEDED",
                        response=result,
                        latency_ms=round((perf_counter() - attempt_started) * 1000),
                    )
                    record_model_invocation(
                        context, request, response=result, provider=result.resolved_provider,
                        model=result.resolved_model, status="SUCCEEDED",
                        latency_ms=round((perf_counter() - attempt_started) * 1000),
                        retry_count=attempt,
                        circuit_state=self._circuits.snapshot(provider.provider_id)["state"],
                    )
                    self._circuits.success(provider.provider_id)
                    self.last_response = result
                    return result
                except TestCostControlError as exc:
                    record_model_invocation(
                        context,
                        request,
                        response=None,
                        provider=provider.provider_id,
                        model=provider.model_name,
                        status="BLOCKED",
                        latency_ms=round((perf_counter() - attempt_started) * 1000),
                        fallback_count=fallback_count,
                        retry_count=attempt,
                        error_code=str(exc),
                        circuit_state=self._circuits.snapshot(provider.provider_id)["state"],
                    )
                    raise
                except httpx.HTTPError as exc:
                    status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else "transport"
                    error_code = f"HTTP_{status}" if isinstance(status, int) else type(exc).__name__
                    self.test_cost_control.complete_attempt(
                        paid_attempt,
                        status="FAILED",
                        error_code=error_code,
                        latency_ms=round((perf_counter() - attempt_started) * 1000),
                    )
                    failures.append(f"{provider.provider_id}:{type(exc).__name__}:{status}:attempt{attempt + 1}")
                    self._circuits.failure(provider.provider_id)
                    record_model_invocation(
                        context, request, response=None, provider=provider.provider_id,
                        model=provider.model_name, status="FAILED",
                        latency_ms=round((perf_counter() - attempt_started) * 1000),
                        fallback_count=fallback_count, retry_count=attempt,
                        error_code=error_code,
                        circuit_state=self._circuits.snapshot(provider.provider_id)["state"],
                    )
                    if attempt + 1 < provider_attempts and self._retryable(exc):
                        retry_ready_at[(fallback_count, attempt + 1)] = (
                            self.clock() + self._retry_delay(exc, attempt)
                        )
                        continue
                    break
                except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                    self.test_cost_control.complete_attempt(
                        paid_attempt,
                        status="FAILED",
                        error_code=type(exc).__name__,
                        latency_ms=round((perf_counter() - attempt_started) * 1000),
                    )
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
                    self.test_cost_control.complete_attempt(
                        paid_attempt,
                        status="CANCELLED",
                        response=attempt_response,
                        error_code="REQUEST_CANCELLED",
                        latency_ms=round((perf_counter() - attempt_started) * 1000),
                    )
                    record_model_invocation(
                        context, request, response=attempt_response, provider=provider.provider_id,
                        model=(attempt_response.resolved_model if attempt_response else provider.model_name),
                        status="CANCELLED",
                        latency_ms=round((perf_counter() - attempt_started) * 1000),
                        fallback_count=fallback_count, retry_count=attempt,
                        error_code="REQUEST_CANCELLED",
                        circuit_state=self._circuits.snapshot(provider.provider_id)["state"],
                    )
                    raise
        self._cancelled(cancellation_event)
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
        max_output_tokens: int | None = None,
        thinking: bool | None = None,
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
            thinking=complexity_score >= 55 if thinking is None else thinking,
            reasoning_effort="high" if complexity_score >= 80 else "medium",
            image_count=len(image_data_urls or ()),
            premium_triggers=frozenset(governed_triggers),
            max_output_tokens=max_output_tokens,
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
        json_mode: bool = False,
    ) -> Iterator[ModelReply]:
        context = context or self._default_context(user)
        cancellation_event = resolve_model_request_control(cancellation_event)
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
            messages=tuple(messages), requested_alias=alias, json_mode=json_mode,
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
        attempts = self.test_cost_control.limit_attempts(
            max(1, int(self.health_config["retry_attempts"]))
        )
        try:
            candidates = self._candidates(request, context)
        except ModelUnavailable as exc:
            record_model_invocation(
                context, request, response=None, provider="none", status="FAILED",
                latency_ms=round((perf_counter() - started) * 1000), error_code=type(exc).__name__,
            )
            raise
        retry_ready_at: dict[tuple[int, int], float] = {}
        for plan in self._provider_attempt_schedule(candidates, attempts):
            fallback_count = plan.fallback_count
            provider = plan.provider
            provider_attempts = plan.max_attempts
            for attempt in (plan.retry_count,):
                if attempt > 0:
                    retry_key = (fallback_count, attempt)
                    if retry_key not in retry_ready_at:
                        continue
                    retry_delay = max(
                        0.0,
                        retry_ready_at.pop(retry_key) - self.clock(),
                    )
                    if retry_delay:
                        self._controlled_sleep(retry_delay, cancellation_event)
                    retries_total += 1
                self._cancelled(cancellation_event)
                attempt_started = perf_counter()
                paid_attempt: PaidTestAttempt | None = None
                emitted = False
                chunks: list[str] = []
                usage = ModelUsage()
                finish_reason = None
                ttfe_ms = None
                reasoning_observed = False
                resolved_model = provider.model_name
                try:
                    paid_attempt = self.test_cost_control.reserve_attempt(
                        provider=provider.provider_id,
                        model=provider.model_name,
                        request=request,
                        context=context,
                        estimated_cost_cny=self.policy.cost.estimate(provider.provider_id, request).cost_cny,
                        retry_count=attempt,
                        recorded_transport=self.transport is not None,
                        fallback_count=fallback_count,
                        premium_escalation=self._premium_escalation(request, provider),
                    )
                    timeout = self._request_timeout(request, cancellation_event)
                    with httpx.Client(timeout=timeout, transport=self.transport) as client:
                        for line in _controlled_stream_lines(
                            client,
                            url=f"{provider.base_url}/chat/completions",
                            headers=self._headers(provider),
                            payload=self._payload(
                                provider,
                                request,
                                stream=True,
                                context=context,
                            ),
                            cancellation_event=cancellation_event,
                            timeout_seconds=timeout,
                        ):
                            self._cancelled(cancellation_event)
                            if not line or line.startswith(":") or not line.startswith("data:"):
                                continue
                            data = line[5:].strip()
                            if data == "[DONE]":
                                break
                            decoded = json.loads(data)
                            self._cancelled(cancellation_event)
                            resolved_model = str(decoded.get("model") or resolved_model)
                            if decoded.get("usage"):
                                usage = normalize_usage(decoded["usage"])
                            choice = (decoded.get("choices") or [{}])[0]
                            finish_reason = choice.get("finish_reason") or finish_reason
                            delta = choice.get("delta") or {}
                            reasoning_observed = reasoning_observed or bool(delta.get("reasoning_content"))
                            text_delta = delta.get("content")
                            if isinstance(text_delta, str) and text_delta:
                                self._cancelled(cancellation_event)
                                if ttfe_ms is None:
                                    ttfe_ms = round((perf_counter() - started) * 1000)
                                emitted = True
                                chunks.append(text_delta)
                                yield ModelReply(content=text_delta, provider=provider.provider_id, model=provider.model_name, requested_alias=alias)
                    self._cancelled(cancellation_event)
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
                    # Deltas have their own pre-yield checkpoint above. This
                    # final checkpoint governs terminal success publication.
                    self._cancelled(cancellation_event)
                    self.test_cost_control.complete_attempt(
                        paid_attempt,
                        status="SUCCEEDED",
                        response=result,
                        latency_ms=round((perf_counter() - attempt_started) * 1000),
                    )
                    record_model_invocation(
                        context, request, response=result, provider=result.resolved_provider,
                        model=result.resolved_model, status="SUCCEEDED",
                        latency_ms=round((perf_counter() - attempt_started) * 1000),
                        retry_count=attempt,
                        circuit_state=self._circuits.snapshot(provider.provider_id)["state"],
                    )
                    self._circuits.success(provider.provider_id)
                    self.last_response = result
                    return
                except GeneratorExit:
                    # A consumer may close after receiving one delta. Reap the
                    # network iterator and terminalize the paid reservation;
                    # never leave an attempt RESERVED or publish SUCCEEDED.
                    self.last_response = None
                    cancelled_response = (
                        ModelResponse(
                            content="",
                            requested_alias=alias,
                            resolved_provider=provider.provider_id,
                            resolved_model=resolved_model,
                            usage=usage,
                            cost_cny=self.policy.cost.calculate(
                                provider.provider_id,
                                input_tokens=usage.input_tokens,
                                cached_input_tokens=usage.cached_input_tokens,
                                output_tokens=usage.output_tokens,
                            ),
                            latency_ms=round((perf_counter() - started) * 1000),
                            time_to_first_token_ms=ttfe_ms,
                            fallback_used=fallback_count > 0,
                            fallback_count=fallback_count,
                            retry_count=retries_total,
                            finish_reason=finish_reason,
                            reasoning_observed=reasoning_observed,
                            pricing_version=self.policy.cost.version,
                        )
                        if usage.exact
                        else None
                    )
                    self.test_cost_control.complete_attempt(
                        paid_attempt,
                        status="CANCELLED",
                        response=cancelled_response,
                        error_code="STREAM_CONSUMER_CLOSED",
                        latency_ms=round((perf_counter() - attempt_started) * 1000),
                    )
                    record_model_invocation(
                        context,
                        request,
                        response=cancelled_response,
                        provider=provider.provider_id,
                        model=(cancelled_response.resolved_model if cancelled_response else provider.model_name),
                        status="CANCELLED",
                        latency_ms=round((perf_counter() - attempt_started) * 1000),
                        fallback_count=fallback_count,
                        retry_count=attempt,
                        error_code="STREAM_CONSUMER_CLOSED",
                        circuit_state=self._circuits.snapshot(provider.provider_id)["state"],
                    )
                    raise
                except TestCostControlError as exc:
                    record_model_invocation(
                        context,
                        request,
                        response=None,
                        provider=provider.provider_id,
                        model=provider.model_name,
                        status="BLOCKED",
                        latency_ms=round((perf_counter() - attempt_started) * 1000),
                        fallback_count=fallback_count,
                        retry_count=attempt,
                        error_code=str(exc),
                        circuit_state=self._circuits.snapshot(provider.provider_id)["state"],
                    )
                    raise
                except httpx.HTTPError as exc:
                    if emitted:
                        self.test_cost_control.complete_attempt(
                            paid_attempt,
                            status="FAILED",
                            error_code="STREAM_HTTP_ERROR",
                            latency_ms=round((perf_counter() - attempt_started) * 1000),
                        )
                        record_model_invocation(
                            context, request, response=None, provider=provider.provider_id,
                            model=provider.model_name, status="FAILED",
                            latency_ms=round((perf_counter() - started) * 1000),
                            fallback_count=fallback_count, retry_count=attempt,
                            error_code="STREAM_HTTP_ERROR",
                            circuit_state=self._circuits.snapshot(provider.provider_id)["state"],
                        )
                        raise ModelUnavailable("Provider stream failed after content was emitted") from exc
                    status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else "transport"
                    error_code = f"HTTP_{status}" if isinstance(status, int) else type(exc).__name__
                    self.test_cost_control.complete_attempt(
                        paid_attempt,
                        status="FAILED",
                        error_code=error_code,
                        latency_ms=round((perf_counter() - attempt_started) * 1000),
                    )
                    failures.append(f"{provider.provider_id}:{type(exc).__name__}:{status}:attempt{attempt + 1}")
                    self._circuits.failure(provider.provider_id)
                    record_model_invocation(
                        context, request, response=None, provider=provider.provider_id,
                        model=provider.model_name, status="FAILED",
                        latency_ms=round((perf_counter() - attempt_started) * 1000),
                        fallback_count=fallback_count, retry_count=attempt,
                        error_code=error_code,
                        circuit_state=self._circuits.snapshot(provider.provider_id)["state"],
                    )
                    if attempt + 1 < provider_attempts and self._retryable(exc):
                        retry_ready_at[(fallback_count, attempt + 1)] = (
                            self.clock() + self._retry_delay(exc, attempt)
                        )
                        continue
                    break
                except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                    if emitted:
                        self.test_cost_control.complete_attempt(
                            paid_attempt,
                            status="FAILED",
                            error_code="STREAM_INVALID_RESPONSE",
                            latency_ms=round((perf_counter() - attempt_started) * 1000),
                        )
                        record_model_invocation(
                            context, request, response=None, provider=provider.provider_id,
                            model=provider.model_name, status="FAILED",
                            latency_ms=round((perf_counter() - started) * 1000),
                            fallback_count=fallback_count, retry_count=attempt,
                            error_code="STREAM_INVALID_RESPONSE",
                            circuit_state=self._circuits.snapshot(provider.provider_id)["state"],
                        )
                        raise ModelUnavailable("Provider stream became invalid after content was emitted") from exc
                    self.test_cost_control.complete_attempt(
                        paid_attempt,
                        status="FAILED",
                        error_code=type(exc).__name__,
                        latency_ms=round((perf_counter() - attempt_started) * 1000),
                    )
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
                    cancelled_response = (
                        ModelResponse(
                            content="",
                            requested_alias=alias,
                            resolved_provider=provider.provider_id,
                            resolved_model=resolved_model,
                            usage=usage,
                            cost_cny=self.policy.cost.calculate(
                                provider.provider_id,
                                input_tokens=usage.input_tokens,
                                cached_input_tokens=usage.cached_input_tokens,
                                output_tokens=usage.output_tokens,
                            ),
                            latency_ms=round((perf_counter() - started) * 1000),
                            time_to_first_token_ms=ttfe_ms,
                            fallback_used=fallback_count > 0,
                            fallback_count=fallback_count,
                            retry_count=retries_total,
                            finish_reason=finish_reason,
                            reasoning_observed=reasoning_observed,
                            pricing_version=self.policy.cost.version,
                        )
                        if usage.exact
                        else None
                    )
                    self.test_cost_control.complete_attempt(
                        paid_attempt,
                        status="CANCELLED",
                        response=cancelled_response,
                        error_code="REQUEST_CANCELLED",
                        latency_ms=round((perf_counter() - attempt_started) * 1000),
                    )
                    record_model_invocation(
                        context, request, response=cancelled_response, provider=provider.provider_id,
                        model=(cancelled_response.resolved_model if cancelled_response else provider.model_name),
                        status="CANCELLED",
                        latency_ms=round((perf_counter() - attempt_started) * 1000),
                        fallback_count=fallback_count, retry_count=attempt,
                        error_code="REQUEST_CANCELLED",
                        circuit_state=self._circuits.snapshot(provider.provider_id)["state"],
                    )
                    raise
        self._cancelled(cancellation_event)
        error = VisionModelUnavailable if vision else ModelUnavailable
        raise error("All configured model provider streams failed: " + ", ".join(failures))

    def classify(
        self, question: str, *, history_summary: str = "", context: RequestContext | None = None,
        complexity_score: int = 25,
    ) -> str:
        reply = self.complete(
            system=(
                "Classify the request for an enterprise ChatBI router. Return JSON only with key route. "
                "Allowed: DATA_QUERY, DATA_FOLLOW_UP, KNOWLEDGE_QUERY, HYBRID_ANALYSIS, COMPLEX_ANALYSIS, "
                "GENERAL_CHAT, SYSTEM_CAPABILITY, MODEL_STATUS, ADMIN_QUERY, CLARIFICATION, UNSUPPORTED. "
                "DATA_QUERY requires database facts; DATA_FOLLOW_UP explicitly depends on a prior data result; "
                "MODEL_STATUS asks about configured or healthy models; SYSTEM_CAPABILITY asks about product/version; "
                "ADMIN_QUERY asks about the current user, permissions, workspace, or settings; KNOWLEDGE_QUERY requires "
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

    def probe(self, provider: str, *, context: RequestContext | None = None) -> dict[str, Any]:
        reply = self.complete(
            system="Return OK only.", user="health probe", requested_alias=provider,
            complexity_score=0, budget_mode=BudgetMode.ECONOMY,
            context=context, max_output_tokens=8,
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
