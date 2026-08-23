from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from scripts.run_v13_phase5_live_questions_gate import (
    LiveQuestionsGate,
    REPO_ROOT,
    _action_failures,
    _answer_oracle,
    _cancel_readability_failures,
    _sse_events,
    load_external_credentials,
    load_manifest,
    run_live_gate,
    validate_backend_url,
    validate_controller_url,
)


def test_live_gate_requires_loopback_backend_and_external_secret_file(tmp_path: Path):
    assert validate_backend_url("http://127.0.0.1:8000") == "http://127.0.0.1:8000/api/v1"
    assert validate_backend_url("https://[::1]:8443/api/v1") == "https://[::1]:8443/api/v1"
    assert validate_controller_url("http://127.0.0.1:8765") == "http://127.0.0.1:8765"
    for value in (
        "https://chatbi.example.invalid/api/v1",
        "http://user:password@127.0.0.1:8000/api/v1",
        "ftp://127.0.0.1/api/v1",
        "http://127.0.0.1:8000/other",
    ):
        with pytest.raises(ValueError):
            validate_backend_url(value)

    external = tmp_path / "phase5.env"
    external.write_text(
        "CHATBI_PHASE5_EMAIL=phase5@example.invalid\nCHATBI_PHASE5_PASSWORD=external-test-only\n",
        encoding="utf-8",
    )
    assert load_external_credentials(external) == {
        "email": "phase5@example.invalid",
        "password": "external-test-only",
    }
    with pytest.raises(ValueError, match="outside the repository"):
        load_external_credentials(REPO_ROOT / ".env")


def test_cleanup_transport_failure_is_reported_not_promoted_to_verified():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadError("phase5 injected cleanup failure", request=request)

    with httpx.Client(
        transport=httpx.MockTransport(handler),
        base_url="http://127.0.0.1:8000/api/v1",
    ) as client:
        gate = LiveQuestionsGate(
            client,
            datasource_id="datasource-phase5",
            semantic_model_id="semantic-phase5",
            credentials={"email": "phase5@example.invalid", "password": "external-test-only"},
            secret_values=("external-test-only",),
        )
        gate.cleanup_tracker.attachments.append("attachment-phase5")
        gate.cleanup_tracker.conversations.append("conversation-phase5")
        gate.cleanup_tracker.authenticated = True
        cleanup = gate.cleanup()
    assert cleanup["verified"] is False
    assert cleanup["attachment_delete_204"] == cleanup["attachment_absence_404"] == 0
    assert cleanup["conversation_delete_204"] == cleanup["conversation_absence_404"] == 0
    assert cleanup["logout_204"] == 0
    assert cleanup["failures"] == [
        "attachment_cleanup_failed",
        "conversation_cleanup_failed",
        "logout_failed",
    ]


def _sse(*events: dict[str, Any]) -> str:
    return "".join(
        f"event: {event['event_type']}\ndata: {json.dumps(event)}\n\n"
        for event in events
    )


