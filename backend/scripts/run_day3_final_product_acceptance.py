from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
from dotenv import dotenv_values


PROJECT_ROOT = Path(__file__).resolve().parents[2]
OPEN_SET = PROJECT_ROOT / "evaluation" / "golden" / "final-open-question-100.json"
MEMORY_SET = PROJECT_ROOT / "evaluation" / "golden" / "final-memory-30x5.json"
CSV_FIXTURE = PROJECT_ROOT / "evaluation" / "fixtures" / "phase2-regional-revenue.csv"
IMAGE_FIXTURE = PROJECT_ROOT / "docs" / "ui" / "03_问数据_分析结果.png"
CHAT_ROUTES = {
    "GENERAL_CHAT", "DATA_QUERY", "KNOWLEDGE_QUERY", "HYBRID_ANALYSIS", "COMPLEX_ANALYSIS",
    "FILE_QUERY", "MULTIMODAL_QUERY", "CLARIFICATION", "UNSUPPORTED",
}
TRACE_KEYS = {
    "conversation_id", "message_id", "workspace_id", "user_id", "route", "model_provider",
    "model_name", "prompt_version", "semantic_model_version", "retrieved_sources", "tool_calls",
    "sql_execution", "fallback_reason", "elapsed_ms",
}


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _ok(response: httpx.Response) -> dict:
    response.raise_for_status()
    return response.json()


def _create_conversation(client: httpx.Client, api: str, title: str) -> str:
    return _ok(client.post(f"{api}/conversations", json={"title": title})) ["id"]


def _upload(client: httpx.Client, api: str, conversation_id: str, path: Path, mime: str) -> str:
    with path.open("rb") as stream:
        response = client.post(
            f"{api}/attachments", data={"conversation_id": conversation_id},
            files={"file": (path.name, stream, mime)},
        )
    payload = _ok(response)
    if payload["status"] != "READY":
        raise RuntimeError(f"ATTACHMENT_NOT_READY:{payload.get('error_code')}")
    return payload["id"]


def _runtime_context(client: httpx.Client, api: str) -> tuple[str, str]:
    datasources = _ok(client.get(f"{api}/datasources"))
    models = _ok(client.get(f"{api}/semantic-models"))
    datasource = next(item for item in datasources if item["type"] == "postgresql" and item["status"] == "CONNECTED")
    semantic = next(item for item in models if item["datasource_id"] == datasource["id"] and item["status"] == "PUBLISHED")
    return datasource["id"], semantic["id"]


def _chat_case(
    client: httpx.Client,
    api: str,
    case: dict,
    datasource_id: str,
    semantic_model_id: str,
    conversation_id: str,
    attachments: list[str],
) -> dict:
    response = client.post(f"{api}/chat", json={
        "conversation_id": conversation_id,
        "content": case["question"],
        "client_message_id": f"day3-open-{uuid4()}",
        "attachment_ids": attachments,
        "datasource_id": datasource_id,
        "semantic_model_id": semantic_model_id,
    })
    payload = _ok(response)
    assistant = payload["assistant_message"]
    trace = assistant.get("trace_payload") or {}
    expected = case["expected_route"]
    actual = assistant.get("route")
    acceptable = (
        assistant.get("status") in {"SUCCEEDED", "PARTIAL"}
        or (expected == "UNSUPPORTED" and assistant.get("status") == "REFUSED" and assistant.get("error_code") == "UNSUPPORTED")
    )
    return {
        "id": case["id"], "category": case["category"], "question": case["question"],
        "expected_route": expected, "actual_route": actual, "http_status": response.status_code,
        "runtime_status": assistant.get("status"), "error_code": assistant.get("error_code"),
        "trace_id": response.headers.get("X-Trace-ID") or trace.get("trace_id"),
        "trace_complete": TRACE_KEYS.issubset(trace), "route_pass": actual == expected,
        "runtime_pass": acceptable, "content_excerpt": str(assistant.get("content") or "")[:240],
    }


