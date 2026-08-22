from __future__ import annotations

import threading
from uuid import uuid4

from pydantic import Field

from chatbi_agent_contracts import (
    AgentExecutionContext,
    OrchestrationRequest,
    OrchestrationResult,
    ToolCall,
    ToolExecutor,
    ToolResult,
)
from chatbi_dbgpt_runtime import (
    UPSTREAM_PACKAGE_VERSION,
    UPSTREAM_REVISION,
    DbgptAwelRuntime,
    DbgptRuntimeCancelled,
    DbgptRuntimeError,
    DbgptRuntimePolicyError,
    DbgptRuntimeProvenanceError,
    DbgptRuntimeTimeout,
    DbgptRuntimeUnavailable,
    RuntimeControl,
    RuntimeRequest,
)

from .runtime import BoundedAgentOrchestrator, ProgressCallback


class _ControlledToolExecutor:
    def __init__(self, executor: ToolExecutor, control: RuntimeControl) -> None:
        self._executor = executor
        self._control = control

    def execute(self, call: ToolCall, context: AgentExecutionContext) -> ToolResult:
        self._control.checkpoint()
        result = self._executor.execute(call, context)
        self._control.checkpoint()
        return result


class DbgptOrchestrationResult(OrchestrationResult):
    """Orchestration result with auditable selected-runtime evidence."""

    upstream_revision: str = UPSTREAM_REVISION
    upstream_package_version: str = UPSTREAM_PACKAGE_VERSION
    upstream_install_source: str = "unverified"
    runtime_calls: int = Field(ge=0)
    total_runtime_calls: int = Field(ge=0)
    runtime_trace_stages: tuple[str, ...]
    runtime_verified: bool = False


class DbgptSelectedRuntimeOrchestrator:
    """Make real pinned AWEL ``BaseOperator.call`` the selected runtime boundary.

    AWEL receives only route/trace/budgets. The privileged five-role/six-tool
    ChatBI orchestrator remains behind a single callback, so DB-GPT never sees
    keys, connector objects, datasource identifiers, semantic-model identifiers,
    generated SQL, or tool outputs.
    """

    def __init__(
        self,
        executor: ToolExecutor,
        *,
        progress_callback: ProgressCallback | None = None,
        runtime: DbgptAwelRuntime | None = None,
    ) -> None:
        self._executor = executor
        self._progress_callback = progress_callback
        self._runtime = runtime or DbgptAwelRuntime()

    def run(
        self,
        request: OrchestrationRequest,
        *,
        cancellation_event: threading.Event | None = None,
        deadline_monotonic: float | None = None,
    ) -> DbgptOrchestrationResult:
        runtime_request = RuntimeRequest(
            question=request.question,
            route=request.route.value,
            trace_id=request.context.trace_id,
            max_steps=request.context.max_steps,
            max_tool_calls=request.context.max_tool_calls,
        )
        timeout_seconds = min(30.0, request.context.timeout_ms / 1000)

        def invoke_chatbi(control: RuntimeControl) -> OrchestrationResult:
            control.checkpoint()
            controlled = _ControlledToolExecutor(self._executor, control)
            result = BoundedAgentOrchestrator(
                controlled, progress_callback=self._progress_callback
            ).run(request)
            control.checkpoint()
            return result

        try:
            selected = self._runtime.run(
                runtime_request,
                invoke_chatbi,
                cancellation_event=cancellation_event,
                deadline_monotonic=deadline_monotonic,
                timeout_seconds=timeout_seconds,
            )
        except DbgptRuntimeTimeout:
            return self._failure(request, "TIMEOUT", "DBGPT_RUNTIME_TIMEOUT")
        except DbgptRuntimeCancelled:
            return self._failure(request, "REFUSED", "DBGPT_RUNTIME_CANCELLED")
        except DbgptRuntimeUnavailable:
            return self._failure(request, "FAILED", "DBGPT_RUNTIME_UNAVAILABLE")
        except DbgptRuntimeProvenanceError:
            return self._failure(request, "REFUSED", "DBGPT_RUNTIME_PROVENANCE")
        except DbgptRuntimePolicyError:
            return self._failure(request, "REFUSED", "DBGPT_RUNTIME_POLICY")
        except DbgptRuntimeError:
            return self._failure(request, "FAILED", "DBGPT_RUNTIME_FAILED")
        except Exception:
            return self._failure(request, "FAILED", "DBGPT_CALLBACK_FAILED")

        orchestration = selected.output
        if not isinstance(orchestration, OrchestrationResult):
            return self._failure(request, "FAILED", "DBGPT_CALLBACK_RESULT_INVALID")
        return DbgptOrchestrationResult.model_validate(
            {
                **orchestration.model_dump(),
                "upstream_revision": selected.upstream_revision,
                "upstream_package_version": selected.upstream_package_version,
                "upstream_install_source": selected.upstream_install_source,
                "runtime_calls": selected.runtime_calls,
                "total_runtime_calls": selected.total_runtime_calls,
                "runtime_trace_stages": selected.trace_stages,
                "runtime_verified": True,
            }
        )

    def _failure(
        self,
        request: OrchestrationRequest,
        status: str,
        error_code: str,
    ) -> DbgptOrchestrationResult:
        return DbgptOrchestrationResult(
            status=status,
            route=request.route,
            trace_id=request.context.trace_id,
            run_id=str(uuid4()),
            steps=(),
            fallback_used=False,
            error_code=error_code,
            verification={"result_verified": False, "citation_verified": False},
            performance={"ttft_ms": 0, "total_latency_ms": 0, "tool_latency_ms": 0},
            tool_call_count=0,
            replan_count=0,
            max_depth_observed=1,
            trace_complete=False,
            upstream_revision=UPSTREAM_REVISION,
            upstream_package_version=UPSTREAM_PACKAGE_VERSION,
            upstream_install_source="unverified",
            runtime_calls=0,
            total_runtime_calls=self._runtime.total_runtime_calls,
            runtime_trace_stages=(f"agent.runtime.failed.{error_code.lower()}",),
            runtime_verified=False,
        )
