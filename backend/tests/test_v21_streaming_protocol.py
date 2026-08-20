import json
from threading import Thread
from time import sleep

import pytest

from app.schemas.chat import ResultSemantic
from app.services.answer_composer import AnswerComposer, classify_result_semantic
from app.streaming import (
    REQUIRED_EVENTS,
    StreamCancelled,
    StreamEventFactory,
    format_sse,
    phase_for_stage,
    stream_registry,
)


def test_stream_protocol_declares_only_canonical_events():
    assert set(REQUIRED_EVENTS) == {
        "run.started", "phase.started", "phase.completed", "answer.delta",
        "artifact.ready", "citations.ready", "run.completed", "run.failed", "run.cancelled",
    }


def test_stream_event_envelope_is_monotonic_stable_and_terminal_is_last():
    factory = StreamEventFactory(
        run_id="STREAM-test-trace",
        conversation_id="conversation-1",
        message_id="pending-client-message-1",
    )
    started = factory.create("run.started", status="RUNNING")
    phase = factory.create("phase.started", phase="understanding")
    delta = factory.create("answer.delta", delta="真实回答")
    terminal = factory.create(
        "run.completed", status="SUCCEEDED", result_semantic="VALUE",
        message_parts=[], response={},
    )
    assert [item["seq"] for item in (started, phase, delta, terminal)] == [1, 2, 3, 4]
    for item in (started, phase, delta, terminal):
        assert item["run_id"] == "STREAM-test-trace"
        assert item["conversation_id"] == "conversation-1"
        assert item["message_id"] == "pending-client-message-1"
        assert {"seq", "run_id", "conversation_id", "message_id", "timestamp", "event_type"} <= set(item)
        assert "reasoning" not in json.dumps(item).lower()
    assert phase["label"] == "正在理解问题……"
    with pytest.raises(RuntimeError):
        factory.create("answer.delta", delta="terminal 后禁止事件")


def test_stream_factory_requires_started_valid_delta_and_matching_sse_name():
    factory = StreamEventFactory("STREAM-test", "conversation", "pending-message")
    with pytest.raises(RuntimeError):
        factory.create("answer.delta", delta="too early")
    started = factory.create("run.started")
    with pytest.raises(ValueError):
        factory.create("answer.delta", delta="")
    with pytest.raises(ValueError):
        format_sse("answer.delta", started)
    rendered = format_sse("run.started", started)
    assert rendered.startswith("event: run.started\ndata: ") and rendered.endswith("\n\n")


@pytest.mark.parametrize(
    ("stage", "phase"),
    [
        ("UNDERSTANDING", "understanding"),
        ("SCHEMA_LINKED", "semantic_mapping"),
        ("SEMANTIC_PARSING", "semantic_mapping"),
        ("QUERYING_DATA", "querying_data"),
        ("VERIFYING", "verifying"),
        ("RETRIEVING_KNOWLEDGE", "retrieving_knowledge"),
        ("PYTHON_RUNNING", "querying_data"),
        ("GENERATING_INSIGHT", "composing_answer"),
    ],
)
def test_private_stages_map_to_six_public_phases(stage, phase):
    assert phase_for_stage(stage) == phase


def test_unknown_or_private_stage_and_event_are_not_exposed():
    assert phase_for_stage("CHAIN_OF_THOUGHT") is None
    factory = StreamEventFactory("STREAM-test", "conversation", "message")
    with pytest.raises(ValueError):
        factory.create("private.reasoning")


def _query_payload(value, *, rows=None, row_count=None, status="SUCCEEDED"):
    rows = [{"revenue": value}] if rows is None else rows
    return {
        "analysis": {
            "status": status,
            "primary": {
                "status": status,
                "plan": {"metrics": ["revenue"], "dimensions": []},
                "guard": {"allowed": status == "SUCCEEDED", "normalized_sql": "SELECT revenue FROM orders"},
                "execution": {
                    "status": status,
                    "columns": ["revenue"],
                    "rows": rows,
                    "row_count": len(rows) if row_count is None else row_count,
                    "result_signature": "signature-1",
                },
                "oracle": {"status": "PASSED" if status == "SUCCEEDED" else "NOT_RUN"},
                "chart_spec": {"data_source_query_id": "query-1", "result_signature": "signature-1"},
                "kpis": [{"label": "revenue", "value": value, "unit": "元"}],
                "recommended_questions": ["按地区拆分看看？"],
            },
        },
    }


@pytest.mark.parametrize(
    ("status", "payload", "expected"),
    [
        ("SUCCEEDED", _query_payload(12), ResultSemantic.VALUE),
        ("SUCCEEDED", _query_payload(0), ResultSemantic.ZERO),
        ("SUCCEEDED", _query_payload(None, rows=[], row_count=0), ResultSemantic.NO_ROWS),
        ("SUCCEEDED", _query_payload(None), ResultSemantic.NULL_VALUE),
        ("FAILED", _query_payload(12, status="FAILED"), ResultSemantic.FAILED),
    ],
)
def test_result_semantic_has_five_distinct_states(status, payload, expected):
    assert classify_result_semantic(status, payload) is expected


def test_zero_is_preserved_as_value_and_never_rendered_as_no_data():
    composed = AnswerComposer().compose(
        answer="查询完成，revenue 为 0。",
        status="SUCCEEDED",
        response_payload=_query_payload(0),
        phases=["querying_data", "verifying", "composing_answer"],
    )
    assert composed.result_semantic is ResultSemantic.ZERO
    assert composed.content == "当前条件下结果为 0。"
    assert next(part for part in composed.message_parts if part["type"] == "kpi")["items"][0]["value"] == 0
    assert "没有匹配" not in composed.content


