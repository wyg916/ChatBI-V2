from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]
ADAPTER_SRC = ROOT / "packages" / "dbgpt-runtime-adapter" / "src"
AGENT_CONTRACTS_SRC = ROOT / "packages" / "agent-contracts" / "src"
AGENT_ORCHESTRATOR_SRC = ROOT / "packages" / "agent-orchestrator" / "src"
sys.path.insert(0, str(ADAPTER_SRC))
sys.path.insert(0, str(AGENT_CONTRACTS_SRC))
sys.path.insert(0, str(AGENT_ORCHESTRATOR_SRC))

from chatbi_dbgpt_runtime import (  # noqa: E402
    DbgptAwelRuntime,
    DbgptRuntimeCancelled,
    DbgptRuntimePolicyError,
    DbgptRuntimeProvenanceError,
    DbgptRuntimeTimeout,
    DbgptRuntimeUnavailable,
    RuntimeRequest,
    preload_selected_runtime,
    UPSTREAM_ARCHIVE_SHA256,
    UPSTREAM_ARCHIVE_URL,
    UPSTREAM_REVISION,
)
from chatbi_dbgpt_runtime import runtime as runtime_module  # noqa: E402
from chatbi_agent_contracts import (  # noqa: E402
    AgentExecutionContext,
    OrchestrationRequest,
    QuestionRoute,
    ToolName,
    ToolResult,
)
from chatbi_agent_orchestrator import DbgptSelectedRuntimeOrchestrator  # noqa: E402


class FakeDAG:
    created: list[str] = []

    def __init__(self, dag_id: str) -> None:
        self.dag_id = dag_id
        self.created.append(dag_id)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeMapOperator:
    calls: list[dict[str, object]] = []

    def __init__(self, *, map_function, task_id: str) -> None:
        self.map_function = map_function
        self.task_id = task_id

    async def call(self, payload):
        self.calls.append(dict(payload))
        return await self.map_function(payload)


def selected_loader():
    return SimpleNamespace(
        dag_type=FakeDAG,
        map_operator_type=FakeMapOperator,
        package_version="0.8.1",
        revision=UPSTREAM_REVISION,
        install_source="git",
    )


@pytest.fixture(autouse=True)
def reset_fakes():
    FakeDAG.created.clear()
    FakeMapOperator.calls.clear()


def request(**overrides):
    values = {
        "question": "SELECT secret_value FROM internal_table",
        "route": "COMPLEX_ANALYSIS",
        "trace_id": "trace-001",
        "max_steps": 5,
        "max_tool_calls": 6,
    }
    values.update(overrides)
    return RuntimeRequest(**values)


def test_awel_call_invokes_chatbi_callback_and_reports_selected_runtime():
    runtime = DbgptAwelRuntime(loader=selected_loader)
    callback_calls = []

    def callback(control):
        control.checkpoint()
        callback_calls.append(control)
        return {"verified_answer": 42, "raw_sql": "kept inside ChatBI"}

    result = runtime.run(request(), callback)

    assert result.output["verified_answer"] == 42
    assert result.upstream_revision == UPSTREAM_REVISION
    assert result.runtime_calls == 1
    assert result.total_runtime_calls == 1
    assert callback_calls
    assert FakeDAG.created == ["chatbi-controlled-trace-001"]
    assert FakeMapOperator.calls == [
        {
            "route": "COMPLEX_ANALYSIS",
            "trace_id": "trace-001",
            "max_steps": 5,
            "max_tool_calls": 6,
        }
    ]
    assert "question" not in FakeMapOperator.calls[0]
    assert "raw_sql" not in str(FakeMapOperator.calls[0]).lower()
    assert result.awel_acknowledgement == {
        "trace_id": "trace-001",
        "route": "COMPLEX_ANALYSIS",
        "callback_status": "COMPLETED",
    }
    assert result.trace_stages[-1] == "agent.runtime.completed"


def test_preload_selected_runtime_validates_and_returns_public_provenance(monkeypatch):
    monkeypatch.setattr(runtime_module, "_load_selected_runtime", selected_loader)

    result = preload_selected_runtime()

    assert result == {
        "revision": UPSTREAM_REVISION,
        "package_version": "0.8.1",
        "install_source": "git",
    }