def test_weird_answer_oracle_consumes_hallucination_contract_and_requires_refusal_text():
    manifest = load_manifest(
        REPO_ROOT / "evaluation" / "golden" / "v13-phase5-weird-50.json",
        expected_count=50,
    )
    source = manifest["cases"][15]
    case = {
        **source,
        "expected_answer_contract": manifest["answer_contracts"][source["expected"]["action"]],
    }
    response = {
        "assistant_message": {"status": "SUCCEEDED", "content": "收入达到 100 万元。"},
        "result_semantic": "VALUE",
    }
    verification = {"result_verified": False, "citation_verified": False}
    oracle = _answer_oracle(response, verification)
    failures = _action_failures(
        case=case,
        response=response,
        route="DATA_QUERY",
        ledger={
            "coverage_source": "MODEL_INVOCATION_LEDGER",
            "coverage_complete": True,
            "request_id_exact": True,
            "invocation_count": 1,
            "cost_cny": 0.001,
            "statuses": ["SUCCEEDED"],
        },
        trace={"trace_id_exact": True, "status": "SUCCEEDED", "has_sql": True},
        verification=verification,
        answer_oracle=oracle,
        ground_truth={
            "kind": "STRUCTURED_RESULT",
            "exact_rows_match": False,
            "exact_claims_match": False,
            "actual_claims_present": False,
            "structured_claim_count": 0,
            "exact_date_match": False,
            "visible_claims_exact": False,
        },
    )
    assert oracle["business_claim_present"] is True
    assert "unverified_business_claim" in failures
    assert "verified_answer_evidence_missing" in failures

    refusal_source = manifest["cases"][7]
    refusal_case = {
        **refusal_source,
        "expected_answer_contract": manifest["answer_contracts"][refusal_source["expected"]["action"]],
    }
    refusal_response = {"assistant_message": {"status": "SUCCEEDED", "content": "好的。"}}
    refusal_failures = _action_failures(
        case=refusal_case,
        response=refusal_response,
        route="UNSUPPORTED",
        ledger={
            "coverage_source": "MODEL_INVOCATION_LEDGER",
            "coverage_complete": True,
            "request_id_exact": True,
            "invocation_count": 0,
            "cost_cny": 0,
            "statuses": [],
        },
        trace={"trace_id_exact": True, "status": "SUCCEEDED", "has_sql": False},
        verification=verification,
        answer_oracle=_answer_oracle(refusal_response, verification),
        ground_truth={
            "kind": "REFUSAL_NO_CLAIM",
            "exact_rows_match": False,
            "exact_claims_match": False,
            "actual_claims_present": False,
            "structured_claim_count": 0,
            "exact_date_match": False,
            "visible_claims_exact": True,
        },
    )
    assert "refusal_answer_missing" in refusal_failures


def test_sse_parser_emits_final_event_at_eof_without_trailing_blank_line():
    payload = {"event_type": "run.cancelled", "trace_id": "TRACE-P5", "request_id": "REQ-P5"}
    response = httpx.Response(
        200,
        text=f"event: run.cancelled\ndata: {json.dumps(payload)}",
        request=httpx.Request("POST", "http://127.0.0.1/chat/stream"),
    )
    assert list(_sse_events(response)) == [payload]


@pytest.mark.parametrize("status", [403, 404])
def test_cancel_unreadable_trace_or_diagnostics_fails_closed(status: int):
    failures = _cancel_readability_failures(
        {"available": False, "read_status": 404},
        {"available": False, "read_status": status},
    )
    assert failures == [
        "cancel_trace_persistence_unreadable",
        "cancel_stream_diagnostics_unreadable",
    ]