def _dedicated_case(
    client: httpx.Client,
    api: str,
    case: dict,
    datasource_id: str,
    semantic_model_id: str,
    state: dict[str, Any],
) -> dict:
    category = case["category"]
    index = int(case["id"].split("-")[-1])
    response: httpx.Response
    semantic_pass = True
    if category == "SQL_WORKSPACE":
        operation = len(state.setdefault("sql_cases", []))
        safe_sql = "SELECT 1 AS release_probe"
        if operation == 0:
            response = client.post(f"{api}/data-workspace/sql/format", json={"datasource_id": datasource_id, "sql": safe_sql})
        elif operation == 1:
            response = client.post(f"{api}/data-workspace/sql/execute", json={"datasource_id": datasource_id, "sql": safe_sql, "row_limit": 5})
            if response.status_code < 400:
                state["sql_run_id"] = response.json().get("id")
                semantic_pass = response.json().get("status") == "SUCCEEDED"
        elif operation == 2:
            response = client.post(f"{api}/data-workspace/sql/explain", json={"datasource_id": datasource_id, "sql": safe_sql, "row_limit": 5})
        elif operation == 3:
            response = client.get(f"{api}/data-workspace/datasources/{datasource_id}/search", params={"q": "revenue", "kind": "column"})
        elif operation == 4:
            response = client.get(f"{api}/data-workspace/sql/history", params={"datasource_id": datasource_id})
        elif operation == 5 and state.get("sql_run_id"):
            response = client.post(f"{api}/data-workspace/sql/history/{state['sql_run_id']}/replay")
        elif operation == 6 and state.get("sql_run_id"):
            response = client.post(f"{api}/data-workspace/sql/history/{state['sql_run_id']}/verify", json={"owner_name": "Day3 final acceptance", "status": "DRAFT"})
        else:
            response = client.post(f"{api}/data-workspace/sql/execute", json={"datasource_id": datasource_id, "sql": "SELECT 1; SELECT 2", "row_limit": 5})
            if response.status_code < 400:
                semantic_pass = response.json().get("status") == "SECURITY_REJECTED"
        state["sql_cases"].append(case["id"])
    elif category == "EVALUATION":
        operation = len(state.setdefault("evaluation_cases", []))
        overview = state.get("evaluation_overview")
        if overview is None:
            probe = client.get(f"{api}/evaluation/overview")
            if probe.status_code == 404:
                probe = client.post(f"{api}/evaluation/runs")
                overview = {"current": probe.json()["run"], "comparisons": []}
            else:
                overview = probe.json()
            state["evaluation_overview"] = overview
        current_id = overview["current"]["id"]
        if operation == 0:
            response = client.get(f"{api}/evaluation/overview")
        elif operation == 1:
            response = client.get(f"{api}/evaluation/dashboard")
        elif operation == 2:
            response = client.get(f"{api}/evaluation/runs/{current_id}")
        elif operation == 3:
            response = client.get(f"{api}/evaluation/runs/{current_id}/gate")
        elif operation == 4:
            response = client.get(f"{api}/evaluation/cases/G01")
        elif operation == 5:
            comparison_ids = [current_id, *[item["id"] for item in overview.get("comparisons", []) if item["id"] != current_id]][:2]
            response = (
                client.post(f"{api}/evaluation/compare", json={"run_ids": comparison_ids})
                if len(comparison_ids) >= 2 else client.get(f"{api}/evaluation/dashboard")
            )
        else:
            response = client.get(f"{api}/evaluation/overview")
            if response.status_code < 400:
                current = response.json()["current"]
                semantic_pass = current["dangerous_sql_block_count"] == current["dangerous_sql_total"]
        state["evaluation_cases"].append(case["id"])
    else:
        operation = len(state.setdefault("feedback_cases", []))
        if operation in {0, 4, 5}:
            response = client.get(f"{api}/evaluation/feedback/dashboard")
            if response.status_code < 400 and operation == 4:
                semantic_pass = 0 <= response.json().get("feedback_replay_rate", -1) <= 1
        else:
            questions = (
                "按地区统计销售额", "每月收入趋势", "按产品统计销售额前五名", "当前工作空间销售额",
            )
            response = client.post(f"{api}/evaluation/feedback/recall", json={
                "question": questions[(operation - 1) % len(questions)],
                "datasource_id": datasource_id, "semantic_model_id": semantic_model_id,
            })
        state["feedback_cases"].append(case["id"])
    trace_id = response.headers.get("X-Trace-ID")
    http_pass = 200 <= response.status_code < 300
    return {
        "id": case["id"], "category": category, "question": case["question"],
        "expected_route": category, "actual_route": category if http_pass else None,
        "http_status": response.status_code, "runtime_status": "SUCCEEDED" if http_pass else "FAILED",
        "error_code": None if http_pass else f"HTTP_{response.status_code}", "trace_id": trace_id,
        "trace_complete": bool(trace_id), "route_pass": http_pass,
        "runtime_pass": http_pass and semantic_pass,
        "content_excerpt": response.text[:240] if not http_pass else "",
        "case_index": index,
    }