def test_runtime_counter_records_each_real_base_operator_call():
    runtime = DbgptAwelRuntime(loader=selected_loader)
    first = runtime.run(request(trace_id="trace-1"), lambda control: 1)
    second = runtime.run(request(trace_id="trace-2"), lambda control: 2)
    assert first.total_runtime_calls == 1
    assert second.total_runtime_calls == 2
    assert len(FakeMapOperator.calls) == 2


def test_callback_result_is_not_put_back_into_awel_state():
    runtime = DbgptAwelRuntime(loader=selected_loader)
    result = runtime.run(
        request(),
        lambda control: {"api_key": "must-not-leak", "connector": object()},
    )
    assert "api_key" not in str(result.awel_acknowledgement).lower()
    assert "connector" not in str(result.awel_acknowledgement).lower()


@pytest.mark.parametrize("route", ["DATA_QUERY", "KNOWLEDGE_QUERY", "GENERAL_AGENT"])
def test_unselected_route_is_refused_before_loader(route):
    called = False

    def loader():
        nonlocal called
        called = True
        return selected_loader()

    with pytest.raises(DbgptRuntimePolicyError):
        DbgptAwelRuntime(loader=loader).run(request(route=route), lambda control: None)
    assert not called


@pytest.mark.parametrize(
    ("field", "value"),
    [("max_steps", 9), ("max_tool_calls", 13), ("trace_id", "bad trace/id")],
)
def test_invalid_budget_or_trace_is_refused(field, value):
    with pytest.raises(DbgptRuntimePolicyError):
        DbgptAwelRuntime(loader=selected_loader).run(
            request(**{field: value}), lambda control: None
        )
    assert not FakeMapOperator.calls


def test_missing_dependency_fails_closed_without_callback():
    callback_called = False

    def unavailable():
        raise DbgptRuntimeUnavailable("missing")

    def callback(control):
        nonlocal callback_called
        callback_called = True

    runtime = DbgptAwelRuntime(loader=unavailable)
    with pytest.raises(DbgptRuntimeUnavailable):
        runtime.run(request(), callback)
    assert runtime.total_runtime_calls == 0
    assert not callback_called


def test_wrong_revision_fails_closed_without_awel_call():
    def wrong_revision():
        loaded = selected_loader()
        loaded.revision = "0" * 40
        return loaded

    with pytest.raises(DbgptRuntimeProvenanceError):
        DbgptAwelRuntime(loader=wrong_revision).run(request(), lambda control: None)
    assert not FakeMapOperator.calls


def test_git_direct_url_provenance_requires_both_exact_revisions():
    direct_url = {
        "url": "https://github.com/eosphoros-ai/DB-GPT.git",
        "vcs_info": {
            "vcs": "git",
            "commit_id": UPSTREAM_REVISION,
            "requested_revision": UPSTREAM_REVISION,
        },
        "subdirectory": "packages/dbgpt-core",
    }
    assert runtime_module._validate_direct_url(direct_url) == (UPSTREAM_REVISION, "git")
    direct_url["vcs_info"]["commit_id"] = "0" * 40
    with pytest.raises(DbgptRuntimeProvenanceError):
        runtime_module._validate_direct_url(direct_url)


def test_verified_archive_provenance_accepts_exact_url_subdirectory_and_sha256():
    direct_url = {
        "url": UPSTREAM_ARCHIVE_URL,
        "subdirectory": "packages/dbgpt-core",
        "archive_info": {"hashes": {"sha256": UPSTREAM_ARCHIVE_SHA256}},
    }
    assert runtime_module._validate_direct_url(direct_url) == (
        UPSTREAM_REVISION,
        "verified-archive",
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("url", "https://github.com/eosphoros-ai/DB-GPT/archive/main.zip"),
        ("subdirectory", "packages/dbgpt-app"),
        ("sha256", "0" * 64),
    ],
)
def test_archive_provenance_rejects_wrong_url_subdirectory_or_sha(field, value):
    direct_url = {
        "url": UPSTREAM_ARCHIVE_URL,
        "subdirectory": "packages/dbgpt-core",
        "archive_info": {"hashes": {"sha256": UPSTREAM_ARCHIVE_SHA256}},
    }
    if field == "sha256":
        direct_url["archive_info"]["hashes"]["sha256"] = value
    else:
        direct_url[field] = value
    with pytest.raises(DbgptRuntimeProvenanceError):
        runtime_module._validate_direct_url(direct_url)


