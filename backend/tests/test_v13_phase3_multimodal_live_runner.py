from __future__ import annotations

import json
from pathlib import Path

import httpx

from app.core.config import Settings
from app.model_gateway import ModelGateway
from scripts.run_v13_multimodal_live import run_multimodal_suite, write_report


_RESPONSES = {
    "M01": {"metric": "Revenue", "time": "2026-07", "value": 1_250_000},
    "M02": {"series_a": [10, 20], "series_b": [8, 16], "final_difference": 4},
    "M03": {"city": "Guangzhou", "value": 87},
    "M04": {"value": "18.6%"},
    "M05": {"label": "EXIF NORMALIZED", "value": 55},
    "M06": {"left": 120, "right": 132},
    "M07": {"screenshot": 270},
    "M08": {"safe_value": 42, "injection_used": False},
    "M09": {"classification": "HIGH", "redacted_phone": "138****8000"},
    "M10": {"pages": 3, "rotated_page": 2, "page_locator": 3, "value": 760},
}


def _gateway(calls: list[tuple[str, str]]) -> ModelGateway:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        user_content = body["messages"][-1]["content"]
        prompt = next(item["text"] for item in user_content if item["type"] == "text")
        case_id = prompt.split("CASE_ID=", 1)[1].split(".", 1)[0]
        calls.append((case_id, str(request.url)))
        provider = "kimi" if "moonshot" in str(request.url) else "mimo"
        return httpx.Response(200, json={
            "model": f"unit-{provider}-vision",
            "choices": [{"message": {"content": json.dumps(_RESPONSES[case_id])}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        })

    return ModelGateway(
        Settings(
            _env_file=None,
            mimo_api_key="unit-mimo-key",
            kimi_api_key="unit-kimi-key",
            deepseek_api_key="unit-deepseek-key",
            vision_model_provider="auto",
            model_budget_mode="quality",
        ),
        transport=httpx.MockTransport(handler),
        sleeper=lambda _seconds: None,
    )


def test_multimodal_10_runner_exercises_real_gateway_routing_and_production_paths(tmp_path: Path):
    calls: list[tuple[str, str]] = []
    report = run_multimodal_suite(
        _gateway(calls),
        execution_mode="unit_mock",
        generated_at="2026-08-22T00:00:00Z",
    )

    assert report["status"] == "TEST_PASS"
    assert report["score"] == "NOT_ACHIEVED"
    assert report["passed"] == report["total"] == 10
    assert [item["id"] for item in report["results"]] == [f"M{number:02d}" for number in range(1, 11)]
    assert len(calls) == 10
    by_case = dict(calls)
    for case_id in ("M01", "M02", "M05", "M07", "M08", "M09"):
        assert "xiaomimimo" in by_case[case_id]
    for case_id in ("M03", "M04", "M06", "M10"):
        assert "moonshot" in by_case[case_id]

    outside_repo = tmp_path / "outside" / "live-result.json"
    assert write_report(report, outside_repo) == outside_repo.resolve()
    serialized = outside_repo.read_text(encoding="utf-8")
    assert "unit-mimo-key" not in serialized
    assert "unit-kimi-key" not in serialized
    assert "13800138000" not in serialized
    assert "SYNTHETIC_SECRET_SENTINEL" not in serialized
    assert "data:image" not in serialized
    assert json.loads(serialized)["raw_model_output_persisted"] is False


def test_only_live_execution_can_emit_overall_pass():
    report = run_multimodal_suite(
        _gateway([]),
        execution_mode="unit_mock",
        generated_at="2026-08-22T00:00:00Z",
    )
    assert report["score"] != "10/10"
    assert report["status"] != "PASS"


def test_targeted_multimodal_case_is_labeled_non_final():
    calls: list[tuple[str, str]] = []
    report = run_multimodal_suite(
        _gateway(calls),
        execution_mode="unit_mock",
        generated_at="2026-08-23T00:00:00Z",
        selected_case_ids=frozenset({"M10"}),
    )

    assert report["status"] == "TEST_PASS"
    assert report["certification_scope"] == "TARGETED_CASES_ONLY"
    assert report["selected_case_ids"] == ["M10"]
    assert report["score"] == "NOT_ACHIEVED"
    assert report["passed"] == report["total"] == 1
    assert calls == [("M10", "https://api.moonshot.cn/v1/chat/completions")]
