from __future__ import annotations

import io
import hashlib
from pathlib import Path
from types import SimpleNamespace
import json

from PIL import Image
from pypdf import PdfWriter
import pytest
from fastapi import HTTPException

import app.services.chat as chat_module
from app.integration.question_router import QuestionRouter
from app.file_multimodal.contracts import canonical_sha256
from app.model_gateway import RequestContext
from app.services.chat import ChatService, _operation_spans, _render_scanned_pdf
from chatbi_agent_contracts import QuestionRoute


def _png(width: int = 800, height: int = 600) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(output, format="PNG")
    return output.getvalue()


def _blank_pdf() -> bytes:
    output = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=200)
    writer.write(output)
    return output.getvalue()


class _VisionGateway:
    def __init__(self) -> None:
        self.kwargs = None
        self.calls = 0

    def complete(self, **kwargs):
        self.kwargs = kwargs
        self.calls += 1
        return SimpleNamespace(
            content=json.dumps({
                "answer": "图中可见 KPI 100。",
                "claims": [{
                    "metric": "KPI", "value": 100, "time_range": None,
                    "dimension": None, "confidence": 1.0,
                }],
                "prompt_injection_detected": False,
                "sensitive_classification": "NONE",
                "sensitive_categories": [],
                "safe_to_publish": True,
            }, ensure_ascii=False),
            provider="mimo",
            model="mimo-v2.5",
            trace={"provider": "mimo"},
        )


def _attachment(path: Path, *, kind: str, mime_type: str, sha256: str):
    return SimpleNamespace(
        id=f"ATT-{kind}",
        workspace_id="workspace-a",
        user_id="user-a",
        filename=path.name,
        kind=kind,
        mime_type=mime_type,
        sha256=sha256,
    )


def _context() -> RequestContext:
    return RequestContext(
        request_id="REQ-PHASE3-CONTROL",
        trace_id="TRACE-PHASE3-CONTROL",
        workspace_id="workspace-a",
        user_id="user-a",
        question="识别 KPI",
    )


def test_scanned_pdf_renders_to_bounded_clean_png():
    pages = _render_scanned_pdf(_blank_pdf())
    assert len(pages) == 1
    assert pages[0].startswith(b"\x89PNG\r\n\x1a\n")


def test_scanned_pdf_routes_to_existing_multimodal_route():
    decision = QuestionRouter().decide(
        "识别 KPI", attachment_kinds={"SCANNED_PDF"}, context=_context()
    )
    assert decision.route == QuestionRoute.MULTIMODAL_QUERY
    assert decision.reason == "VISION_ATTACHMENT"


def test_vision_uses_preprocessed_png_mimo_default_and_visual_evidence(monkeypatch, tmp_path):
    path = tmp_path / "dashboard.png"
    path.write_bytes(_png())
    item = _attachment(path, kind="IMAGE", mime_type="image/png", sha256="a" * 64)
    monkeypatch.setattr(chat_module, "attachment_path", lambda _item: path)
    gateway = _VisionGateway()
    result = ChatService(gateway)._vision_answer(
        "识别 KPI", [item], [], request_context=_context(), complexity_score=25
    )
    answer, provider, model, streamed, _trace, evidence = result
    assert (answer, provider, model, streamed) == (
        "图中可见 KPI 100。", "mimo", "mimo-v2.5", False
    )
    assert gateway.kwargs["premium_triggers"] == frozenset()
    assert gateway.kwargs["json_mode"] is True
    assert all(value.startswith("data:image/png;base64,") for value in gateway.kwargs["image_data_urls"])
    assert evidence[0]["cache_key"]["workspace_id"] == "workspace-a"
    assert evidence[0]["cache_key"]["file_sha256"] == "a" * 64
    assert evidence[0]["metadata"]["raw_image_forwarded_to_deepseek"] is False


def test_production_vision_cache_get_is_question_bound(monkeypatch, tmp_path):
    path = tmp_path / "cache-dashboard.png"
    path.write_bytes(_png(900, 700))
    item = _attachment(path, kind="IMAGE", mime_type="image/png", sha256="9" * 64)
    monkeypatch.setattr(chat_module, "attachment_path", lambda _item: path)
    gateway = _VisionGateway()
    gateway.providers = {"mimo": SimpleNamespace(model_name="mimo-v2.5")}
    service = ChatService(gateway)
    first = service._vision_answer("识别缓存 KPI", [item], [], request_context=_context())
    second = service._vision_answer("识别缓存 KPI", [item], [], request_context=_context())
    assert gateway.calls == 1
    assert first[0] == second[0]
    assert second[4]["cache_hit"] is True
    assert second[5][0]["cache_hit"] is True


def test_vision_safety_envelope_rejects_pixel_prompt_injection(monkeypatch, tmp_path):
    path = tmp_path / "injection.png"
    path.write_bytes(_png())
    item = _attachment(path, kind="IMAGE", mime_type="image/png", sha256="8" * 64)
    monkeypatch.setattr(chat_module, "attachment_path", lambda _item: path)

    class InjectionGateway(_VisionGateway):
        def complete(self, **kwargs):
            return SimpleNamespace(
                content=json.dumps({
                    "answer": "",
                    "claims": [],
                    "prompt_injection_detected": True,
                    "sensitive_classification": "NONE",
                    "sensitive_categories": [],
                    "safe_to_publish": False,
                }),
                provider="mimo",
                model="mimo-v2.5",
                trace={},
            )

    with pytest.raises(HTTPException, match="IMAGE_PROMPT_INJECTION_DETECTED"):
        ChatService(InjectionGateway())._vision_answer(
            "识别 KPI", [item], [], request_context=_context()
        )


