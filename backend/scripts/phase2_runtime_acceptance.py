from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from uuid import uuid4

import httpx
from dotenv import dotenv_values


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MANIFEST = PROJECT_ROOT / "evaluation" / "golden" / "phase2-open-ended-60.json"
CSV_FIXTURE = PROJECT_ROOT / "evaluation" / "fixtures" / "phase2-regional-revenue.csv"
TEXT_FIXTURE = PROJECT_ROOT / "evaluation" / "fixtures" / "phase2-policy.txt"
IMAGE_FIXTURE = PROJECT_ROOT / "docs" / "ui" / "03_问数据_分析结果.png"

FILE_EXPECTATIONS = {
    "OE-F01": ("270", "180"),
    "OE-F02": ("150",),
    "OE-F03": ("100", "审批"),
    "OE-F04": ("风险事项",),
    "OE-F05": ("112.5",),
}
IMAGE_EXPECTATIONS = {
    "OE-M01": ("华东", "18"),
    "OE-M02": ("1.84",),
    "OE-M03": ("上升",),
    "OE-M04": ("上半年", "8月"),
    "OE-M05": ("华东", "华南"),
}
FOLLOW_UP_EXPECTATIONS = {
    "OE-FU01": ("今年", "销售额", "华南"),
    "OE-FU02": ("华东", "华南", "按地区"),
    "OE-FU03": ("华东", "华南", "按月份"),
    "OE-FU04": ("华东", "华南", "按月"),
    "OE-FU05": ("销售额", "知识库规则"),
    "OE-FU06": ("华北",),
    "OE-FU07": ("趋势",),
    "OE-FU08": ("销售额", "最低"),
    "OE-FU09": ("依据",),
    "OE-FU10": ("订单量",),
}
NO_EVIDENCE_MARKERS = ("未", "没有", "无相关", "不存在", "未提及")


def _conversation(client: httpx.Client, api: str, title: str) -> str:
    response = client.post(f"{api}/conversations", json={"title": title})
    response.raise_for_status()
    return response.json()["id"]


def _upload(client: httpx.Client, api: str, conversation_id: str, path: Path, mime: str) -> str:
    with path.open("rb") as stream:
        response = client.post(
            f"{api}/attachments",
            data={"conversation_id": conversation_id},
            files={"file": (path.name, stream, mime)},
        )
    response.raise_for_status()
    payload = response.json()
    if payload["status"] != "READY":
        raise RuntimeError(f"{path.name} was not parsed: {payload.get('error_code')}")
    return payload["id"]


def _chat(client: httpx.Client, api: str, conversation_id: str, question: str, attachment_ids: list[str], parent: str | None):
    response = client.post(f"{api}/chat", json={
        "conversation_id": conversation_id,
        "content": question,
        "parent_message_id": parent,
        "client_message_id": f"acceptance-{uuid4()}",
        "attachment_ids": attachment_ids,
    })
    response.raise_for_status()
    return response.json()


