from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from app.schemas.answer_envelope import AnswerArtifact, AnswerEnvelope, AnswerRoute
from app.services.answer_envelope import AnswerEnvelopeAdapter


def _query_payload() -> dict:
    return {
        "id": "query-1",
        "status": "SUCCEEDED",
        "plan": {
            "metrics": ["revenue"],
            "warnings": ["指标按财务确认口径计算"],
            "recommended_questions": ["按客户查看收入"],
        },
        "guard": {"allowed": True, "normalized_sql": "SELECT region, SUM(revenue) AS revenue FROM sales GROUP BY region"},
        "execution": {
            "status": "SUCCEEDED",
            "columns": ["region", "revenue"],
            "rows": [{"region": "华东", "revenue": 270}],
            "row_count": 1,
            "result_signature": "result-signature-1",
        },
        "oracle": {"status": "PASSED"},
        "chart_spec": {
            "version": "1",
            "chart_type": "BAR",
            "title": "区域收入",
            "x_field": "region",
            "y_fields": ["revenue"],
            "series": [{"name": "收入", "field": "revenue", "type": "bar"}],
            "aggregation": {"revenue": "SUM"},
            "unit": {"revenue": "元"},
            "sort": [],
            "limit": 20,
            "legend": {"show": True, "formatter": "must-not-pass"},
            "axis": {"formatter": "must-not-pass"},
            "tooltip": {"formatter": "must-not-pass"},
            "data_source_query_id": "query-1",
            "result_signature": "result-signature-1",
            "bound_columns": ["region", "revenue"],
            "bound_row_count": 1,
            "null_policy": "PRESERVE",
            "warnings": [],
        },
        "kpis": [{"label": "收入", "value": 270, "unit": "元"}],
        "narrative": {"insights": ["华东贡献最高"], "recommended_questions": ["按客户查看收入"]},
        "recommended_questions": ["按客户查看收入"],
    }


def _parts() -> list[dict]:
    query = _query_payload()
    return [
        {"type": "text", "text": "华东收入为 **270 元**。", "role": "conclusion"},
        {"type": "kpi", "items": query["kpis"]},
        {"type": "chart", "chart_spec": query["chart_spec"], "result_signature": "result-signature-1"},
        {
            "type": "table",
            "columns": ["region", "revenue"],
            "rows": [{"region": "华东", "revenue": 270}],
            "row_count": 1,
            "result_signature": "result-signature-1",
        },
        {"type": "text", "text": "华东贡献最高", "role": "insights"},
        {"type": "text", "text": "按客户查看收入", "role": "followups"},
        {
            "type": "citations",
            "items": [{
                "title": "收入口径",
                "version": "v1",
                "locator": "第 2 节",
                "resource_id": "document-1",
                "url": "javascript:alert(1)",
            }],
        },
        {
            "type": "evidence",
            "sql": query["guard"]["normalized_sql"],
            "guard": query["guard"],
            "oracle": query["oracle"],
            "semantic": query["plan"],
            "phases": [],
        },
    ]


def _build(route: str, *, response_payload: dict, parts: list[dict] | None = None, attachment_ids: tuple[str, ...] = ()) -> AnswerEnvelope:
    return AnswerEnvelopeAdapter.build(
        answer_id=f"answer-{route}",
        conversation_id="conversation-1",
        message_id=f"message-{route}",
        trace_id=f"trace-{route}",
        route=route,
        status="SUCCEEDED",
        content="已完成受控分析。",
        response_payload=response_payload,
        trace_payload={
            "trace_id": f"trace-{route}",
            "elapsed_ms": 321,
            "model_provider": "mimo",
            "model_name": "mimo-v2.5",
            "model_call": {
                "usage": {"input_tokens": 10, "cached_input_tokens": 2, "output_tokens": 4, "total_tokens": 14, "exact": True},
                "cost_cny": 0.012,
                "latency_ms": 210,
                "time_to_first_token_ms": 42,
                "pricing_version": "2026-08",
                "reasoning_content": "must-never-leave-adapter",
            },
            "private_prompt": "must-never-leave-adapter",
        },
        message_parts=parts,
        result_semantic="VALUE",
        attachment_ids=attachment_ids,
    )