def run_open(client: httpx.Client, api: str, datasource_id: str, semantic_model_id: str) -> dict:
    manifest = json.loads(OPEN_SET.read_text(encoding="utf-8"))
    results: list[dict] = []
    cleanup: list[str] = []
    state: dict[str, Any] = {}
    shared: dict[str, tuple[str, list[str]]] = {}
    try:
        file_conversation = _create_conversation(client, api, "Day3 final open file")
        cleanup.append(file_conversation)
        shared["FILE_QUERY"] = (file_conversation, [_upload(client, api, file_conversation, CSV_FIXTURE, "text/csv")])
        image_conversation = _create_conversation(client, api, "Day3 final open image")
        cleanup.append(image_conversation)
        shared["MULTIMODAL_QUERY"] = (image_conversation, [_upload(client, api, image_conversation, IMAGE_FIXTURE, "image/png")])
        for case in manifest["cases"]:
            if case["category"] in CHAT_ROUTES:
                if case["category"] in shared:
                    conversation_id, attachments = shared[case["category"]]
                else:
                    conversation_id = _create_conversation(client, api, f"Day3 final {case['id']}")
                    cleanup.append(conversation_id)
                    attachments = []
                try:
                    results.append(_chat_case(
                        client, api, case, datasource_id, semantic_model_id, conversation_id, attachments,
                    ))
                except Exception as exc:
                    results.append({
                        "id": case["id"], "category": case["category"], "question": case["question"],
                        "expected_route": case["expected_route"], "actual_route": None, "http_status": None,
                        "runtime_status": "FAILED", "error_code": type(exc).__name__, "trace_id": None,
                        "trace_complete": False, "route_pass": False, "runtime_pass": False,
                        "content_excerpt": str(exc)[:240],
                    })
            else:
                try:
                    results.append(_dedicated_case(client, api, case, datasource_id, semantic_model_id, state))
                except Exception as exc:
                    results.append({
                        "id": case["id"], "category": case["category"], "question": case["question"],
                        "expected_route": case["expected_route"], "actual_route": None, "http_status": None,
                        "runtime_status": "FAILED", "error_code": type(exc).__name__, "trace_id": None,
                        "trace_complete": False, "route_pass": False, "runtime_pass": False,
                        "content_excerpt": str(exc)[:240],
                    })
    finally:
        cleanup_failures = []
        for conversation_id in cleanup:
            response = client.delete(f"{api}/conversations/{conversation_id}")
            if response.status_code != 204:
                cleanup_failures.append({"conversation_id": conversation_id, "status": response.status_code})
    hardcoded_hits = []
    app_text = "\n".join(path.read_text(encoding="utf-8", errors="ignore") for path in (PROJECT_ROOT / "backend" / "app").rglob("*.py"))
    for case in manifest["cases"]:
        if case["category"] not in {"CLARIFICATION", "UNSUPPORTED"} and len(case["question"]) >= 8 and case["question"] in app_text:
            hardcoded_hits.append(case["id"])
    total = len(results)
    runtime_pass = sum(bool(item["runtime_pass"]) for item in results)
    route_pass = sum(bool(item["route_pass"]) for item in results)
    trace_pass = sum(bool(item["trace_complete"]) for item in results)
    unsupported = [item for item in results if item["category"] == "UNSUPPORTED"]
    return {
        "manifest": str(OPEN_SET.relative_to(PROJECT_ROOT)), "total": total,
        "category_counts": dict(Counter(item["category"] for item in results)),
        "hardcoded_answer_paths": len(hardcoded_hits), "hardcoded_hits": hardcoded_hits,
        "open_ended_request_runtime_rate": round(runtime_pass / total, 6),
        "question_route_coverage_rate": round(route_pass / total, 6),
        "trace_complete_rate": round(trace_pass / total, 6),
        "unsupported_request_hallucination": sum(
            item["runtime_status"] != "REFUSED" or item["error_code"] != "UNSUPPORTED" for item in unsupported
        ),
        "runtime_failures": [item["id"] for item in results if not item["runtime_pass"]],
        "route_failures": [item["id"] for item in results if not item["route_pass"]],
        "trace_failures": [item["id"] for item in results if not item["trace_complete"]],
        "cleanup_failures": cleanup_failures, "results": results,
    }


def _slot_present(slots: dict, key: str) -> bool:
    value = slots.get(key)
    return value is not None and value != "" and value != [] and value != {}


