from __future__ import annotations

import json
import sys
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
import scripts.performance.run_v13_phase5_api_load as api_load_module


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.performance.run_v13_phase5_api_load import (  # noqa: E402
    ApiSample,
    DEFAULT_CORE_DATA_MANIFEST,
    DEFAULT_API_DURATION_SECONDS,
    DEFAULT_API_USERS,
    EXPECTED_REVENUE_KNOWLEDGE_TEXT,
    EXPECTED_REVENUE_KNOWLEDGE_TITLE,
    RELEASE_THRESHOLDS,
    ResourceSample,
    UserRuntime,
    WORKLOAD_MIX,
    _independent_result_signature,
    _sse_observation,
    aggregate_scoped_cost_ledger,
    cleanup_user,
    deterministic_csv_bytes,
    deterministic_png_bytes,
    evaluate_api_gate,
    derive_credentials,
    execute_core_data_case,
    load_core_data_manifest,
    run_core_data100,
    select_load_data_case,
    summarize_api_load,
    validate_business_result,
    validate_backend_url,
    workload_kind,
    build_parser,
)


def test_backend_core_data100_manifest_reuses_day4_and_adds_50_diverse_cases() -> None:
    manifest, cases = load_core_data_manifest(DEFAULT_CORE_DATA_MANIFEST)

    assert manifest["suite"] == "CHATBI_V13_PHASE5_BACKEND_CORE_DATA_100"
    assert len(cases) == 100
    assert len({item["id"] for item in cases}) == 100
    assert len({item["question"].strip().casefold() for item in cases}) == 100
    assert {"month_over_month", "year_over_year", "tie_topn", "null", "empty_result"} <= {
        item["category"] for item in cases
    }
    assert {
        "boundary", "cross_month", "cross_year", "complex_filter", "multi_metric_dimension",
        "ambiguous", "wrong_field", "nonexistent_metric", "dangerous_sql", "extreme_value",
    } <= {item["category"] for item in cases}
    assert len(manifest["extension_cases"]) == 50
    selected, expected_value = select_load_data_case(cases, "G01")
    assert selected["expected_signature"] == "178d1b593bd923261abc1efd86c94975a01f6e169e3b45ba1de4ac86460f2172"
    assert expected_value == Decimal("1725750.0")