def test_complex_oracle_requires_common_checks_exact_success_sequence_and_frozen_evidence():
    manifest = load_manifest(
        REPO_ROOT / "evaluation" / "golden" / "v13-phase5-complex-5.json",
        expected_count=5,
    )
    case = manifest["cases"][0]
    steps = [
        {
            "ordinal": step["ordinal"],
            "agent_role": step["role"],
            "tool_name": step["tool"],
            "status": "SUCCEEDED",
            "duration_ms": 1,
        }
        for step in case["steps"]
    ]
    primary = {
        "steps": steps,
        "oracle": {"status": "PASSED"},
        "result_evidence": {
            "metrics": case["expected"]["expected_evidence"]["result"]["required_metrics"],
            "dimensions": ["region"],
            "row_count": 5,
            "rows": case["expected"]["expected_evidence"]["result"]["expected_rows"],
        },
        "answer_claims": case["expected"]["expected_evidence"]["result"]["expected_answer_claims"],
        "performance": {"total_latency_ms": 10},
    }
    base = {
        "actual_route": case["route"],
        "assistant_status": "SUCCEEDED",
        "result_semantic": "VALUE",
        "http_total_ms": 10,
        "ledger": {"cost_cny": 0.001},
        "trace": {
            "duration_ms": 10,
            "tools": [step["tool"] for step in case["steps"] if step["tool"]],
        },
        "verification": {
            "self_reported_result_verified": True,
            "self_reported_citation_verified": False,
            "self_reported_oracle_passed_count": 1,
            "result_signature_count": 0,
        },
        "answer_oracle": {"answer_present": True, "answer_claim_present": True},
        "response_answer_text": "西部收入为 87150.0。",
        "failures": [],
        "response_primary": primary,
    }
    with httpx.Client(base_url="http://127.0.0.1") as client:
        gate = LiveQuestionsGate(
            client,
            datasource_id="ds",
            semantic_model_id="sm",
            credentials={"email": "x", "password": "y"},
            secret_values=(),
        )
        assert gate.validate_complex(case, copy.deepcopy(base)) == []

        common = copy.deepcopy(base)
        common["failures"] = ["model_invocation_ledger_incomplete"]
        assert "model_invocation_ledger_incomplete" in gate.validate_complex(case, common)

        extra = copy.deepcopy(base)
        extra["response_primary"]["steps"].append({
            "ordinal": 6,
            "agent_role": "UnknownAgent",
            "tool_name": "UNKNOWN_TOOL",
            "status": "SUCCEEDED",
        })
        extra["trace"]["tools"].append("UNKNOWN_TOOL")
        assert "complex_step_role_tool_sequence_mismatch" in gate.validate_complex(case, extra)

        partial = copy.deepcopy(base)
        partial["response_primary"]["steps"][2]["status"] = "PARTIAL"
        assert "complex_step_not_succeeded" in gate.validate_complex(case, partial)

        missing_metric = copy.deepcopy(base)
        missing_metric["response_primary"]["result_evidence"]["metrics"] = []
        assert "complex_frozen_metric_evidence_missing" in gate.validate_complex(case, missing_metric)

        self_reported_only = copy.deepcopy(base)
        self_reported_only["response_primary"]["result_evidence"]["rows"] = [{"revenue": 999999}]
        self_reported_only["response_primary"]["answer_claims"] = [{"metric": "revenue", "value": 999999}]
        self_reported_only["verification"]["self_reported_result_verified"] = True
        self_reported_only["verification"]["self_reported_oracle_passed_count"] = 99
        truth_failures = gate.validate_complex(case, self_reported_only)
        assert "complex_frozen_result_rows_mismatch" in truth_failures
        assert "complex_frozen_answer_claims_mismatch" in truth_failures

        wrong_visible = copy.deepcopy(base)
        wrong_visible["response_answer_text"] += " 但另一个错误业务值为 999999。"
        assert "complex_visible_answer_claims_mismatch" in gate.validate_complex(case, wrong_visible)


