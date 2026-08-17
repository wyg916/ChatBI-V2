from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from time import perf_counter
from typing import Any, Callable, Iterable
from uuid import uuid4

from chatbi_agent_contracts import (
    AgentExecutionContext,
    AgentRole,
    OrchestrationRequest,
    OrchestrationResult,
    OrchestrationStep,
    ProgressStage,
    ToolCall,
    ToolExecutor,
    ToolName,
    ToolResult,
)


ProgressCallback = Callable[[ProgressStage, dict[str, Any]], None]


class OrchestrationError(RuntimeError):
    """Raised when a bounded orchestration contract cannot be satisfied."""


@dataclass(frozen=True)
class AgentAssignment:
    role: AgentRole
    tool: ToolName


class PlannerAgent:
    """Creates a fixed, auditable plan from the approved six-tool catalogue."""

    role = AgentRole.PLANNER

    def plan(self, request: OrchestrationRequest) -> tuple[AgentAssignment, ...]:
        assignments: list[AgentAssignment] = [
            AgentAssignment(AgentRole.DATA_ANALYST, ToolName.QUERY_DATA),
        ]
        if request.include_knowledge:
            assignments.append(
                AgentAssignment(AgentRole.KNOWLEDGE, ToolName.RETRIEVE_KNOWLEDGE)
            )
        assignments.append(
            AgentAssignment(AgentRole.VERIFICATION, ToolName.VERIFY_RESULT)
        )
        if request.include_knowledge:
            assignments.append(
                AgentAssignment(AgentRole.VERIFICATION, ToolName.VERIFY_CITATION)
            )
        assignments.extend(
            (
                AgentAssignment(AgentRole.INSIGHT, ToolName.GENERATE_CHART),
                AgentAssignment(AgentRole.INSIGHT, ToolName.GENERATE_INSIGHT),
            )
        )
        return tuple(assignments)


class DataAnalystAgent:
    role = AgentRole.DATA_ANALYST
    tools = frozenset({ToolName.QUERY_DATA})


class KnowledgeAgent:
    role = AgentRole.KNOWLEDGE
    tools = frozenset({ToolName.RETRIEVE_KNOWLEDGE})


class VerificationAgent:
    role = AgentRole.VERIFICATION
    tools = frozenset({ToolName.VERIFY_RESULT, ToolName.VERIFY_CITATION})


class InsightAgent:
    role = AgentRole.INSIGHT
    tools = frozenset({ToolName.GENERATE_CHART, ToolName.GENERATE_INSIGHT})


ROLE_TOOL_POLICY: dict[AgentRole, frozenset[ToolName]] = {
    DataAnalystAgent.role: DataAnalystAgent.tools,
    KnowledgeAgent.role: KnowledgeAgent.tools,
    VerificationAgent.role: VerificationAgent.tools,
    InsightAgent.role: InsightAgent.tools,
}


def _stage_for(tool: ToolName) -> ProgressStage:
    if tool is ToolName.QUERY_DATA:
        return ProgressStage.QUERYING_DATA
    if tool is ToolName.RETRIEVE_KNOWLEDGE:
        return ProgressStage.RETRIEVING_KNOWLEDGE
    if tool in {ToolName.VERIFY_RESULT, ToolName.VERIFY_CITATION}:
        return ProgressStage.VERIFYING
    return ProgressStage.GENERATING_INSIGHT


def _status_for(result: ToolResult) -> str:
    return {
        "SUCCEEDED": "SUCCEEDED",
        "REFUSED": "REFUSED",
        "TIMEOUT": "TIMEOUT",
        "FAILED": "FAILED",
    }[result.status]