def test_core_data_case_calls_real_ask_and_verify_and_records_business_evidence() -> None:
    signature = _independent_result_signature(["revenue"], [{"revenue": 100.0}])
    case = {
        "id": "T1", "category": "simple_metric", "question": "统计收入",
        "expected_entities": ["orders"], "expected_metrics": ["revenue"],
        "expected_dimensions": [], "expected_filters": [], "expected_time_range": None,
        "expected_sql": "SELECT SUM(revenue) AS revenue FROM orders",
        "expected_result": [{"revenue": 100}], "expected_outcome": "SUCCEEDED_AND_VERIFIED",
    }
    actual = {
        "id": "query-1", "status": "SUCCEEDED", "error_code": None,
        "context": {
            "request_context": {"route": "DATA_QUERY"},
            "verification_query": {
                "required": True, "executed": True, "passed": True,
                "kind": "READ_ONLY_REPLAY", "query_sha256": "b" * 64,
            },
        },
        "plan": {
            "selected_entities": ["orders"], "metrics": ["revenue"], "dimensions": [],
            "filters": [], "time_range": None, "generated_sql": "SELECT SUM(revenue) AS revenue FROM orders",
        },
        "guard": {"allowed": True, "statement_type": "SELECT", "normalized_sql": "SELECT SUM(revenue) AS revenue FROM orders", "issues": []},
        "execution": {"status": "SUCCEEDED", "columns": ["revenue"], "rows": [{"revenue": 100.0}], "row_count": 1, "result_signature": signature},
        "oracle": {"status": "PASSED"},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/ask":
            return httpx.Response(201, json=actual)
        if request.url.path == "/api/v1/queries/query-1/verify":
            return httpx.Response(200, json={**actual, "oracle": {"status": "PASSED"}})
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://127.0.0.1:8000")
    result = execute_core_data_case(client, case, datasource_id="ds", semantic_model_id="sm")

    assert result["status"] == "PASS"
    assert result["actual_route"] == "DATA_QUERY"
    assert result["guard"]["allowed"] is True
    assert result["execution"]["result_signature"] == signature
    assert result["pipeline_verification_query"]["passed"] is True
    assert result["oracle_after_expected_verify"]["status"] == "PASSED"
    assert result["expected_actual_value_match"] is True
    client.close()


def _passing_core_data() -> dict:
    return {
        "status": "PASS", "total": 100, "passed": 100, "failed": 0,
        "sql_execution_rate": 1.0, "result_value_accuracy": 1.0,
        "dangerous_sql_block_rate": 1.0, "cases": [],
    }


def test_real_api_workload_mix_is_complete_and_vision_is_low_frequency() -> None:
    assert len(WORKLOAD_MIX) == 100
    assert {kind: WORKLOAD_MIX.count(kind) for kind in set(WORKLOAD_MIX)} == {
        "DATA": 35,
        "RAG": 15,
        "HYBRID": 15,
        "AGENT": 15,
        "FILE": 15,
        "VISION": 5,
    }
    scheduled = {
        workload_kind(user, sequence, 20)
        for user in range(20)
        for sequence in range(5)
    }
    assert scheduled == {"DATA", "RAG", "HYBRID", "AGENT", "FILE", "VISION"}
    assert WORKLOAD_MIX.count("VISION") / len(WORKLOAD_MIX) == 0.05


def test_api_load_defaults_remain_20_users_for_15_minutes(tmp_path: Path) -> None:
    args = build_parser().parse_args([
        "--metadata-schema", "phase5_metadata_test",
        "--workspace-id", "workspace",
        "--datasource-id", "datasource",
        "--semantic-model-id", "semantic-model",
        "--backend-pid", "1",
        "--output", str(tmp_path / "load.json"),
    ])
    assert args.users == DEFAULT_API_USERS == 20
    assert args.duration_seconds == DEFAULT_API_DURATION_SECONDS == 900


def test_fixtures_are_reproducible_real_csv_and_png() -> None:
    csv_one = deterministic_csv_bytes()
    png_one = deterministic_png_bytes()

    assert csv_one == deterministic_csv_bytes()
    assert png_one == deterministic_png_bytes()
    assert len(csv_one.decode("utf-8").splitlines()) == 121
    assert csv_one.startswith(b"month,region,revenue,cost\n")
    assert png_one.startswith(b"\x89PNG\r\n\x1a\n")
    assert png_one.endswith(b"IEND\xaeB`\x82")


def test_single_external_base_password_derives_20_distinct_non_persisted_credentials() -> None:
    credentials = derive_credentials(
        "test-only-base-password",
        request_prefix="phase5api-0123456789ab-",
        users=20,
    )

    assert len(credentials) == 20
    assert len({item.email for item in credentials}) == 20
    assert len({item.password for item in credentials}) == 20
    assert all("test-only-base-password" in item.password for item in credentials)
    with pytest.raises(ValueError, match="at least 10"):
        derive_credentials("short", request_prefix="phase5api-0123456789ab-", users=20)


@pytest.mark.parametrize(
    "url",
    ["http://127.0.0.1:8000", "http://localhost:8000/", "https://[::1]:8443"],
)
def test_backend_target_must_be_loopback(url: str) -> None:
    assert validate_backend_url(url).startswith(("http://", "https://"))


@pytest.mark.parametrize(
    "url",
    ["https://chatbi.example.invalid", "ftp://127.0.0.1/backend", "http://user:secret@127.0.0.1:8000"],
)
def test_backend_target_rejects_remote_non_http_or_embedded_credentials(url: str) -> None:
    with pytest.raises(ValueError):
        validate_backend_url(url)


def test_authenticated_load_client_never_uses_environment_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    observed: dict[str, object] = {}

    class FakeClient:
        def __init__(self, **kwargs: object) -> None:
            observed.update(kwargs)

        def post(self, *_args: object, **_kwargs: object) -> httpx.Response:
            return httpx.Response(502)

        def close(self) -> None:
            return None

    monkeypatch.setattr(api_load_module.httpx, "Client", FakeClient)
    credential = api_load_module.Credential(email="load@example.invalid", password="synthetic-password")
    with pytest.raises(RuntimeError, match="HTTP_502"):
        api_load_module.prepare_user(
            index=0,
            credential=credential,
            base_url="http://127.0.0.1:28080",
            workspace_id="workspace",
            csv_bytes=b"csv",
            png_bytes=b"png",
            timeout_seconds=10.0,
        )
    assert observed["trust_env"] is False


def test_sse_observation_uses_real_stream_contract_with_fake_transport_only_in_quick_test() -> None:
    signature = _independent_result_signature(["revenue"], [{"revenue": 1725750}])
    terminal = {
        "event_type": "run.completed",
        "response": {
            "assistant_message": {
                "route": "DATA_QUERY",
                "response_payload": {
                    "analysis": {
                        "route": "DATA_QUERY",
                        "status": "SUCCEEDED",
                        "primary": {
                            "status": "SUCCEEDED",
                            "guard": {"allowed": True, "normalized_sql": "SELECT SUM(revenue) FROM orders"},
                            "execution": {
                                "status": "SUCCEEDED",
                                "columns": ["revenue"],
                                "rows": [{"revenue": 1725750}],
                                "result_signature": signature,
                            },
                            "oracle": {"status": "PASSED"},
                        },
                    }
                },
            }
        },
    }
    body = (
        "event: run.started\n"
        "data: {\"event_type\":\"run.started\"}\n\n"
        "event: phase.started\n"
        "data: {\"event_type\":\"phase.started\"}\n\n"
        "event: answer.delta\n"
        "data: {\"event_type\":\"answer.delta\",\"delta\":\"完成\"}\n\n"
        "event: run.completed\n"
        f"data: {json.dumps(terminal)}\n\n"
    )
    client = httpx.Client(transport=httpx.MockTransport(
        lambda _request: httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})
    ), base_url="http://127.0.0.1:8000")
    ticks = iter([1.0, 1.01, 1.02, 1.03, 1.04, 1.05])

    sample = _sse_observation(
        client,
        path="/api/v1/analysis/stream",
        payload={"question": "test"},
        user_index=3,
        kind="DATA",
        expected_data_value=Decimal("1725750"),
        clock=lambda: next(ticks),
    )

    assert sample.status_code == 200
    assert sample.event_count == 4
    assert sample.terminal_event == "run.completed"
    assert sample.terminal_count == 1
    assert sample.ttfe_ms == 10.0
    assert sample.ttft_ms == 30.0
    assert sample.total_ms == 50.0
    assert sample.success is True
    assert sample.error_code is None
    assert sample.observed_route == "DATA_QUERY"
    assert sample.business_valid is True
    client.close()