def test_answer_composer_chunks_are_lossless_and_parts_follow_business_order():
    answer = "华东区域本期销售额为 120 万元。较上期增长 8%，结果已通过查询校验。建议继续按客户查看贡献。"
    composed = AnswerComposer().compose(
        answer=answer,
        status="SUCCEEDED",
        response_payload=_query_payload(1),
        phases=["understanding", "semantic_mapping", "querying_data", "verifying", "composing_answer"],
    )
    deltas = list(composed.deltas())
    assert len(deltas) >= 2
    assert "".join(deltas) == composed.content == answer
    part_types = [part["type"] for part in composed.message_parts]
    assert part_types[:3] == ["text", "kpi", "chart"]
    assert part_types[-1] == "evidence"
    evidence = composed.message_parts[-1]
    assert evidence["phases"] == [
        {"phase": phase, "label": label}
        for phase, label in (
            ("understanding", "正在理解问题……"),
            ("semantic_mapping", "正在识别指标和维度……"),
            ("querying_data", "正在查询数据……"),
            ("verifying", "正在校验结果……"),
            ("composing_answer", "正在整理回答……"),
        )
    ]


def test_citations_require_real_controlled_identity_and_file_chart_is_not_misrepresented():
    file_payload = {
        "answer": "收入合计为 10。",
        "citations": [
            {"attachment_id": "attachment-1", "filename": "sales.csv", "kind": "STRUCTURED"},
            {"filename": "missing-id.csv"},
        ],
        "file_analysis": {
            "status": "SUCCEEDED",
            "result": {
                "columns": ["sum"], "rows": [{"sum": 10}],
                "result_signature": "file-signature",
            },
            "chart": {"chart_type": "bar", "x": "region", "y": "revenue", "rows": []},
        },
    }
    composed = AnswerComposer().compose(
        answer=file_payload["answer"], status="SUCCEEDED", response_payload=file_payload,
    )
    assert all(item.get("type") != "chart" for item in composed.message_parts)
    table = next(item for item in composed.message_parts if item["type"] == "table")
    assert table["result_signature"] == "file-signature"
    assert composed.citations == [{
        "title": "sales.csv",
        "version": "attachment-1",
        "locator": "attachment-1",
        "resource_id": "attachment-1",
    }]


def test_large_table_part_is_previewed_without_truncating_execution_or_row_count():
    rows = [
        {f"column_{column}": f"row-{index}-" + "x" * 100 for column in range(10)}
        for index in range(500)
    ]
    payload = _query_payload("value")
    primary = payload["analysis"]["primary"]
    primary["plan"] = {"metrics": ["column_0"], "dimensions": ["column_1"]}
    primary["execution"] = {
        "status": "SUCCEEDED",
        "columns": list(rows[0]),
        "rows": rows,
        "row_count": 500,
        "result_signature": "large-result-signature",
    }
    primary["chart_spec"] = {}
    primary["kpis"] = []

    composed = AnswerComposer().compose(
        answer="查询返回 500 行。", status="SUCCEEDED", response_payload=payload,
    )
    table = next(item for item in composed.message_parts if item["type"] == "table")
    assert len(table["rows"]) == 20
    assert table["row_count"] == 500
    assert table["result_signature"] == "large-result-signature"
    assert len(primary["execution"]["rows"]) == 500

    unbounded_table = {**table, "rows": rows}
    compact_bytes = len(json.dumps(table, ensure_ascii=False).encode("utf-8"))
    unbounded_bytes = len(json.dumps(unbounded_table, ensure_ascii=False).encode("utf-8"))
    assert compact_bytes < unbounded_bytes * 0.1


def test_stream_lifecycle_prunes_connection_and_task_after_cancel():
    trace_id = "STREAM-lifecycle-test"
    lifecycle = stream_registry.register(trace_id)
    stream_registry.task_started(trace_id)
    observed: list[str] = []

    def worker() -> None:
        while True:
            try:
                lifecycle.checkpoint()
            except StreamCancelled:
                observed.append("cancelled")
                break
            sleep(0.005)
        stream_registry.task_finished(trace_id)

    thread = Thread(target=worker)
    thread.start()
    stream_registry.connection_closed(trace_id)
    thread.join(timeout=1)
    assert observed == ["cancelled"]
    snapshot = stream_registry.snapshot()
    assert snapshot["active_connections"] == snapshot["active_tasks"] == 0
    assert snapshot["trace_ids"] == []


def test_stream_lifecycle_can_cancel_the_exact_conversation_run():
    trace_id = "STREAM-explicit-cancel"
    lifecycle = stream_registry.register(
        trace_id,
        conversation_id="conversation-1",
        client_message_id="client-message-1",
    )
    try:
        assert not stream_registry.cancel_matching(
            conversation_id="conversation-2",
            client_message_id="client-message-1",
        )
        assert stream_registry.cancel_matching(
            conversation_id="conversation-1",
            client_message_id="client-message-1",
        )
        assert lifecycle.cancel_event.is_set()
    finally:
        stream_registry.connection_closed(trace_id)


def test_workload_diagnostics_track_agent_and_sandbox_without_leaks():
    before = stream_registry.snapshot()
    with stream_registry.workload("agent"):
        assert stream_registry.snapshot()["active_agent_tasks"] == 1
    with stream_registry.workload("sandbox"):
        assert stream_registry.snapshot()["active_sandbox_tasks"] == 1
    after = stream_registry.snapshot()
    assert after["active_agent_tasks"] == after["active_sandbox_tasks"] == 0
    assert after["total_agent_tasks"] == before["total_agent_tasks"] + 1
    assert after["total_sandbox_tasks"] == before["total_sandbox_tasks"] + 1
