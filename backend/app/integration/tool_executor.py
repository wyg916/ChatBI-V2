from __future__ import annotations

import hashlib
import json
import re
from time import perf_counter
from threading import Event

from chatbi_agent_contracts import (
    AgentExecutionContext,
    AgentRole,
    ToolCall,
    ToolName,
    ToolResult,
)
from chatbi_rag_adapter import CitationVerifierV1, LiveRagAdapter, RagAdapterError
from chatbi_rag_contracts import Citation, RagExecutionContext, RagRequest
from sqlalchemy.orm import Session

from app.core.access import Principal
from app.model_gateway.contracts import RequestContext
from app.query.contracts import AskRequest
from app.query.service import QueryPipeline, query_response
from app.core.config import get_settings
from app.file_multimodal.pandasai_adapter import PandasAIExecutionRequest, execute_selected_pandasai_runtime
from app.sandbox import SandboxControllerClient


def _bind_derived_result(
    payload: dict,
    *,
    rows: list[dict],
    metrics: list[str],
    dimensions: list[str],
    claims: list[dict],
    summary: str,
) -> dict:
    signature = hashlib.sha256(json.dumps(
        rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str,
    ).encode("utf-8")).hexdigest()
    execution = {
        **(payload.get("execution") or {}),
        "columns": list(rows[0]) if rows else [*dimensions, *metrics],
        "rows": rows,
        "row_count": len(rows),
        "result_signature": signature,
    }
    plan = {**(payload.get("plan") or {}), "metrics": metrics, "dimensions": dimensions}
    chart = {**(payload.get("chart_spec") or {})}
    if chart:
        chart["result_signature"] = signature
        chart["data_source_query_id"] = payload.get("id")
    payload.update({
        "execution": execution,
        "plan": plan,
        "chart_spec": chart,
        "result_evidence": {
            "metrics": metrics,
            "dimensions": dimensions,
            "row_count": len(rows),
            "rows": rows,
            "result_signature": signature,
        },
        "answer_claims": claims,
        "summary": summary,
    })
    return payload


ROLE_TOOLS: dict[AgentRole, frozenset[ToolName]] = {
    AgentRole.DATA_ANALYST: frozenset({ToolName.QUERY_DATA}),
    AgentRole.KNOWLEDGE: frozenset({ToolName.RETRIEVE_KNOWLEDGE}),
    AgentRole.VERIFICATION: frozenset(
        {ToolName.VERIFY_RESULT, ToolName.VERIFY_CITATION}
    ),
    AgentRole.INSIGHT: frozenset(
        {ToolName.GENERATE_CHART, ToolName.GENERATE_INSIGHT}
    ),
}