def test_scanned_pdf_enters_same_preprocess_and_vision_gateway(monkeypatch, tmp_path):
    path = tmp_path / "scan.pdf"
    path.write_bytes(_blank_pdf())
    item = _attachment(path, kind="SCANNED_PDF", mime_type="application/pdf", sha256="b" * 64)
    monkeypatch.setattr(chat_module, "attachment_path", lambda _item: path)
    gateway = _VisionGateway()
    result = ChatService(gateway)._vision_answer(
        "识别扫描件", [item], [], request_context=_context(), complexity_score=25
    )
    assert result[5][0]["metadata"]["pages"] == [1]
    assert gateway.kwargs["image_data_urls"][0].startswith("data:image/png;base64,")


def test_chat_file_path_reparses_full_file_instead_of_persisted_preview(monkeypatch, tmp_path):
    path = tmp_path / "revenue.csv"
    data = ("region,revenue\n" + "\n".join(
        f"east,{value}" for value in range(1, 151)
    ) + "\n").encode("utf-8")
    path.write_bytes(data)
    item = _attachment(
        path,
        kind="STRUCTURED",
        mime_type="text/csv",
        sha256=hashlib.sha256(data).hexdigest(),
    )
    monkeypatch.setattr(chat_module, "attachment_path", lambda _item: path)
    answer, provider, model, _sources, analysis, streamed, _trace = ChatService(
        _VisionGateway()
    )._file_answer(
        "revenue 合计", [item], [], request_context=_context(), complexity_score=25
    )
    assert answer == "revenue 合计为 11325。"
    assert (provider, model, streamed) == (
        "chatbi-safe-dataframe", "full-file-operators-v1", False
    )
    assert analysis["exact_for_full_file"] is True
    assert analysis["rows"][0]["sum"] == 11325.0


def test_image_database_compare_uses_only_guarded_oracle_verified_query(monkeypatch):
    captured = {}

    class Analysis:
        def execute(self, db, analysis_request, principal, **kwargs):
            captured["request"] = analysis_request
            return SimpleNamespace(
                status="SUCCEEDED",
                primary={
                    "id": "QUERY-IMAGE-DB",
                    "guard": {"allowed": True},
                    "oracle": {"status": "PASSED"},
                    "execution": {
                        "rows": [{"revenue": 90}],
                        "result_signature": "c" * 64,
                    },
                    "context": {"time_range": "2026-Q2"},
                    "plan": {"business_definition": "已确认收入"},
                },
            )

    monkeypatch.setattr(chat_module, "AnalysisService", Analysis)
    request = SimpleNamespace(
        datasource_id="DS-1",
        semantic_model_id="SEM-1",
        client_message_id="MSG-1",
    )
    question = "核对截图收入与数据库 revenue"
    evidence = {
        "cache_key": {},
        "provider": "mimo",
        "model": "mimo-v2.5",
        "claims": [{
            "claim": "revenue", "value": 100, "time_range": "2026-Q2",
            "dimension": None, "confidence": 1.0,
            "locator": {"locator_type": "image", "page": None, "paragraph": None,
                        "table": None, "row": None, "column": None, "tile": 0},
        }],
        "sanitized_text": "截图中收入为 100。",
        "sensitive_classification": "NONE",
        "injection_detected": False,
        "preprocess_sha256": "p" * 64,
        "metadata": {"question_sha256": hashlib.sha256(question.encode("utf-8")).hexdigest()},
    }
    evidence["signature"] = canonical_sha256(evidence)
    compared = ChatService(_VisionGateway())._image_database_compare(
        object(),
        SimpleNamespace(),
        request,
        question,
        "截图中 revenue 为 100。",
        [evidence],
        request_context=_context(),
        cancellation_event=None,
    )
    assert captured["request"].route == QuestionRoute.DATA_QUERY
    assert compared["status"] == "PASSED"
    assert compared["screenshot_value"] == 100.0
    assert compared["database_value"] == 90.0
    assert compared["difference"] == 10.0
    assert compared["database_evidence"]["oracle_status"] == "PASSED"


def test_unified_operation_span_names_are_bound_to_actual_control_plane_work():
    spans = _operation_spans(
        QuestionRoute.HYBRID_ANALYSIS,
        sse_streamed=True,
        model_provider="mimo",
        retrieved_sources=[{"citation_id": "C1"}],
        tool_calls=[{"tool": "QUERY_DATA"}],
        sql_execution={"rows": [{"value": 1}]},
        response_payload={
            "file_analysis": {
                "sandbox": {"trace_stages": ["python.execute"]}
            }
        },
    )
    assert {item["name"] for item in spans} == {
        "sse.stream",
        "rag.retrieve",
        "agent.step",
        "python.execute",
        "model.invoke",
        "sql.execute",
        "oracle.verify",
        "answer.compose",
    }