def test_cancellation_cancels_awel_call():
    cancellation = threading.Event()

    async def callback(control):
        cancellation.set()
        while True:
            await asyncio.sleep(0.001)
            control.checkpoint()

    with pytest.raises(DbgptRuntimeCancelled):
        DbgptAwelRuntime(loader=selected_loader).run(
            request(), callback, cancellation_event=cancellation
        )


def test_deadline_cancels_awel_call():
    async def callback(control):
        await asyncio.sleep(1)

    with pytest.raises(DbgptRuntimeTimeout):
        DbgptAwelRuntime(loader=selected_loader).run(
            request(), callback, timeout_seconds=0.02
        )


def test_sync_run_refuses_nested_event_loop():
    async def invoke():
        with pytest.raises(DbgptRuntimePolicyError):
            DbgptAwelRuntime(loader=selected_loader).run(
                request(), lambda control: None
            )

    asyncio.run(invoke())


def test_callable_returning_awaitable_is_supported():
    class Callback:
        def __call__(self, control):
            async def complete():
                return "awaited"

            return complete()

    result = DbgptAwelRuntime(loader=selected_loader).run(request(), Callback())
    assert result.output == "awaited"


class SuccessfulToolExecutor:
    def __init__(self) -> None:
        self.calls = []

    def execute(self, call, context):
        self.calls.append(call)
        outputs = {
            ToolName.QUERY_DATA.value: {"rows": [{"value": 7}]},
            ToolName.RETRIEVE_KNOWLEDGE.value: {"citations": [{"id": "c1"}]},
            ToolName.VERIFY_RESULT.value: {"verified": True},
            ToolName.VERIFY_CITATION.value: {"verified": True},
            ToolName.GENERATE_CHART.value: {"chart": {"type": "bar"}},
            ToolName.GENERATE_INSIGHT.value: {"answer": "verified answer"},
        }
        return ToolResult(
            tool_name=call.tool_name,
            status="SUCCEEDED",
            output=outputs[call.tool_name],
        )


def orchestration_request():
    tools = frozenset(tool.value for tool in ToolName)
    return OrchestrationRequest(
        question="Analyse verified revenue with controlled knowledge",
        route=QuestionRoute.COMPLEX_ANALYSIS,
        context=AgentExecutionContext(
            workspace_id="workspace-1",
            user_id="user-1",
            roles=frozenset({"analyst"}),
            allowed_datasources=frozenset({"datasource-1"}),
            allowed_semantic_models=frozenset({"semantic-1"}),
            allowed_tools=tools,
            trace_id="trace-bridge-001",
            timeout_ms=5_000,
            max_steps=8,
            max_tool_calls=12,
            max_replan=2,
            max_agent_depth=2,
            token_budget=4_096,
        ),
        datasource_id="datasource-1",
        semantic_model_id="semantic-1",
        include_knowledge=True,
        idempotency_key="idempotency-bridge-001",
        prompt_versions={"agent.planner": "v1"},
    )


def test_agent_orchestrator_formally_routes_through_selected_awel_runtime():
    executor = SuccessfulToolExecutor()
    runtime = DbgptAwelRuntime(loader=selected_loader)
    result = DbgptSelectedRuntimeOrchestrator(
        executor, runtime=runtime
    ).run(orchestration_request())
    assert result.status == "SUCCEEDED"
    assert result.answer == "verified answer"
    assert result.runtime_verified
    assert result.runtime_calls == 1
    assert result.upstream_revision == UPSTREAM_REVISION
    assert len(executor.calls) == 6
    assert len(FakeMapOperator.calls) == 1
    awel_payload = FakeMapOperator.calls[0]
    assert set(awel_payload) == {"route", "trace_id", "max_steps", "max_tool_calls"}
    assert "datasource-1" not in str(awel_payload)
    assert "semantic-1" not in str(awel_payload)
    assert "sql" not in str(awel_payload).lower()


