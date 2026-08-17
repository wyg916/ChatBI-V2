from __future__ import annotations

import time
from collections.abc import Callable
from uuid import uuid4

from chatbi_agent_contracts import (
    AgentExecutionContext,
    OrchestrationRequest,
    OrchestrationResult,
    OrchestrationStep,
    QuestionRoute,
    ToolCall,
    ToolExecutor,
)


class OrchestrationError(RuntimeError):
    pass


class BoundedAgentOrchestrator:
    def __init__(self, tool_executor: ToolExecutor, *, monotonic: Callable[[], float] = time.monotonic) -> None:
        self.tool_executor = tool_executor
        self.monotonic = monotonic

    def run(self, request: OrchestrationRequest) -> OrchestrationResult:
        started = self.monotonic()
        run_id = f"ORCH-{uuid4()}"
        steps: list[OrchestrationStep] = []
        data_evidence = None
        knowledge_evidence = None
        planned_tools = ["data.query"]
        if request.include_knowledge:
            planned_tools.append("knowledge.retrieve")
        if len(planned_tools) > request.context.max_steps:
            return self._result(request, run_id, steps, status="REFUSED", error_code="STEP_LIMIT_EXCEEDED")
        for ordinal, tool_name in enumerate(planned_tools, 1):
            if self._timed_out(started, request.context):
                steps.append(OrchestrationStep(ordinal=ordinal, code="deadline", tool_name=tool_name, status="TIMEOUT"))
                return self._result(request, run_id, steps, status="TIMEOUT", error_code="AGENT_TIMEOUT")
            if tool_name not in request.context.allowed_tools:
                steps.append(OrchestrationStep(
                    ordinal=ordinal,
                    code="authorization",
                    tool_name=tool_name,
                    status="REFUSED",
                    detail={"reason": "UNAUTHORIZED_TOOL_CALL"},
                ))
                return self._result(request, run_id, steps, status="REFUSED", error_code="UNAUTHORIZED_TOOL_CALL")
            arguments = {
                "question": request.question,
                "datasource_id": request.datasource_id,
                "semantic_model_id": request.semantic_model_id,
            }
            result = self.tool_executor.execute(
                ToolCall(
                    tool_name=tool_name,
                    arguments=arguments,
                    idempotency_key=f"{request.idempotency_key}:{ordinal}",
                ),
                request.context,
            )
            steps.append(OrchestrationStep(
                ordinal=ordinal,
                code="tool_call",
                tool_name=tool_name,
                status=result.status,
                detail={"error_code": result.error_code} if result.error_code else {},
            ))
            if result.status != "SUCCEEDED":
                status = "TIMEOUT" if result.status == "TIMEOUT" else "PARTIAL" if data_evidence else "FAILED"
                return self._result(
                    request,
                    run_id,
                    steps,
                    status=status,
                    data_evidence=data_evidence,
                    knowledge_evidence=knowledge_evidence,
                    error_code=result.error_code or "TOOL_CALL_FAILED",
                )
            if tool_name == "data.query":
                data_evidence = result.output
            else:
                knowledge_evidence = result.output
        return self._result(
            request,
            run_id,
            steps,
            status="SUCCEEDED",
            data_evidence=data_evidence,
            knowledge_evidence=knowledge_evidence,
        )

    def _timed_out(self, started: float, context: AgentExecutionContext) -> bool:
        return (self.monotonic() - started) * 1000 >= context.timeout_ms

    @staticmethod
    def _result(
        request: OrchestrationRequest,
        run_id: str,
        steps: list[OrchestrationStep],
        *,
        status: str,
        data_evidence: dict | None = None,
        knowledge_evidence: dict | None = None,
        error_code: str | None = None,
    ) -> OrchestrationResult:
        return OrchestrationResult(
            status=status,
            route=request.route,
            trace_id=request.context.trace_id,
            run_id=run_id,
            steps=tuple(steps),
            data_evidence=data_evidence,
            knowledge_evidence=knowledge_evidence,
            error_code=error_code,
        )


class LegacyAgentOrchestratorAdapter:
    def __init__(
        self,
        *,
        base_url: str,
        bearer_token: str = "",
        endpoint: str = "/api/v1/assistant/query",
    ) -> None:
        if not base_url.startswith(("http://", "https://")):
            raise ValueError("legacy agent base_url must use HTTP or HTTPS")
        self.base_url = base_url.rstrip("/")
        self.bearer_token = bearer_token
        self.endpoint = endpoint

    def run(self, request: OrchestrationRequest) -> OrchestrationResult:
        del request
        raise OrchestrationError(
            "legacy assistant endpoint cannot use the ChatBI V2 ToolExecutor callback; remote execution is disabled"
        )