def test_file_business_validation_reads_real_nested_result_contract() -> None:
    rows = [{"region": "华东", "revenue_sum": 1_000_000}, {"region": "华南", "revenue_sum": 1_194_620}]
    terminal = {
        "response": {"assistant_message": {
            "route": "FILE_QUERY",
            "response_payload": {"file_analysis": {
                "status": "SUCCEEDED",
                "result": {
                    "columns": ["region", "revenue_sum"],
                    "rows": rows,
                    "exact_for_full_file": True,
                    "result_signature": _independent_result_signature(["region", "revenue_sum"], rows),
                },
            }},
        }},
    }

    route, valid, failures = validate_business_result(
        "FILE", terminal, expected_data_value=Decimal("0"),
    )

    assert route == "FILE_QUERY"
    assert valid is True
    assert failures == ()


def test_rag_business_validation_recomputes_frozen_claim_entailment() -> None:
    citation = {
        "citation_id": "c1",
        "document_id": "document-1",
        "document_version_id": "version-1",
        "chunk_id": "chunk-1",
        "title": EXPECTED_REVENUE_KNOWLEDGE_TITLE,
        "text": EXPECTED_REVENUE_KNOWLEDGE_TEXT,
        "source": "ChatBI V1 Business Glossary",
        "locator": "business-glossary/revenue.md#definition",
    }
    primary = {
        "status": "SUCCEEDED",
        "summary": f"{EXPECTED_REVENUE_KNOWLEDGE_TEXT} [citation:c1]",
        "citations": [citation],
        "answer_guard": "PASSED",
        "answer_guard_evidence": {
            "status": "PASSED", "citation_accuracy": 1.0,
            "prompt_injection_evidence_used": 0, "factual_units": 1, "cited_ids": ["c1"],
        },
    }
    terminal = {"response": {"assistant_message": {"route": "KNOWLEDGE_QUERY", "response_payload": {
        "analysis": {"route": "KNOWLEDGE_QUERY", "status": "SUCCEEDED", "primary": primary}
    }}}}

    _route, valid, failures = validate_business_result("RAG", terminal, expected_data_value=Decimal(0))
    assert valid is True
    assert failures == ()

    primary["summary"] = "利润等于 999 元。 [citation:c1]"
    _route, valid, failures = validate_business_result("RAG", terminal, expected_data_value=Decimal(0))
    assert valid is False
    assert "KNOWLEDGE_CLAIM_NOT_ENTAILED_BY_FROZEN_CITATION" in failures