@pytest.mark.parametrize(
    ("route", "payload", "parts", "attachment_ids", "expected_route"),
    [
        ("DATA_QUERY", {"analysis": {"primary": _query_payload()}}, _parts(), (), AnswerRoute.DATA_QUERY),
        (
            "KNOWLEDGE_QUERY",
            {
                "analysis": {"primary": {"knowledge": {"citations": [{
                    "citation_id": "citation-1", "document_id": "document-1", "document_version_id": "v1",
                    "chunk_id": "chunk-1", "title": "收入口径", "locator": "第 2 节",
                }]}}},
                "grounded_answer_guard": {"passed": True},
            },
            _parts()[:1],
            (),
            AnswerRoute.KNOWLEDGE_QUERY,
        ),
        (
            "HYBRID_ANALYSIS",
            {"analysis": {"primary": {"data": _query_payload(), "knowledge": {"citations": []}}}},
            _parts(),
            (),
            AnswerRoute.HYBRID_ANALYSIS,
        ),
        (
            "COMPLEX_ANALYSIS",
            {"analysis": {"primary": {
                "data_evidence": _query_payload(),
                "verification": {"result_verified": True},
                "steps": [{
                    "ordinal": 1,
                    "code": "VERIFY",
                    "agent_role": "VerificationAgent",
                    "tool_name": "VERIFY_RESULT",
                    "status": "SUCCEEDED",
                    "duration_ms": 12,
                    "detail": {"result_signature": "result-signature-1", "reasoning_content": "private"},
                }],
            }}},
            _parts(),
            (),
            AnswerRoute.COMPLEX_ANALYSIS,
        ),
        (
            "FILE_QUERY",
            {
                "citations": [{
                    "attachment_id": "attachment-1", "filename": "<img src=x onerror=alert(1)>.csv",
                    "kind": "STRUCTURED", "result_signature": "file-signature-1",
                }],
                "file_analysis": {
                    "result": {
                        "columns": ["region", "revenue"], "rows": [{"region": "华东", "revenue": 270}],
                        "row_count": 1, "result_signature": "file-signature-1",
                    },
                    "chart": {"chart_type": "bar", "x": "region", "y": "revenue"},
                    "artifacts": [
                        {
                            "attachment_id": "attachment-1", "filename": "sales.csv",
                            "csv_url": "/api/v1/attachments/attachment-1/artifact?format=csv",
                            "json_url": "javascript:alert(1)",
                        },
                    ],
                },
            },
            [{"type": "text", "text": "文件收入为 270 元。", "role": "conclusion"}],
            ("attachment-1",),
            AnswerRoute.FILE_QUERY,
        ),
        (
            "MULTIMODAL_QUERY",
            {
                "visual_evidence": [{
                    "cache_key": {"workspace_id": "must-not-leak", "file_sha256": "private"},
                    "provider": "kimi", "model": "kimi-k2.6",
                    "claims": [{
                        "claim": "收入", "value": 270, "locator": {"locator_type": "image", "tile": 0},
                        "confidence": 0.99, "time_range": "2026", "dimension": "华东",
                    }],
                    "sanitized_text": "截图显示收入 270。", "sensitive_classification": "NONE",
                    "injection_detected": False, "signature": "visual-signature-1",
                    "reasoning_content": "private",
                }],
            },
            [{"type": "text", "text": "截图显示收入 270。", "role": "conclusion"}],
            ("attachment-image-1",),
            AnswerRoute.VISION_QUERY,
        ),
    ],
)
def test_six_phase3_routes_produce_one_public_answer_envelope(route, payload, parts, attachment_ids, expected_route):
    envelope = _build(route, response_payload=payload, parts=parts, attachment_ids=attachment_ids)
    assert envelope.route is expected_route
    assert envelope.answer_id == f"answer-{route}"
    assert envelope.conversation_id == "conversation-1"
    assert envelope.message_id == f"message-{route}"
    assert envelope.trace_id == f"trace-{route}"
    assert envelope.summary
    assert envelope.markdown == "已完成受控分析。"
    assert envelope.cost.total_tokens == 14
    assert envelope.latency.total_ms == 321
    assert envelope.provider == "mimo"
    serialized = json.dumps(envelope.model_dump(mode="json"), ensure_ascii=False)
    assert "reasoning_content" not in serialized
    assert "must-never-leave-adapter" not in serialized
    assert "must-not-leak" not in serialized


def test_data_envelope_deduplicates_citations_and_keeps_only_controlled_chart_fields():
    parts = _parts()
    parts.append(parts[6].copy())
    envelope = _build("DATA_QUERY", response_payload={"analysis": {"primary": _query_payload()}}, parts=parts)
    assert len(envelope.citations) == 1
    assert envelope.citations[0].href is None
    assert envelope.sql and envelope.sql.startswith("SELECT")
    assert envelope.table and envelope.table.result_signature == "result-signature-1"
    assert envelope.chart and envelope.chart["axis"] == {}
    assert envelope.chart["tooltip"] == {}
    assert envelope.verification.status == "VERIFIED"
    assert {item.code for item in envelope.verification.checks} >= {"SQL_GUARD", "RESULT_ORACLE"}
    assert envelope.follow_up_suggestions == ["按客户查看收入"]


def test_file_artifact_requires_same_origin_api_url_and_filename_remains_inert_text():
    envelope = _build(
        "FILE_QUERY",
        response_payload={
            "citations": [{"attachment_id": "attachment-1", "filename": "../<svg onload=alert(1)>.csv", "kind": "STRUCTURED"}],
            "file_analysis": {"artifacts": [{
                "attachment_id": "attachment-1", "filename": "sales.csv",
                "csv_url": "/api/v1/attachments/attachment-1/artifact?format=csv",
                "json_url": "data:text/html,<script>alert(1)</script>",
            }]},
        },
        parts=[{"type": "text", "text": "文件已处理。", "role": "conclusion"}],
    )
    assert [item.kind for item in envelope.artifacts] == ["CSV"]
    assert envelope.artifacts[0].download_url.startswith("/api/v1/")
    assert envelope.file_evidence[0].filename == "<svg onload=alert(1)>.csv"
    with pytest.raises(ValidationError):
        AnswerArtifact(id="bad", name="bad", kind="HTML", download_url="javascript:alert(1)")