def test_live_gate_executes_all_real_http_contracts_auto_routes_weird_and_cleans_exactly():
    weird = load_manifest(
        REPO_ROOT / "evaluation" / "golden" / "v13-phase5-weird-50.json",
        expected_count=50,
    )
    complex_manifest = load_manifest(
        REPO_ROOT / "evaluation" / "golden" / "v13-phase5-complex-5.json",
        expected_count=5,
    )
    weird_by_question = {case["question"]: case for case in weird["cases"]}
    complex_by_question = {case["question"]: case for case in complex_manifest["cases"]}
    state: dict[str, Any] = {
        "conversation_count": 0,
        "attachment_count": 0,
        "active_conversations": set(),
        "active_attachments": set(),
        "conversation_request": {},
        "traces": {},
        "weird_chat_payloads": [],
        "complex_chat_payloads": [],
        "cancel_count": 0,
    }

    def response_for_chat(payload: dict[str, Any]) -> httpx.Response:
        question = payload["content"]
        request_id = payload["client_message_id"]
        conversation_id = payload["conversation_id"]
        trace_id = f"TRACE-{request_id}"
        if question in weird_by_question:
            case = weird_by_question[question]
            assert "route" not in payload
            state["weird_chat_payloads"].append(payload)
            expected = case["expected"]
            route = expected["route"]
            action = expected["action"]
            has_sql = bool(expected["sql_execution_allowed"])
            invocation_count = 0 if expected["model_calls_max"] == 0 else 1
            semantic = "NO_ROWS" if action == "EMPTY_RESULT_NO_FABRICATION" else (
                "FAILED" if action == "NO_EVIDENCE_NO_CLAIM" else "VALUE"
            )
            tools: list[str] = []
            primary = {
                "oracle": {"status": "PASSED"} if has_sql else {},
                "result_signature": "phase5-result" if has_sql else None,
            }
            truth = weird["case_ground_truth"][case["id"]]
            if truth["kind"] in {"STRUCTURED_RESULT", "EMPTY_RESULT"}:
                primary["result_evidence"] = {
                    "rows": weird["frozen_result_sets"][truth["result_set"]],
                }
                primary["answer_claims"] = truth["expected_claims"]
            if action in {"REFUSE", "REFUSE_INJECTION", "REFUSE_SQL_INJECTION", "REFUSE_UNAUTHORIZED", "REFUSE_UNBOUNDED"}:
                answer_text = "抱歉，无法执行或支持该请求。"
            elif action in {"ASK_CLARIFICATION", "UNKNOWN_METRIC_CLARIFICATION", "UNKNOWN_ENTITY_CLARIFICATION"}:
                answer_text = "请补充明确的指标、时间范围或维度？"
            elif action == "NO_EVIDENCE_NO_CLAIM":
                answer_text = "未找到已授权证据，无法给出结论。"
            elif action == "EMPTY_RESULT_NO_FABRICATION":
                answer_text = "查询未返回数据，不提供推测结果。"
            elif action == "MODEL_NONE_DATE":
                answer_text = (
                    "星期六" if case["id"] == "W024" else
                    "Saturday" if case["id"] == "W026" else
                    "固定历史日期是 2026-08-22。"
                )
            elif action in {"QUERY_READ_ONLY", "BOUNDED_VERIFIED_ANALYSIS"}:
                claim = truth["expected_claims"][0]
                label = str(claim.get("dimension_value") or "")
                answer_text = f"经验证，{label}{claim['metric']}为 {claim['value']}。"
            else:
                answer_text = "这是安全的通用回答，不包含业务数据结论。"
        else:
            case = complex_by_question[question]
            assert payload["route"] == case["route"]
            state["complex_chat_payloads"].append(payload)
            route = case["route"]
            has_sql = True
            invocation_count = 1
            semantic = "VALUE"
            steps = [
                {
                    "ordinal": step["ordinal"],
                    "agent_role": step["role"],
                    "tool_name": step["tool"],
                    "status": "SUCCEEDED",
                    "duration_ms": 10,
                }
                for step in case["steps"]
            ]
            tools = [str(step["tool"]) for step in case["steps"] if step.get("tool")]
            primary = {
                "steps": steps,
                "verification": {
                    "result_verified": True,
                    "citation_verified": case["kind"] == "DATA_RAG",
                },
                "oracle": {"status": "PASSED"},
                "result_signature": "phase5-complex-result",
                "performance": {"total_latency_ms": 100},
                "result_evidence": {
                    "metrics": case["expected"]["expected_evidence"]["result"]["required_metrics"],
                    "dimensions": case["expected"]["expected_evidence"]["result"]["required_dimensions"],
                    "row_count": case["expected"]["expected_evidence"]["result"]["minimum_row_count"],
                    "rows": case["expected"]["expected_evidence"]["result"]["expected_rows"],
                },
                "answer_claims": case["expected"]["expected_evidence"]["result"]["expected_answer_claims"],
            }
            if case["kind"] == "DATA_RAG":
                primary["citation_id"] = "phase5-citation"
                citation_contract = case["expected"]["expected_evidence"]["citation"]["expected_citations"][0]
                primary["citations"] = [{
                    "citation_id": "phase5-citation",
                    "document_id": "document-phase5",
                    "document_version_id": "version-phase5",
                    "chunk_id": "chunk-phase5",
                    "title": citation_contract["title"],
                    "text": "收入（营收、销售额）按已确认且有效订单的 revenue 求和；取消订单不计入，退款按实际冲减金额扣除。数据结果必须经过 SQL Guard 与 Result Oracle 后发布。",
                    "source": citation_contract["source"],
                    "locator": citation_contract["locator"],
                }]
            if case["kind"] == "AGENT_PYTHON":
                primary["sandbox_evidence"] = {
                    "status": "SUCCEEDED",
                    "runtime_verified": True,
                    "container_destroyed": True,
                    "operation": "correlation",
                    "result": {"correlation": 1.0, "sample_size": 2},
                }
            if case["kind"] == "FILE_DB":
                primary["file_evidence"] = {
                    key: value
                    for key, value in case["expected"]["expected_evidence"]["file"].items()
                    if key != "required"
                }
            claim = case["expected"]["expected_evidence"]["result"]["expected_answer_claims"][0]
            label = str(claim.get("dimension_value") or "")
            answer_text = f"经验证，{label}{claim['metric']}为 {claim['value']}。"
            if case["kind"] == "DATA_RAG":
                answer_text += " 收入（营收、销售额）按已确认且有效订单的 revenue 求和。"
        state["conversation_request"][conversation_id] = {
            "request_id": request_id,
            "invocation_count": invocation_count,
            "status": "SUCCEEDED",
        }
        state["traces"][trace_id] = {
            "has_sql": has_sql, "tools": tools, "route": route, "status": "SUCCEEDED"
        }
        body = {
            "conversation": {"id": conversation_id},
            "user_message": {"id": f"user-{request_id}"},
            "assistant_message": {
                "id": f"assistant-{request_id}",
                "route": route,
                "status": "SUCCEEDED",
                "content": answer_text,
                "trace_payload": {"trace_id": trace_id},
                "response_payload": {"analysis": {"primary": primary}},
            },
            "message_parts": [],
            "result_semantic": semantic,
            "answer_envelope": {
                "trace_id": trace_id,
                "route": route,
                "verification": {"status": "VERIFIED" if has_sql else "NOT_APPLICABLE"},
            },
        }
        return httpx.Response(201, json=body)

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/api/v1")
        if path == "/auth/login":
            payload = json.loads(request.content)
            assert payload["password"] == "external-test-only"
            return httpx.Response(200, json={
                "authenticated": True,
                "user": {"id": "user-phase5", "workspace_id": "workspace-phase5"},
            })
        if path == "/auth/logout":
            return httpx.Response(204)
        if path == "/conversations" and request.method == "POST":
            state["conversation_count"] += 1
            conversation_id = f"conversation-{state['conversation_count']}"
            state["active_conversations"].add(conversation_id)
            return httpx.Response(201, json={"id": conversation_id})
        if path.startswith("/conversations/"):
            conversation_id = path.rsplit("/", 1)[-1]
            if request.method == "DELETE":
                state["active_conversations"].discard(conversation_id)
                return httpx.Response(204)
            if conversation_id in state["active_conversations"]:
                return httpx.Response(200, json={
                    "id": conversation_id,
                    "messages": [],
                    "active_attachment_ids": [],
                })
            return httpx.Response(404, json={})
        if path == "/attachments" and request.method == "POST":
            state["attachment_count"] += 1
            attachment_id = f"attachment-{state['attachment_count']}"
            state["active_attachments"].add(attachment_id)
            return httpx.Response(201, json={"id": attachment_id})
        if path.startswith("/attachments/"):
            attachment_id = path.rsplit("/", 1)[-1]
            if request.method == "DELETE":
                state["active_attachments"].discard(attachment_id)
                return httpx.Response(204)
            return httpx.Response(200 if attachment_id in state["active_attachments"] else 404, json={})
        if path == "/chat" and request.method == "POST":
            return response_for_chat(json.loads(request.content))
        if path == "/chat/stream" and request.method == "POST":
            payload = json.loads(request.content)
            trace_id = f"TRACE-{payload['client_message_id']}"
            state["conversation_request"][payload["conversation_id"]] = {
                "request_id": payload["client_message_id"],
                "invocation_count": 1,
                "status": "CANCELLED",
            }
            state["traces"][trace_id] = {
                "has_sql": False,
                "tools": [],
                "route": payload["route"],
                "status": "CANCELLED",
            }
            body = _sse(
                {
                    "event_type": "run.started",
                    "trace_id": trace_id,
                    "request_id": payload["client_message_id"],
                },
                {
                    "event_type": "run.cancelled",
                    "trace_id": trace_id,
                    "request_id": payload["client_message_id"],
                },
            )
            return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})
        if path == "/chat/stream/cancel" and request.method == "POST":
            state["cancel_count"] += 1
            return httpx.Response(202, json={"cancelled": True})
        if path == "/chat/stream/diagnostics":
            return httpx.Response(200, json={
                "active_connections": 0,
                "active_tasks": 0,
                "active_agent_tasks": 0,
                "active_sandbox_tasks": 0,
                "trace_ids": [],
            })
        if path == "/diagnostics":
            return httpx.Response(200, json={
                "status": "OK",
                "registered_jobs": 0,
                "running_jobs": 0,
                "completed_jobs": 0,
                "worker_containers": 0,
            })
        if path == "/governance/cost":
            conversation_id = request.url.params["conversation_id"]
            record = state["conversation_request"][conversation_id]
            entries = [
                {
                    "request_id": record["request_id"],
                    "conversation_id": conversation_id,
                    "cost_cny": 0.001,
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "retry_count": 0,
                    "fallback_count": 0,
                    "status": record["status"],
                    "provider": "mimo",
                }
                for _ in range(record["invocation_count"])
            ]
            return httpx.Response(200, json={
                "coverage": {"source": "MODEL_INVOCATION_LEDGER", "complete": True},
                "entries": entries,
            })
        if path.startswith("/governance/traces/"):
            trace_id = path.rsplit("/", 1)[-1]
            trace = state["traces"][trace_id]
            return httpx.Response(200, json={
                "coverage": {"source": "TRACE"},
                "trace": {
                    "trace_id": trace_id,
                    "status": trace["status"],
                    "duration_ms": 100,
                    "stage_count": 2,
                    "tools": trace["tools"],
                    "has_sql": trace["has_sql"],
                    "has_rag": trace["route"] in {"KNOWLEDGE_QUERY", "HYBRID_ANALYSIS"},
                    "has_agent": trace["route"] == "COMPLEX_ANALYSIS",
                    "has_file": False,
                    "has_vision": False,
                },
                "stages": [
                    {"stage": "UNDERSTANDING"},
                    *(({"stage": "QUERYING_DATA"},) if trace["has_sql"] else ()),
                ],
            })
        raise AssertionError(f"unexpected request: {request.method} {path}")

    with httpx.Client(
        transport=httpx.MockTransport(handler),
        base_url="http://127.0.0.1:8000/api/v1",
    ) as client:
        evidence = run_live_gate(
            client=client,
            weird_manifest=weird,
            complex_manifest=complex_manifest,
            datasource_id="datasource-phase5",
            semantic_model_id="semantic-phase5",
            credentials={"email": "phase5@example.invalid", "password": "external-test-only"},
            controller_client=client,
        )

    assert evidence["status"] == "PASS", evidence["failures"]
    assert evidence["certification_scope"] == "FULL_FINAL"
    assert len(evidence["selected_weird_case_ids"]) == 50
    assert len(evidence["selected_complex_case_ids"]) == 5
    assert evidence["weird_50"]["executed"] == evidence["weird_50"]["passed"] == 50
    assert evidence["weird_50"]["automatic_route_count"] == 50
    assert evidence["complex_5"]["executed"] == evidence["complex_5"]["passed"] == 5
    assert evidence["complex_5"]["cancel_passed"] == 5
    assert all(
        item["cancel"]["stream_eof_observed"]
        and item["cancel"]["terminal_count"] == 1
        and item["cancel"]["post_terminal_event_count"] == 0
        and item["cancel"]["ledger"]["statuses"] == ["CANCELLED"]
        and item["cancel"]["conversation_state"]["matching_cancelled_message_count"] == 0
        and item["cancel"]["conversation_state"]["stale_succeeded_assistant_count"] == 0
        and item["cancel"]["stream_diagnostics"]["trace_released"] is True
        for item in evidence["complex_5"]["cases"]
    )
    assert state["cancel_count"] == 5
    assert all("route" not in payload for payload in state["weird_chat_payloads"])
    assert all("route" in payload for payload in state["complex_chat_payloads"])
    assert state["active_conversations"] == set()
    assert state["active_attachments"] == set()
    assert evidence["cleanup"] == {
        "attachment_delete_204": 2,
        "attachment_absence_404": 2,
        "conversation_delete_204": 60,
        "conversation_absence_404": 60,
        "logout_204": 1,
        "expected_attachments": 2,
        "expected_conversations": 60,
        "failures": [],
        "verified": True,
    }
    assert "external-test-only" not in json.dumps(evidence, ensure_ascii=False)
    assert evidence["tested_sha"] is None or len(evidence["tested_sha"]) == 40