def test_agent_self_reported_verification_cannot_replace_frozen_data_and_knowledge() -> None:
    primary = {
        "status": "SUCCEEDED",
        "trace_complete": True,
        "tool_call_count": 6,
        "fallback_used": False,
        "verification": {"result_verified": True, "citation_verified": True},
        "answer": f"1725750.0，相关口径见《{EXPECTED_REVENUE_KNOWLEDGE_TITLE}》。",
        "steps": [
            {"agent_role": role, "tool_name": tool, "status": "SUCCEEDED"}
            for role, tool in (
                ("PlannerAgent", "QUERY_DATA"),
                ("DataAnalystAgent", "RETRIEVE_KNOWLEDGE"),
                ("KnowledgeAgent", "VERIFY_RESULT"),
                ("VerificationAgent", "VERIFY_CITATION"),
                ("InsightAgent", "GENERATE_CHART"),
                ("InsightAgent", "GENERATE_INSIGHT"),
            )
        ],
        "data_evidence": {},
        "knowledge_evidence": {},
    }
    terminal = {"response": {"assistant_message": {"route": "COMPLEX_ANALYSIS", "response_payload": {
        "analysis": {"route": "COMPLEX_ANALYSIS", "status": "SUCCEEDED", "primary": primary}
    }}}}

    _route, valid, failures = validate_business_result(
        "AGENT", terminal, expected_data_value=Decimal("1725750.0"), expected_data_signature="a" * 64,
    )
    assert valid is False
    assert "DATA_EXECUTION_NOT_PROVEN" in failures
    assert "FROZEN_REVENUE_KNOWLEDGE_CONTENT_NOT_PROVEN" in failures

    primary["answer"] += " 错误利润为 999999。"
    _route, valid, failures = validate_business_result(
        "AGENT", terminal, expected_data_value=Decimal("1725750.0"), expected_data_signature="a" * 64,
    )
    assert valid is False
    assert "AGENT_ANSWER_UNMATCHED_NUMERIC_CLAIM" in failures


def _passing_samples() -> list[ApiSample]:
    result = []
    routes = {
        "DATA": "DATA_QUERY", "RAG": "KNOWLEDGE_QUERY",
        "HYBRID": "HYBRID_ANALYSIS", "AGENT": "COMPLEX_ANALYSIS",
        "FILE": "FILE_QUERY", "VISION": "MULTIMODAL_QUERY",
    }
    for user in range(20):
        for sequence in range(5):
            kind = workload_kind(user, sequence, 20)
            result.append(ApiSample(
                user_index=user,
                kind=kind,
                ttfe_ms=100.0,
                ttft_ms=1_000.0,
                total_ms=2_000.0,
                status_code=200,
                event_count=5,
                terminal_event="run.completed",
                terminal_count=1,
                success=True,
                error_code=None,
                request_id=f"phase5api-0123456789ab-{user:02d}-{sequence:08d}",
                observed_route=routes[kind],
                business_valid=True,
                business_checks=(),
            ))
    return result