def run(base_url: str, *, reuse: bool = False, env_file: Path | None = None) -> dict:
    api = f"{base_url.rstrip('/')}/api/v1"
    environment = dotenv_values(env_file or PROJECT_ROOT / ".env")
    password = environment.get("CHATBI_BOOTSTRAP_ADMIN_PASSWORD")
    if not password:
        raise RuntimeError("CHATBI_BOOTSTRAP_ADMIN_PASSWORD is not configured")
    cases = json.loads(MANIFEST.read_text(encoding="utf-8"))["cases"]
    results: list[dict] = []
    with httpx.Client(timeout=90, trust_env=False) as client:
        login = client.post(f"{api}/auth/login", json={"email": "admin@chatbi.local", "password": password})
        login.raise_for_status()
        cases_to_run = cases
        if reuse:
            conversations = client.get(f"{api}/conversations").json()
            by_title: dict[str, dict] = {}
            for item in conversations:
                by_title.setdefault(item["title"], item)
            for case in cases:
                title = {
                    "FILE_QUERY": "Phase2 file acceptance",
                    "MULTIMODAL_QUERY": "Phase2 image acceptance",
                    "FOLLOW_UP": "Phase2 follow-up acceptance",
                }.get(case["category"], f"Acceptance {case['id']}")
                conversation = by_title.get(title)
                if not conversation:
                    raise RuntimeError(f"Missing reusable conversation: {title}")
                detail = client.get(f"{api}/conversations/{conversation['id']}").json()
                user = next((item for item in reversed(detail["messages"]) if item["role"] == "user" and item["content"] == case["question"]), None)
                assistant = next((item for item in detail["messages"] if user and item["role"] == "assistant" and item["parent_message_id"] == user["id"]), None)
                if not user or not assistant:
                    raise RuntimeError(f"Missing reusable message: {case['id']}")
                results.append({
                    "id": case["id"], "category": case["category"], "expected_route": case["expected_route"],
                    "route": assistant.get("route"), "status": assistant.get("status"),
                    "error_code": assistant.get("error_code"), "content": assistant.get("content", ""),
                    "resolved_question": (user.get("context_payload") or {}).get("resolved_question", ""),
                    "trace": assistant.get("trace_payload") or {}, "http_ok": True,
                })
            cases_to_run = []
        shared: dict[str, tuple[str, list[str]]] = {}
        follow_conversation = ""
        follow_parent = None
        if cases_to_run:
            file_conversation = _conversation(client, api, "Phase2 file acceptance")
            shared["FILE_QUERY"] = (file_conversation, [
                _upload(client, api, file_conversation, CSV_FIXTURE, "text/csv"),
                _upload(client, api, file_conversation, TEXT_FIXTURE, "text/plain"),
            ])
            image_conversation = _conversation(client, api, "Phase2 image acceptance")
            shared["MULTIMODAL_QUERY"] = (image_conversation, [
                _upload(client, api, image_conversation, IMAGE_FIXTURE, "image/png"),
            ])
            follow_conversation = _conversation(client, api, "Phase2 follow-up acceptance")
            seed = _chat(client, api, follow_conversation, "今年华东区销售额是多少？", [], None)
            follow_parent = seed["assistant_message"]["id"]

        for case in cases_to_run:
            category = case["category"]
            if category in shared:
                conversation_id, attachment_ids = shared[category]
            elif category == "FOLLOW_UP":
                conversation_id, attachment_ids = follow_conversation, []
            else:
                conversation_id, attachment_ids = _conversation(client, api, f"Acceptance {case['id']}"), []
            parent = follow_parent if category == "FOLLOW_UP" else None
            try:
                payload = _chat(client, api, conversation_id, case["question"], attachment_ids, parent)
                assistant = payload["assistant_message"]
                user = payload["user_message"]
                if category == "FOLLOW_UP":
                    follow_parent = assistant["id"]
                trace = assistant.get("trace_payload") or {}
                results.append({
                    "id": case["id"],
                    "category": category,
                    "expected_route": case["expected_route"],
                    "route": assistant.get("route"),
                    "status": assistant.get("status"),
                    "error_code": assistant.get("error_code"),
                    "content": assistant.get("content", ""),
                    "resolved_question": (user.get("context_payload") or {}).get("resolved_question", ""),
                    "trace": trace,
                    "http_ok": True,
                })
            except (httpx.HTTPError, KeyError, TypeError, RuntimeError) as exc:
                results.append({
                    "id": case["id"], "category": category, "expected_route": case["expected_route"],
                    "route": None, "status": "HTTP_FAILED", "error_code": type(exc).__name__, "content": "",
                    "resolved_question": "", "trace": {}, "http_ok": False,
                })

    route_failures = [item["id"] for item in results if item["route"] != item["expected_route"]]
    trace_keys = {
        "conversation_id", "message_id", "workspace_id", "user_id", "route", "model_provider", "model_name",
        "prompt_version", "semantic_model_version", "retrieved_sources", "tool_calls", "sql_execution",
        "fallback_reason", "elapsed_ms",
    }
    trace_failures = [item["id"] for item in results if not trace_keys.issubset(item["trace"])]
    follow_failures = [
        item["id"] for item in results if item["id"] in FOLLOW_UP_EXPECTATIONS
        and not all(value in item["resolved_question"] for value in FOLLOW_UP_EXPECTATIONS[item["id"]])
    ]
    data = [item for item in results if item["category"] == "DATA_QUERY"]
    data_sql_pass = sum((item["trace"].get("sql_execution") or {}).get("status") == "SUCCEEDED" for item in data)
    data_value_pass = sum(
        bool((item["trace"].get("sql_execution") or {}).get("result_signature")) and item["status"] == "SUCCEEDED"
        for item in data
    )
    file_failures = [
        item["id"] for item in results if item["id"] in FILE_EXPECTATIONS
        and (
            not all(value.lower() in item["content"].lower() for value in FILE_EXPECTATIONS[item["id"]])
            or (item["id"] == "OE-F04" and not any(value in item["content"] for value in NO_EVIDENCE_MARKERS))
        )
    ]
    image_failures = [
        item["id"] for item in results if item["id"] in IMAGE_EXPECTATIONS
        and not all(value.lower() in item["content"].lower() for value in IMAGE_EXPECTATIONS[item["id"]])
    ]
    knowledge = [item for item in results if item["expected_route"] == "KNOWLEDGE_QUERY"]
    cited = [item for item in knowledge if item["trace"].get("retrieved_sources")]
    citation_valid = sum(
        all(source.get("chunk_id") and source.get("document_id") for source in item["trace"]["retrieved_sources"])
        for item in cited
    )
    unsupported = [item for item in results if item["expected_route"] == "UNSUPPORTED"]
    return {
        "total": len(results),
        "category_counts": Counter(item["category"] for item in results),
        "open_ended_request_runtime_rate": round(sum(item["http_ok"] for item in results) / len(results), 4),
        "question_route_coverage": f"{len(results) - len(route_failures)}/{len(results)}",
        "route_failures": route_failures,
        "trace_complete": f"{len(results) - len(trace_failures)}/{len(results)}",
        "trace_failures": trace_failures,
        "follow_up_context_pass": f"{10 - len(follow_failures)}/10",
        "follow_up_failures": follow_failures,
        "data_sql_execution_rate": round(data_sql_pass / len(data), 4),
        "data_result_value_accuracy": round(data_value_pass / len(data), 4),
        "knowledge_citation_accuracy": round(citation_valid / len(cited), 4) if cited else 0,
        "knowledge_cited_count": len(cited),
        "file_result_accuracy": round((5 - len(file_failures)) / 5, 4),
        "file_failures": file_failures,
        "image_question_accuracy": round((5 - len(image_failures)) / 5, 4),
        "image_failures": image_failures,
        "unsupported_request_hallucination": sum(
            item["status"] != "REFUSED" or item["error_code"] != "UNSUPPORTED" for item in unsupported
        ),
        "status_counts": Counter(item["status"] for item in results),
        "route_counts": Counter(item["route"] for item in results),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--reuse", action="store_true", help="score the most recent persisted acceptance conversations")
    parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = run(args.base_url, reuse=args.reuse, env_file=args.env_file)
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