class ChatBIToolExecutor:
    """The sole six-tool bridge; it exposes no connector, URL, SQL or file tool."""

    tool_catalogue = frozenset(ToolName)
    direct_db_access = False
    dynamic_tool_loading = False
    file_access = False
    network_access = False

    def __init__(
        self, db: Session, principal: Principal, rag_adapter,
        *, cancellation_event: Event | None = None, file_evidence: dict | None = None,
        request_context: RequestContext | None = None,
    ) -> None:
        self.db = db
        self.principal = principal
        self.rag_adapter = rag_adapter
        self.cancellation_event = cancellation_event
        self.file_evidence = file_evidence
        self.request_context = request_context
        self.citation_verifier = CitationVerifierV1()

    def execute(self, call: ToolCall, context: AgentExecutionContext) -> ToolResult:
        started = perf_counter()
        try:
            tool = ToolName(call.tool_name)
        except ValueError:
            return self._result(call.tool_name, started, "REFUSED", "UNAUTHORIZED_TOOL_CALL")
        if tool.value not in context.allowed_tools:
            return self._result(call.tool_name, started, "REFUSED", "UNAUTHORIZED_TOOL_CALL")
        if tool not in ROLE_TOOLS.get(call.agent_role, frozenset()):
            return self._result(call.tool_name, started, "REFUSED", "AGENT_ROLE_TOOL_DENIED")
        handlers = {
            ToolName.QUERY_DATA: self._query_data,
            ToolName.RETRIEVE_KNOWLEDGE: self._retrieve_knowledge,
            ToolName.VERIFY_RESULT: self._verify_result,
            ToolName.VERIFY_CITATION: self._verify_citation,
            ToolName.GENERATE_CHART: self._generate_chart,
            ToolName.GENERATE_INSIGHT: self._generate_insight,
        }
        try:
            status, output, error_code = handlers[tool](call, context)
        except Exception as exc:  # fail closed and never expose exception text
            return self._result(
                call.tool_name,
                started,
                "FAILED",
                f"TOOL_RUNTIME_{type(exc).__name__.upper()}",
            )
        return self._result(call.tool_name, started, status, error_code, output)

    def _query_data(self, call: ToolCall, context: AgentExecutionContext):
        datasource_id = call.arguments.get("datasource_id")
        semantic_model_id = call.arguments.get("semantic_model_id")
        if datasource_id and datasource_id not in context.allowed_datasources:
            return "REFUSED", {}, "DATASOURCE_SCOPE_DENIED"
        if semantic_model_id and semantic_model_id not in context.allowed_semantic_models:
            return "REFUSED", {}, "SEMANTIC_MODEL_SCOPE_DENIED"
        question = str(call.arguments.get("question") or "")
        if self.file_evidence:
            regions = list(dict.fromkeys(
                str(row.get("region")) for row in self.file_evidence.get("rows") or [] if row.get("region")
            ))
            if regions:
                question += "；按地区查询" + "或".join(regions)
        run = QueryPipeline().execute(
            self.db,
            AskRequest(
                question=question,
                datasource_id=datasource_id,
                semantic_model_id=semantic_model_id,
            ),
            principal=self.principal,
            cancellation_event=self.cancellation_event,
            request_context=(
                self.request_context.model_copy(update={
                    "question": question,
                    "datasource_id": datasource_id or self.request_context.datasource_id,
                })
                if self.request_context is not None
                else None
            ),
        )
        payload = query_response(run).model_dump(mode="json")
        guard_allowed = bool((payload.get("guard") or {}).get("allowed"))
        oracle_passed = (payload.get("oracle") or {}).get("status") == "PASSED"
        signature = (payload.get("execution") or {}).get("result_signature")
        if run.status != "SUCCEEDED" or not guard_allowed or not oracle_passed or not signature:
            status = "REFUSED" if run.status == "SECURITY_REJECTED" else "FAILED"
            return status, {"query_id": run.id, "status": run.status}, (
                run.error_code or "RESULT_ORACLE_NOT_PASSED"
            )
        if self.file_evidence:
            payload = self._file_database_comparison(payload)
        elif re.search(r"(?:Python|相关性|相关系数)", question, re.IGNORECASE):
            payload, sandbox_error = self._correlation_result(payload, context)
            if sandbox_error:
                return "FAILED", payload, sandbox_error
        return "SUCCEEDED", payload, None

    def _correlation_result(self, payload: dict, context: AgentExecutionContext) -> tuple[dict, str | None]:
        rows = list((payload.get("execution") or {}).get("rows") or [])
        code = (
            "rows = datasets['rows']\n"
            "xs = [float(row['revenue']) for row in rows]\n"
            "ys = [float(row['cost']) for row in rows]\n"
            "n = len(xs)\n"
            "mx = sum(xs) / n\n"
            "my = sum(ys) / n\n"
            "num = sum((x-mx)*(y-my) for x,y in zip(xs,ys))\n"
            "denx = sum((x-mx)**2 for x in xs)\n"
            "deny = sum((y-my)**2 for y in ys)\n"
            "corr = num / ((denx * deny) ** 0.5) if denx and deny else 0.0\n"
            "result = {'correlation': round(corr, 12), 'sample_size': n}\n"
        )
        upstream = execute_selected_pandasai_runtime(
            PandasAIExecutionRequest(
                code=code,
                environment={"rows": rows},
                trace_id=context.trace_id,
                workspace_id=context.workspace_id,
                timeout_ms=min(context.timeout_ms, 15_000),
                cancellation_event=self.cancellation_event,
            ),
            SandboxControllerClient(get_settings().sandbox_controller_url),
        )
        sandbox = dict(upstream.output)
        result = dict(sandbox.get("output") or {})
        evidence = {
            "status": sandbox.get("status"),
            "runtime_verified": bool(sandbox.get("runtime_verified")),
            "container_destroyed": bool(sandbox.get("container_destroyed")),
            "operation": "correlation",
            "result": result,
        }
        payload["sandbox_evidence"] = evidence
        if evidence["status"] != "SUCCEEDED" or not evidence["runtime_verified"] or not evidence["container_destroyed"]:
            return payload, str(sandbox.get("error_code") or "SANDBOX_RESULT_NOT_VERIFIED")
        years: list[str] = []
        for row in rows:
            value = row.get("year") if row.get("year") is not None else row.get("order_date")
            if value is None:
                continue
            rendered = str(value)
            match = re.search(r"(?<!\d)(20\d{2})(?!\d)", rendered)
            canonical = match.group(1) if match else rendered
            if canonical not in years:
                years.append(canonical)
        scope = "ANNUAL_REVENUE_COST" + ("_" + "_".join(years) if years else "")
        derived_rows = [{"correlation": float(result["correlation"]), "sample_size": int(result["sample_size"])}]
        claim = {"metric": "correlation", "scope": scope, "value": float(result["correlation"])}
        return _bind_derived_result(
            payload,
            rows=derived_rows,
            metrics=["correlation", "sample_size"],
            dimensions=[],
            claims=[claim],
            summary=f"correlation 为 {claim['value']}。",
        ), None

    def _file_database_comparison(self, payload: dict) -> dict:
        file_rows = list((self.file_evidence or {}).get("rows") or [])
        file_by_region: dict[str, float] = {}
        for row in file_rows:
            region = str(row.get("region") or "")
            file_by_region[region] = file_by_region.get(region, 0.0) + float(row.get("revenue") or 0)
        db_by_region = {
            str(row.get("region")): float(row.get("revenue") or 0)
            for row in (payload.get("execution") or {}).get("rows") or []
        }
        rows = [
            {
                "region": region,
                "file_revenue": file_value,
                "db_revenue": db_by_region.get(region, 0.0),
                "difference": file_value - db_by_region.get(region, 0.0),
            }
            for region, file_value in file_by_region.items()
        ]
        claim = ({
            "metric": "difference",
            "dimension": "region",
            "dimension_value": rows[0]["region"],
            "value": rows[0]["difference"],
        } if rows else {})
        payload["file_evidence"] = {
            key: value for key, value in (self.file_evidence or {}).items() if key != "rows"
        }
        return _bind_derived_result(
            payload,
            rows=rows,
            metrics=["file_revenue", "db_revenue", "difference"],
            dimensions=["region"],
            claims=[claim] if claim else [],
            summary=(
                f"{claim['dimension_value']}的difference 为 {claim['value']}。"
                if claim else "文件与数据库比较没有数据。"
            ),
        )

    def _retrieve_knowledge(self, call: ToolCall, context: AgentExecutionContext):
        if self.rag_adapter is None:
            return "FAILED", {}, "RAG_RUNTIME_UNAVAILABLE"
        try:
            rag_request = RagRequest(
                    query=str(call.arguments.get("question") or ""),
                    scenario_id="charging_ops",
                    context=RagExecutionContext(
                        workspace_id=context.workspace_id,
                        user_id=context.user_id,
                        roles=context.roles,
                        allowed_datasources=context.allowed_datasources,
                        allowed_semantic_models=context.allowed_semantic_models,
                        allowed_tools=frozenset({ToolName.RETRIEVE_KNOWLEDGE.value}),
                        trace_id=context.trace_id,
                        timeout_ms=context.timeout_ms,
                        max_steps=context.max_steps,
                        token_budget=context.token_budget,
                    ),
                )
            if isinstance(self.rag_adapter, LiveRagAdapter):
                result = self.rag_adapter.retrieve(
                    rag_request, cancellation_event=self.cancellation_event,
                )
            else:
                if self.cancellation_event is not None and self.cancellation_event.is_set():
                    raise RagAdapterError("live RAG request cancelled")
                result = self.rag_adapter.retrieve(rag_request)
        except RagAdapterError:
            return "FAILED", {}, "RAG_RUNTIME_FAILED"
        if result.status != "SUCCEEDED":
            return (
                "REFUSED" if result.status == "REFUSED" else "FAILED",
                {},
                result.refusal_reason or "RAG_RUNTIME_FAILED",
            )
        return "SUCCEEDED", result.model_dump(mode="json"), None

    @staticmethod
    def _verify_result(call: ToolCall, _context: AgentExecutionContext):
        evidence = call.arguments.get("data_evidence") or {}
        verified = bool(
            evidence.get("status") == "SUCCEEDED"
            and (evidence.get("guard") or {}).get("allowed") is True
            and (evidence.get("oracle") or {}).get("status") == "PASSED"
            and (evidence.get("execution") or {}).get("result_signature")
        )
        return (
            "SUCCEEDED" if verified else "REFUSED",
            {
                "verified": verified,
                "query_id": evidence.get("id"),
                "result_signature": (evidence.get("execution") or {}).get("result_signature"),
            },
            None if verified else "RESULT_VERIFICATION_FAILED",
        )

    def _verify_citation(self, call: ToolCall, _context: AgentExecutionContext):
        evidence = call.arguments.get("knowledge_evidence") or {}
        try:
            citations = tuple(Citation.model_validate(item) for item in evidence.get("citations", []))
        except Exception:
            return "REFUSED", {"verified": False}, "INVALID_CITATION_PAYLOAD"
        verification = self.citation_verifier.verify(
            str(call.arguments.get("question") or ""), citations
        )
        return (
            "SUCCEEDED" if verification.passed else "REFUSED",
            {
                "verified": verification.passed,
                "verified_ids": list(verification.verified_ids),
            },
            verification.reason,
        )

    @staticmethod
    def _generate_chart(call: ToolCall, _context: AgentExecutionContext):
        evidence = call.arguments.get("data_evidence") or {}
        signature = (evidence.get("execution") or {}).get("result_signature")
        chart = evidence.get("chart_spec") or {}
        bound = bool(
            signature
            and chart.get("result_signature") == signature
            and chart.get("data_source_query_id") == evidence.get("id")
        )
        return (
            "SUCCEEDED" if bound else "REFUSED",
            {"verified": bound, "chart_spec": chart if bound else {}},
            None if bound else "CHART_EVIDENCE_BINDING_FAILED",
        )

    @staticmethod
    def _generate_insight(call: ToolCall, _context: AgentExecutionContext):
        if not call.arguments.get("result_verified"):
            return "REFUSED", {}, "UNVERIFIED_DATA_EVIDENCE"
        data = call.arguments.get("data_evidence") or {}
        knowledge = call.arguments.get("knowledge_evidence") or {}
        conclusion = str(data.get("summary") or "查询已完成并通过结果校验。").strip()
        citations = knowledge.get("citations") or []
        if citations and call.arguments.get("citation_verified"):
            titles = list(dict.fromkeys(str(item.get("title")) for item in citations if item.get("title")))
            if titles:
                conclusion += f" 相关业务口径已由《{'》《'.join(titles[:3])}》验证。"
        return (
            "SUCCEEDED",
            {
                "answer": conclusion,
                "query_id": data.get("id"),
                "result_signature": (data.get("execution") or {}).get("result_signature"),
                "citation_count": len(citations) if call.arguments.get("citation_verified") else 0,
            },
            None,
        )

    @staticmethod
    def _result(
        tool_name: str,
        started: float,
        status: str,
        error_code: str | None,
        output: dict | None = None,
    ) -> ToolResult:
        return ToolResult(
            tool_name=tool_name,
            status=status,
            output=output or {},
            error_code=error_code,
            duration_ms=max(0, int((perf_counter() - started) * 1000)),
        )