def _passing_resources() -> list[ResourceSample]:
    return [
        ResourceSample(None, 50.0, None, 512.0, 10, 2),
        ResourceSample(40.0, 51.0, 20.0, 520.0, 25, 20),
        ResourceSample(50.0, 52.0, 30.0, 530.0, 30, 18),
    ]


def _passing_cost() -> dict:
    return {
        "coverage": {
            "source": "MODEL_INVOCATION_LEDGER",
            "database_complete": True,
            "complete": True,
            "warnings": [],
            "scope": "EXACT_PREFIX_AND_LOAD_WINDOW",
            "expected_billable_requests": 85,
            "covered_billable_requests": 85,
            "missing_billable_requests": 0,
            "request_coverage": 1.0,
        },
        "invocations": 90,
        "token_bearing_invocations": 90,
        "providers": {"kimi": 9, "mimo": 81},
        "kimi_invocations": 9,
        "kimi_premium_share": 0.10,
        "actual_cost_cny": 1.0,
        "all_premium_cost_cny": 4.0,
        "saving_vs_all_premium": 0.75,
        "by_route": {
            "DATA_QUERY": {}, "KNOWLEDGE_QUERY": {}, "HYBRID_ANALYSIS": {},
            "COMPLEX_ANALYSIS": {}, "MULTIMODAL_QUERY": {},
        },
        "by_provider": {"mimo": {}, "kimi": {}},
    }


def _passing_cleanup() -> dict:
    return {
        "attachment_delete_204": 40,
        "attachment_absence_404": 40,
        "conversation_delete_204": 20,
        "conversation_absence_404": 20,
        "logout_204": 20,
        "fixture_directory_absent": True,
        "metadata_sessions_deleted": 20,
        "metadata_grants_deleted": 40,
        "metadata_users_deleted": 20,
        "metadata_conversations_before_delete": 0,
        "metadata_attachments_before_delete": 0,
        "metadata_messages_before_delete": 0,
        "metadata_model_invocations_removed": 90,
        "metadata_load_model_invocations_removed": 90,
        "metadata_query_runs_deleted": 100,
        "metadata_attachment_files_removed": 0,
        "metadata_absence_verified": True,
    }


def test_api_metrics_have_p50_p95_p99_for_every_route_and_resource() -> None:
    metrics = summarize_api_load(
        _passing_samples(),
        _passing_resources(),
        elapsed_seconds=10.0,
        configured_users=20,
    )

    assert metrics["active_users"] == 20
    assert metrics["success_rate"] == 1.0
    assert metrics["actual_elapsed_seconds"] == 10.0
    assert metrics["terminal_contract_violations"] == 0
    assert metrics["by_kind"]["VISION"]["requests"] == 5
    assert metrics["by_kind"]["DATA"]["requests"] == 35
    for kind in ("DATA", "RAG", "HYBRID", "AGENT", "FILE", "VISION"):
        assert set(metrics["by_kind"][kind]["ttfe_ms"]) == {"min", "p50", "p95", "p99", "max"}
        assert set(metrics["by_kind"][kind]["ttft_ms"]) == {"min", "p50", "p95", "p99", "max"}
        assert set(metrics["by_kind"][kind]["total_ms"]) == {"min", "p50", "p95", "p99", "max"}
    assert metrics["resources"]["host_cpu_percent"]["p99"] > 0
    assert metrics["resources"]["backend_rss_mib"]["p50"] == 520.0
    assert metrics["resources"]["db_connections"]["max"] == 30.0
    assert metrics["resources"]["complete_sample_count"] == 2