def test_selected_runtime_loader_reuses_verified_immutable_runtime(monkeypatch):
    import chatbi_dbgpt_runtime.runtime as runtime_module

    calls = {"distribution": 0, "import": 0}

    class Distribution:
        version = runtime_module.UPSTREAM_PACKAGE_VERSION

        @staticmethod
        def read_text(name):
            assert name == "direct_url.json"
            return json.dumps({
                "url": runtime_module.UPSTREAM_ARCHIVE_URL,
                "subdirectory": "packages/dbgpt-core",
                "archive_info": {
                    "hashes": {"sha256": runtime_module.UPSTREAM_ARCHIVE_SHA256}
                },
            })

    class Awel:
        DAG = type("DAG", (), {})
        MapOperator = type("MapOperator", (), {})

    def distribution(name):
        assert name == "dbgpt"
        calls["distribution"] += 1
        return Distribution()

    def load_module(name):
        assert name == "dbgpt.core.awel"
        calls["import"] += 1
        return Awel

    monkeypatch.setattr(runtime_module.metadata, "distribution", distribution)
    monkeypatch.setattr(runtime_module, "import_module", load_module)
    runtime_module._load_selected_runtime.cache_clear()
    try:
        first = runtime_module._load_selected_runtime()
        second = runtime_module._load_selected_runtime()
    finally:
        runtime_module._load_selected_runtime.cache_clear()

    assert first is second
    assert calls == {"distribution": 1, "import": 1}


def test_agent_orchestrator_missing_selected_runtime_returns_failed_not_fallback():
    def unavailable():
        raise DbgptRuntimeUnavailable("missing")

    result = DbgptSelectedRuntimeOrchestrator(
        SuccessfulToolExecutor(),
        runtime=DbgptAwelRuntime(loader=unavailable),
    ).run(orchestration_request())
    assert result.status == "FAILED"
    assert result.error_code == "DBGPT_RUNTIME_UNAVAILABLE"
    assert result.runtime_calls == 0
    assert not result.runtime_verified
    assert not result.fallback_used


@pytest.mark.skipif(
    os.getenv("CHATBI_TEST_REAL_DBGPT") != "1",
    reason="set CHATBI_TEST_REAL_DBGPT=1 with the exact pinned dependency installed",
)
def test_real_selected_dbgpt_awel_call():
    result = DbgptAwelRuntime().run(request(), lambda control: "real-awel")
    assert result.output == "real-awel"
    assert result.upstream_revision == UPSTREAM_REVISION
    assert result.upstream_package_version == "0.8.1"
    assert result.upstream_install_source in {"git", "verified-archive"}
    assert result.runtime_calls == 1
    assert "agent.runtime.dbgpt.awel.call" in result.trace_stages


@pytest.mark.skipif(
    os.getenv("CHATBI_TEST_REAL_DBGPT") != "1",
    reason="set CHATBI_TEST_REAL_DBGPT=1 with the exact pinned dependency installed",
)
def test_real_selected_dbgpt_agent_orchestrator_bridge():
    executor = SuccessfulToolExecutor()
    result = DbgptSelectedRuntimeOrchestrator(executor).run(orchestration_request())
    assert result.status == "SUCCEEDED"
    assert result.answer == "verified answer"
    assert result.runtime_verified
    assert result.runtime_calls == 1
    assert result.upstream_revision == UPSTREAM_REVISION
    assert result.upstream_install_source in {"git", "verified-archive"}
    assert len(executor.calls) == 6
    assert "agent.runtime.dbgpt.awel.call" in result.runtime_trace_stages


@pytest.mark.skipif(
    os.getenv("CHATBI_TEST_REAL_DBGPT") != "1",
    reason="set CHATBI_TEST_REAL_DBGPT=1 with the exact pinned dependency installed",
)
def test_real_selected_dbgpt_agent_golden_15():
    cases = json.loads(
        (ROOT / "evaluation" / "golden" / "v2.1-agent-15.json").read_text(encoding="utf-8")
    )["cases"]
    runtime = DbgptAwelRuntime()
    succeeded = 0
    for ordinal, case in enumerate(cases, start=1):
        executor = SuccessfulToolExecutor()
        base = orchestration_request()
        context = base.context.model_copy(
            update={"trace_id": f"trace-dbgpt-agent-{ordinal:02d}"}
        )
        selected = base.model_copy(
            update={
                "question": case["question"],
                "context": context,
                "idempotency_key": f"phase3-dbgpt-{case['id']}",
            }
        )
        result = DbgptSelectedRuntimeOrchestrator(
            executor, runtime=runtime
        ).run(selected)
        succeeded += int(result.status == "SUCCEEDED")
        assert result.runtime_verified is True
        assert result.runtime_calls == 1
        assert result.total_runtime_calls == ordinal
        assert result.trace_complete is True
        assert result.tool_call_count == 6
        assert len(executor.calls) == 6
    assert len(cases) == 15
    assert succeeded / len(cases) >= 0.90
    assert runtime.total_runtime_calls == 15