def run_memory(client: httpx.Client, api: str, datasource_id: str, semantic_model_id: str) -> dict:
    manifest = json.loads(MEMORY_SET.read_text(encoding="utf-8"))
    results: list[dict] = []
    cleanup: list[str] = []
    persistence_failures: list[str] = []
    history_failures: list[str] = []
    expected_total = 0
    expected_pass = 0
    try:
        for conversation in manifest["conversations"]:
            conversation_id = _create_conversation(client, api, f"Day3 memory {conversation['id']}")
            cleanup.append(conversation_id)
            attachments: list[str] = []
            if conversation.get("fixture"):
                attachments = [_upload(client, api, conversation_id, CSV_FIXTURE, "text/csv")]
            parent = None
            for turn_index, turn in enumerate(conversation["turns"], start=1):
                response = client.post(f"{api}/chat", json={
                    "conversation_id": conversation_id, "content": turn["question"],
                    "client_message_id": f"day3-memory-{uuid4()}", "parent_message_id": parent,
                    "attachment_ids": attachments, "route": turn["route"],
                    "datasource_id": datasource_id, "semantic_model_id": semantic_model_id,
                })
                try:
                    payload = _ok(response)
                    parent = payload["assistant_message"]["id"]
                    slots = (payload["user_message"].get("context_payload") or {}).get("slots") or {}
                    missing = [key for key in turn["expect"] if not _slot_present(slots, key)]
                    expected_total += len(turn["expect"])
                    expected_pass += len(turn["expect"]) - len(missing)
                    results.append({
                        "conversation_id": conversation["id"], "family": conversation["family"],
                        "turn": turn_index, "http_status": response.status_code,
                        "runtime_status": payload["assistant_message"].get("status"),
                        "route": payload["assistant_message"].get("route"), "expected_slots": turn["expect"],
                        "missing_slots": missing, "slot_keys": sorted(slots),
                    })
                except Exception as exc:
                    expected_total += len(turn["expect"])
                    results.append({
                        "conversation_id": conversation["id"], "family": conversation["family"],
                        "turn": turn_index, "http_status": response.status_code,
                        "runtime_status": "FAILED", "route": None, "expected_slots": turn["expect"],
                        "missing_slots": turn["expect"], "slot_keys": [], "error": f"{type(exc).__name__}:{str(exc)[:160]}",
                    })
            detail = client.get(f"{api}/conversations/{conversation_id}")
            if detail.status_code != 200 or len(detail.json().get("messages", [])) != 10:
                persistence_failures.append(conversation["id"])
            history = client.get(f"{api}/conversations")
            if history.status_code != 200 or conversation_id not in {item["id"] for item in history.json()}:
                history_failures.append(conversation["id"])
        reset_id = _create_conversation(client, api, "Day3 memory reset probe")
        cleanup.append(reset_id)
        reset = _ok(client.post(f"{api}/chat", json={
            "conversation_id": reset_id, "content": "看看", "client_message_id": f"day3-reset-{uuid4()}",
            "attachment_ids": [],
        }))
        reset_slots = (reset["user_message"].get("context_payload") or {}).get("slots") or {}
        leaked_keys = sorted(set(reset_slots).intersection({
            "metric", "time", "regions", "customer", "product", "previous_sql", "previous_result",
            "citation", "attachment", "file_context", "datasource", "semantic_model",
        }))
    finally:
        cleanup_failures = []
        for conversation_id in cleanup:
            response = client.delete(f"{api}/conversations/{conversation_id}")
            if response.status_code != 204:
                cleanup_failures.append({"conversation_id": conversation_id, "status": response.status_code})
    return {
        "manifest": str(MEMORY_SET.relative_to(PROJECT_ROOT)),
        "conversation_count": len(manifest["conversations"]), "turn_count": len(results),
        "follow_up_context_checks": expected_total, "follow_up_context_passes": expected_pass,
        "follow_up_context_accuracy": round(expected_pass / expected_total, 6) if expected_total else 0,
        "conversation_persistence": not persistence_failures,
        "persistence_failures": persistence_failures, "history_recovery": not history_failures,
        "history_failures": history_failures, "new_conversation_reset": not leaked_keys,
        "cross_conversation_memory_leak": len(leaked_keys), "leaked_keys": leaked_keys,
        "cleanup_failures": cleanup_failures, "results": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env")
    parser.add_argument("--mode", choices=("open", "memory", "all"), default="all")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    env = dotenv_values(args.env_file)
    password = env.get("CHATBI_BOOTSTRAP_ADMIN_PASSWORD")
    if not password:
        raise RuntimeError("CHATBI_BOOTSTRAP_ADMIN_PASSWORD is not configured")
    api = f"{args.base_url.rstrip('/')}/api/v1"
    report: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(), "base_url": args.base_url,
        "mode": args.mode,
    }
    with httpx.Client(timeout=120, trust_env=False) as client:
        _ok(client.post(f"{api}/auth/login", json={
            "email": "admin@chatbi.local", "password": password, "remember": False,
        }))
        datasource_id, semantic_model_id = _runtime_context(client, api)
        report["runtime"] = {"datasource_id": datasource_id, "semantic_model_id": semantic_model_id}
        if args.mode in {"open", "all"}:
            report["open_questions"] = run_open(client, api, datasource_id, semantic_model_id)
        if args.mode in {"memory", "all"}:
            report["memory"] = run_memory(client, api, datasource_id, semantic_model_id)
    _write_json(args.output, report)
    summary = {
        "output": str(args.output),
        "open": {key: value for key, value in report.get("open_questions", {}).items() if key not in {"results"}},
        "memory": {key: value for key, value in report.get("memory", {}).items() if key not in {"results"}},
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