def test_cost_coverage_is_recomputed_after_exact_prefix_scope_with_route_provider_breakdown() -> None:
    observations = _passing_samples()
    billable = [item for item in observations if item.kind != "FILE"]
    route_map = {
        "DATA": "DATA_QUERY", "RAG": "KNOWLEDGE_QUERY",
        "HYBRID": "HYBRID_ANALYSIS", "AGENT": "COMPLEX_ANALYSIS",
        "VISION": "MULTIMODAL_QUERY",
    }
    entries = [
        {
            "request_id": sample.request_id,
            "provider": "kimi" if index < 8 else "mimo",
            "route": route_map[sample.kind],
            "input_tokens": 1_000,
            "cached_input_tokens": 0,
            "output_tokens": 200,
            "cost_cny": 0.001 if index >= 8 else 0.01,
        }
        for index, sample in enumerate(billable)
    ]
    entries.append({
        "request_id": "unrelated-request",
        "provider": "kimi",
        "route": "GENERAL_CHAT",
        "input_tokens": 99_999,
        "cached_input_tokens": 0,
        "output_tokens": 99_999,
        "cost_cny": 999.0,
    })

    result = aggregate_scoped_cost_ledger(
        entries,
        base_coverage={"source": "MODEL_INVOCATION_LEDGER", "complete": True, "warnings": []},
        observations=observations,
        request_prefix="phase5api-0123456789ab-",
        kimi_pricing={"cached_input": 1.1, "uncached_input": 6.5, "output": 27.0},
    )

    assert result["invocations"] == len(billable) == 85
    assert result["coverage"]["scope"] == "EXACT_PREFIX_AND_LOAD_WINDOW"
    assert result["coverage"]["expected_billable_requests"] == 85
    assert result["coverage"]["covered_billable_requests"] == 85
    assert result["coverage"]["missing_billable_requests"] == 0
    assert result["coverage"]["request_coverage"] == 1.0
    assert result["coverage"]["route_source"] == "VALIDATED_SSE_OBSERVED_ROUTE"
    assert set(result["by_route"]) == set(route_map.values())
    assert set(result["by_provider"]) == {"mimo", "kimi"}


def test_api_gate_requires_20x15m_all_six_routes_resources_real_ledger_and_cleanup() -> None:
    metrics = summarize_api_load(
        _passing_samples(),
        _passing_resources() * 300,
        elapsed_seconds=900.0,
        configured_users=20,
    )

    assert evaluate_api_gate(
        users=20,
        duration_seconds=900,
        metrics=metrics,
        core_data=_passing_core_data(),
        cost=_passing_cost(),
        cleanup=_passing_cleanup(),
        runtime_error=None,
    ) == []

    failed_cost = {**_passing_cost(), "kimi_premium_share": 0.11, "saving_vs_all_premium": 0.59}
    failed_metrics = {
        **metrics,
        "actual_elapsed_seconds": 898.0,
        "kind_coverage": ["DATA", "RAG", "HYBRID", "AGENT", "FILE"],
    }
    failures = evaluate_api_gate(
        users=19,
        duration_seconds=899,
        metrics=failed_metrics,
        core_data={**_passing_core_data(), "passed": 99, "status": "FAIL"},
        cost=failed_cost,
        cleanup={**_passing_cleanup(), "fixture_directory_absent": False},
        runtime_error=None,
    )
    assert {
        "authenticated_users_below_20",
        "duration_below_15_minutes",
        "api_mixed_route_coverage_incomplete",
        "kimi_premium_share_above_0_10",
        "saving_vs_all_premium_below_0_60",
        "fixture_directory_not_removed",
        "backend_core_data100_not_strict_100_of_100",
        "actual_api_load_duration_below_15_minutes",
    }.issubset(failures)
    assert RELEASE_THRESHOLDS["max_kimi_premium_share"] == 0.10
    assert RELEASE_THRESHOLDS["min_saving_vs_all_premium"] == 0.60


def test_cleanup_deletes_and_verifies_every_attachment_conversation_and_session() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth/logout"):
            return httpx.Response(204)
        if request.method == "DELETE":
            return httpx.Response(204)
        return httpx.Response(404)

    client = httpx.Client(
        transport=httpx.MockTransport(handler),
        base_url="http://127.0.0.1:8000",
    )
    runtime = UserRuntime(
        index=0,
        client=client,
        user_id="user-1",
        workspace_id="workspace-1",
        conversation_id="conversation-1",
        csv_attachment_id="attachment-csv",
        image_attachment_id="attachment-image",
    )

    assert cleanup_user(runtime) == {
        "attachment_delete_204": 2,
        "attachment_absence_404": 2,
        "conversation_delete_204": 1,
        "conversation_absence_404": 1,
        "logout_204": 1,
    }