class BoundedAgentOrchestrator:
    """Runs the five fixed roles with hard budgets and no dynamic tool discovery."""

    def __init__(
        self,
        executor: ToolExecutor,
        *,
        progress_callback: ProgressCallback | None = None,
    ) -> None:
        self._executor = executor
        self._progress_callback = progress_callback
        self._planner = PlannerAgent()

    def run(self, request: OrchestrationRequest) -> OrchestrationResult:
        started = perf_counter()
        run_id = str(uuid4())
        callback = self._progress_callback
        first_progress_ms: int | None = None

        def progress(stage: ProgressStage, **detail: Any) -> None:
            nonlocal first_progress_ms
            elapsed_ms = int((perf_counter() - started) * 1000)
            if first_progress_ms is None:
                first_progress_ms = elapsed_ms
            if callback is not None:
                callback(stage, {"elapsed_ms": elapsed_ms, **detail})

        progress(ProgressStage.UNDERSTANDING, role=AgentRole.PLANNER.value)
        self._validate_request_budget(request)
        assignments = self._planner.plan(request)
        planned_step_count = 1 + len(assignments)
        if planned_step_count > request.context.max_steps:
            return self._terminal_result(
                request,
                run_id,
                started,
                first_progress_ms,
                status="REFUSED",
                steps=(),
                error_code="AGENT_STEP_BUDGET_EXCEEDED",
            )
        if len(assignments) > request.context.max_tool_calls:
            return self._terminal_result(
                request,
                run_id,
                started,
                first_progress_ms,
                status="REFUSED",
                steps=(),
                error_code="AGENT_TOOL_BUDGET_EXCEEDED",
            )

        steps: list[OrchestrationStep] = [
            OrchestrationStep(
                ordinal=1,
                code="PLAN_FIXED_WORKFLOW",
                agent_role=AgentRole.PLANNER,
                status="SUCCEEDED",
                detail={
                    "assignment_count": len(assignments),
                    "prompt_version": request.prompt_versions.get("agent.planner", ""),
                },
            )
        ]
        data_evidence: dict[str, Any] | None = None
        knowledge_evidence: dict[str, Any] | None = None
        result_verified = False
        citation_verified = not request.include_knowledge
        answer: str | None = None
        fallback_used = False
        tool_latency_ms = 0
        tool_call_count = 0

        for assignment in assignments:
            if self._elapsed_ms(started) >= request.context.timeout_ms:
                progress(ProgressStage.COMPLETED, status="TIMEOUT")
                return self._terminal_result(
                    request,
                    run_id,
                    started,
                    first_progress_ms,
                    status="TIMEOUT",
                    steps=tuple(steps),
                    data_evidence=data_evidence,
                    knowledge_evidence=knowledge_evidence,
                    error_code="AGENT_TIMEOUT",
                    tool_latency_ms=tool_latency_ms,
                    tool_call_count=tool_call_count,
                )

            if assignment.tool is ToolName.VERIFY_CITATION and knowledge_evidence is None:
                fallback_used = True
                steps.append(
                    OrchestrationStep(
                        ordinal=len(steps) + 1,
                        code=assignment.tool.value,
                        agent_role=assignment.role,
                        tool_name=assignment.tool.value,
                        status="REFUSED",
                        detail={"error_code": "KNOWLEDGE_EVIDENCE_UNAVAILABLE"},
                    )
                )
                continue

            if assignment.tool.value not in request.context.allowed_tools:
                steps.append(
                    OrchestrationStep(
                        ordinal=len(steps) + 1,
                        code=assignment.tool.value,
                        agent_role=assignment.role,
                        tool_name=assignment.tool.value,
                        status="REFUSED",
                        detail={"error_code": "UNAUTHORIZED_TOOL_CALL"},
                    )
                )
                progress(ProgressStage.COMPLETED, status="REFUSED")
                return self._terminal_result(
                    request,
                    run_id,
                    started,
                    first_progress_ms,
                    status="REFUSED",
                    steps=tuple(steps),
                    data_evidence=data_evidence,
                    knowledge_evidence=knowledge_evidence,
                    error_code="UNAUTHORIZED_TOOL_CALL",
                    result_verified=result_verified,
                    citation_verified=citation_verified,
                    tool_latency_ms=tool_latency_ms,
                    tool_call_count=tool_call_count,
                )

            progress(
                _stage_for(assignment.tool),
                role=assignment.role.value,
                tool=assignment.tool.value,
            )
            arguments = self._arguments_for(
                assignment.tool,
                request,
                data_evidence=data_evidence,
                knowledge_evidence=knowledge_evidence,
                result_verified=result_verified,
                citation_verified=citation_verified,
            )
            call = ToolCall(
                tool_name=assignment.tool.value,
                agent_role=assignment.role,
                arguments=arguments,
                idempotency_key=self._call_key(
                    request.idempotency_key, len(steps) + 1, assignment.tool
                ),
                agent_depth=1,
                replan_count=0,
            )
            tool_started = perf_counter()
            try:
                result = self._executor.execute(call, request.context)
            except Exception as exc:  # fail closed without exposing exception text
                result = ToolResult(
                    tool_name=assignment.tool.value,
                    status="FAILED",
                    error_code=f"TOOL_EXCEPTION_{type(exc).__name__.upper()}",
                )
            measured_ms = int((perf_counter() - tool_started) * 1000)
            duration_ms = max(measured_ms, result.duration_ms)
            tool_latency_ms += duration_ms
            tool_call_count += 1
            steps.append(
                OrchestrationStep(
                    ordinal=len(steps) + 1,
                    code=assignment.tool.value,
                    agent_role=assignment.role,
                    tool_name=assignment.tool.value,
                    status=_status_for(result),
                    detail={
                        "error_code": result.error_code,
                        "output_keys": sorted(result.output),
                    },
                    duration_ms=duration_ms,
                )
            )

            if result.status != "SUCCEEDED":
                if assignment.tool is ToolName.RETRIEVE_KNOWLEDGE:
                    fallback_used = True
                    knowledge_evidence = None
                    citation_verified = False
                    continue
                if assignment.tool is ToolName.VERIFY_CITATION:
                    fallback_used = True
                    knowledge_evidence = None
                    citation_verified = False
                    continue
                terminal_status = (
                    "TIMEOUT" if result.status == "TIMEOUT" else result.status
                )
                progress(ProgressStage.COMPLETED, status=terminal_status)
                return self._terminal_result(
                    request,
                    run_id,
                    started,
                    first_progress_ms,
                    status=terminal_status,
                    steps=tuple(steps),
                    data_evidence=data_evidence,
                    knowledge_evidence=knowledge_evidence,
                    fallback_used=fallback_used,
                    error_code=result.error_code or "TOOL_EXECUTION_FAILED",
                    result_verified=result_verified,
                    citation_verified=citation_verified,
                    tool_latency_ms=tool_latency_ms,
                    tool_call_count=tool_call_count,
                )

            if assignment.tool is ToolName.QUERY_DATA:
                data_evidence = result.output
            elif assignment.tool is ToolName.RETRIEVE_KNOWLEDGE:
                knowledge_evidence = result.output
            elif assignment.tool is ToolName.VERIFY_RESULT:
                result_verified = bool(result.output.get("verified"))
                if not result_verified:
                    progress(ProgressStage.COMPLETED, status="REFUSED")
                    return self._terminal_result(
                        request,
                        run_id,
                        started,
                        first_progress_ms,
                        status="REFUSED",
                        steps=tuple(steps),
                        data_evidence=data_evidence,
                        knowledge_evidence=knowledge_evidence,
                        error_code="RESULT_VERIFICATION_FAILED",
                        result_verified=False,
                        citation_verified=citation_verified,
                        tool_latency_ms=tool_latency_ms,
                        tool_call_count=tool_call_count,
                    )
            elif assignment.tool is ToolName.VERIFY_CITATION:
                citation_verified = bool(result.output.get("verified"))
                if not citation_verified:
                    fallback_used = True
                    knowledge_evidence = None
            elif assignment.tool is ToolName.GENERATE_INSIGHT:
                answer = result.output.get("answer")

        final_status = "PARTIAL" if fallback_used else "SUCCEEDED"
        if not result_verified or not answer:
            final_status = "FAILED"
            answer = None
        progress(ProgressStage.COMPLETED, status=final_status)
        return self._terminal_result(
            request,
            run_id,
            started,
            first_progress_ms,
            status=final_status,
            steps=tuple(steps),
            data_evidence=data_evidence,
            knowledge_evidence=knowledge_evidence,
            answer=answer,
            fallback_used=fallback_used,
            error_code=None if answer else "VERIFIED_ANSWER_UNAVAILABLE",
            result_verified=result_verified,
            citation_verified=citation_verified,
            tool_latency_ms=tool_latency_ms,
            tool_call_count=tool_call_count,
        )

    @staticmethod
    def _validate_request_budget(request: OrchestrationRequest) -> None:
        context = request.context
        if context.max_steps > 8 or context.max_tool_calls > 12:
            raise OrchestrationError("agent execution budget exceeds the V1 ceiling")
        if context.max_replan > 2 or context.max_agent_depth > 2:
            raise OrchestrationError("agent recursion budget exceeds the V1 ceiling")
        approximate_tokens = max(1, len(request.question.encode("utf-8")) // 3)
        if approximate_tokens > context.token_budget:
            raise OrchestrationError("question exceeds token budget")

    @staticmethod
    def _arguments_for(
        tool: ToolName,
        request: OrchestrationRequest,
        *,
        data_evidence: dict[str, Any] | None,
        knowledge_evidence: dict[str, Any] | None,
        result_verified: bool,
        citation_verified: bool,
    ) -> dict[str, Any]:
        base = {
            "question": request.question,
            "datasource_id": request.datasource_id,
            "semantic_model_id": request.semantic_model_id,
            "prompt_versions": request.prompt_versions,
        }
        if tool in {
            ToolName.VERIFY_RESULT,
            ToolName.GENERATE_CHART,
            ToolName.GENERATE_INSIGHT,
        }:
            base["data_evidence"] = data_evidence
        if tool in {
            ToolName.VERIFY_CITATION,
            ToolName.GENERATE_INSIGHT,
        }:
            base["knowledge_evidence"] = knowledge_evidence
        if tool is ToolName.GENERATE_INSIGHT:
            base["result_verified"] = result_verified
            base["citation_verified"] = citation_verified
        return base

    @staticmethod
    def _call_key(prefix: str, ordinal: int, tool: ToolName) -> str:
        material = f"{prefix}:{ordinal}:{tool.value}"
        return sha256(material.encode("utf-8")).hexdigest()

    @staticmethod
    def _elapsed_ms(started: float) -> int:
        return int((perf_counter() - started) * 1000)

    def _terminal_result(
        self,
        request: OrchestrationRequest,
        run_id: str,
        started: float,
        first_progress_ms: int | None,
        *,
        status: str,
        steps: Iterable[OrchestrationStep],
        data_evidence: dict[str, Any] | None = None,
        knowledge_evidence: dict[str, Any] | None = None,
        answer: str | None = None,
        fallback_used: bool = False,
        error_code: str | None = None,
        result_verified: bool = False,
        citation_verified: bool = False,
        tool_latency_ms: int = 0,
        tool_call_count: int = 0,
    ) -> OrchestrationResult:
        step_tuple = tuple(steps)
        return OrchestrationResult(
            status=status,
            route=request.route,
            trace_id=request.context.trace_id,
            run_id=run_id,
            steps=step_tuple,
            data_evidence=data_evidence,
            knowledge_evidence=knowledge_evidence,
            answer=answer,
            fallback_used=fallback_used,
            error_code=error_code,
            verification={
                "result_verified": result_verified,
                "citation_verified": citation_verified,
            },
            performance={
                "ttft_ms": first_progress_ms or 0,
                "total_latency_ms": self._elapsed_ms(started),
                "tool_latency_ms": tool_latency_ms,
            },
            tool_call_count=tool_call_count,
            replan_count=0,
            max_depth_observed=1,
            trace_complete=bool(step_tuple) and len(step_tuple) <= request.context.max_steps,
        )


class LegacyAgentOrchestratorAdapter:
    """Compatibility marker that deliberately refuses the retired legacy runtime."""

    def run(self, request: OrchestrationRequest) -> OrchestrationResult:
        return OrchestrationResult(
            status="REFUSED",
            route=request.route,
            trace_id=request.context.trace_id,
            run_id=str(uuid4()),
            steps=(),
            fallback_used=True,
            error_code="LEGACY_AGENT_RUNTIME_DISABLED",
            verification={"result_verified": False, "citation_verified": False},
            performance={"ttft_ms": 0, "total_latency_ms": 0, "tool_latency_ms": 0},
            tool_call_count=0,
            replan_count=0,
            max_depth_observed=1,
            trace_complete=False,
        )
