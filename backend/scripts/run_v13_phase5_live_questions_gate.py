from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Callable, Iterable, Mapping, Sequence
from urllib.parse import urlparse
from uuid import uuid4

import httpx
from dotenv import dotenv_values


BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
DEFAULT_WEIRD_MANIFEST = REPO_ROOT / "evaluation" / "golden" / "v13-phase5-weird-50.json"
DEFAULT_COMPLEX_MANIFEST = REPO_ROOT / "evaluation" / "golden" / "v13-phase5-complex-5.json"
_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
_TERMINAL_EVENTS = {"run.completed", "run.failed", "run.cancelled"}
_REFUSAL_ACTIONS = {
    "REFUSE",
    "REFUSE_INJECTION",
    "REFUSE_SQL_INJECTION",
    "REFUSE_UNAUTHORIZED",
    "REFUSE_UNBOUNDED",
}
_CLARIFICATION_ACTIONS = {
    "ASK_CLARIFICATION",
    "UNKNOWN_METRIC_CLARIFICATION",
    "UNKNOWN_ENTITY_CLARIFICATION",
}
_TEXT_KEYS = {"answer", "conclusion", "content", "insight", "markdown", "summary", "text"}
_REFUSAL_PATTERNS = (
    "不能", "无法", "拒绝", "不支持", "无权", "没有权限", "cannot", "can't", "refuse", "unsupported",
)
_CLARIFICATION_PATTERNS = (
    "请明确", "请补充", "请提供", "需要明确", "需要补充", "clarify", "which metric", "what metric", "?", "？",
)
_NO_EVIDENCE_PATTERNS = (
    "没有证据", "无证据", "未找到", "不存在", "无法验证", "证据不足", "未返回数据", "没有数据", "无数据",
    "no evidence", "not found", "cannot verify", "no rows", "no data",
)
_BUSINESS_MARKERS = (
    "收入", "营收", "成本", "利润", "毛利", "订单", "退款", "客户", "预算", "销量", "revenue", "cost",
    "profit", "orders", "margin", "sales", "budget",
)
_ASSERTION_MARKERS = (
    "达到", "为", "是", "增长", "下降", "增加", "减少", "最高", "最低", "同比", "环比", "approved", "grew",
    "increased", "decreased", "equals", " is ",
)


class LiveGateError(RuntimeError):
    pass


@dataclass
class CleanupTracker:
    conversations: list[str] = field(default_factory=list)
    attachments: list[str] = field(default_factory=list)
    authenticated: bool = False


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_text(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))


def git_sha() -> str | None:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    value = completed.stdout.strip()
    return value if completed.returncode == 0 and len(value) == 40 else None


def validate_backend_url(value: str) -> str:
    parsed = urlparse(value.strip())
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in _LOCAL_HOSTS:
        raise ValueError("Phase5 live questions gate requires a loopback HTTP(S) Backend")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Backend URL cannot contain credentials, query or fragment")
    path = parsed.path.rstrip("/")
    if path and path != "/api/v1":
        raise ValueError("Backend URL path must be empty or /api/v1")
    return f"{parsed.scheme}://{parsed.netloc}/api/v1"


def load_external_credentials(path: Path) -> dict[str, str]:
    resolved = path.expanduser().resolve()
    if resolved.is_relative_to(REPO_ROOT.resolve()):
        raise ValueError("--env-file must be outside the repository")
    values = dotenv_values(resolved)
    email = str(values.get("CHATBI_PHASE5_EMAIL") or "").strip()
    password = str(values.get("CHATBI_PHASE5_PASSWORD") or "")
    if not email or not password:
        raise ValueError("external env-file requires CHATBI_PHASE5_EMAIL and CHATBI_PHASE5_PASSWORD")
    return {"email": email, "password": password}


def load_manifest(path: Path, *, expected_count: int) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    cases = payload.get("cases") if isinstance(payload, dict) else None
    if payload.get("frozen") is not True or not isinstance(cases, list) or len(cases) != expected_count:
        raise ValueError(f"{path.name} must be frozen with exactly {expected_count} cases")
    if len({str(case.get("id")) for case in cases}) != expected_count:
        raise ValueError(f"{path.name} case IDs must be unique")
    if expected_count == 50:
        actions = {str((case.get("expected") or {}).get("action") or "") for case in cases}
        contracts = payload.get("answer_contracts") or {}
        if set(contracts) != actions:
            raise ValueError(f"{path.name} must freeze one answer contract per action")
        if any((case.get("expected") or {}).get("hallucination_allowed") is not False for case in cases):
            raise ValueError(f"{path.name} must fail closed on hallucination")
    if expected_count == 5:
        if any(
            set(((case.get("expected") or {}).get("expected_evidence") or {}))
            != {"result", "citation", "file", "sandbox"}
            for case in cases
        ):
            raise ValueError(f"{path.name} must freeze result/citation/file/sandbox evidence")
    return payload


def _request_json(
    client: httpx.Client,
    method: str,
    path: str,
    *,
    expected: Iterable[int],
    **kwargs: Any,
) -> Any:
    response = client.request(method, path, **kwargs)
    if response.status_code not in set(expected):
        raise LiveGateError(f"HTTP_{response.status_code}:{method}:{path.split('?', 1)[0]}")
    if response.status_code == 204:
        return None
    try:
        return response.json()
    except ValueError as exc:
        raise LiveGateError(f"INVALID_JSON:{method}:{path.split('?', 1)[0]}") from exc


def _nested_values(value: Any, key: str) -> list[Any]:
    found: list[Any] = []
    if isinstance(value, Mapping):
        for item_key, item_value in value.items():
            if str(item_key) == key:
                found.append(item_value)
            found.extend(_nested_values(item_value, key))
    elif isinstance(value, list):
        for item in value:
            found.extend(_nested_values(item, key))
    return found


def _answer_text(response: Mapping[str, Any]) -> str:
    fragments: list[str] = []

    def visit(value: Any, *, key: str = "") -> None:
        if isinstance(value, Mapping):
            for item_key, item_value in value.items():
                visit(item_value, key=str(item_key).lower())
        elif isinstance(value, list):
            for item in value:
                visit(item, key=key)
        elif isinstance(value, str) and key in _TEXT_KEYS and value.strip():
            fragments.append(value.strip())

    visit(response.get("assistant_message") or {})
    visit(response.get("answer_envelope") or {})
    visit(response.get("message_parts") or [])
    return "\n".join(dict.fromkeys(fragments))


def _answer_oracle(response: Mapping[str, Any], verification: Mapping[str, Any]) -> dict[str, Any]:
    text_value = _answer_text(response)
    lowered = text_value.lower()
    refusal_detected = any(pattern in lowered for pattern in _REFUSAL_PATTERNS)
    clarification_detected = any(pattern in lowered for pattern in _CLARIFICATION_PATTERNS)
    no_evidence_detected = any(pattern in lowered for pattern in _NO_EVIDENCE_PATTERNS)
    numeric_claim = re.search(r"(?<![A-Za-z])[-+]?\d+(?:[.,]\d+)?%?", text_value) is not None
    business_context = any(marker in lowered for marker in _BUSINESS_MARKERS)
    assertive = numeric_claim or any(marker in lowered for marker in _ASSERTION_MARKERS)
    business_claim = business_context and assertive and not (
        refusal_detected or clarification_detected or no_evidence_detected
    )
    answer_claim = bool(text_value.strip()) and not (
        refusal_detected or clarification_detected or no_evidence_detected
    )
    date_claim = re.search(
        r"(?:20\d{2}[-年/.]\d{1,2}(?:[-月/.]\d{1,2})?|星期[一二三四五六日天]|monday|tuesday|wednesday|thursday|friday|saturday|sunday)",
        lowered,
    ) is not None
    return {
        "answer_present": bool(text_value.strip()),
        "answer_sha256": sha256_text(text_value),
        "numeric_claim_present": numeric_claim,
        "answer_claim_present": answer_claim,
        "business_claim_present": business_claim,
        "date_claim_present": date_claim,
        "refusal_detected": refusal_detected,
        "clarification_detected": clarification_detected,
        "no_evidence_detected": no_evidence_detected,
        "verified_evidence_present": bool(
            verification.get("result_verified") or verification.get("citation_verified")
        ),
    }


def _named_values(value: Any, key: str) -> set[str]:
    values: set[str] = set()
    for item in _nested_values(value, key):
        items = item if isinstance(item, list) else [item]
        for candidate in items:
            if isinstance(candidate, Mapping):
                name = candidate.get("name") or candidate.get("code") or candidate.get("id")
                if name:
                    values.add(str(name))
            elif candidate is not None:
                values.add(str(candidate))
    return values


def _first_mapping(value: Any, key: str) -> dict[str, Any]:
    return next((item for item in _nested_values(value, key) if isinstance(item, dict)), {})


def _analysis_primary(response: Mapping[str, Any]) -> dict[str, Any]:
    assistant = response.get("assistant_message") or {}
    payload = assistant.get("response_payload") or {}
    analysis = payload.get("analysis") or {}
    primary = analysis.get("primary") or payload.get("primary") or {}
    return primary if isinstance(primary, dict) else {}


def _trace_id(response: Mapping[str, Any]) -> str:
    envelope = response.get("answer_envelope") or {}
    assistant = response.get("assistant_message") or {}
    trace = assistant.get("trace_payload") or {}
    value = envelope.get("trace_id") or trace.get("trace_id")
    if not value:
        raise LiveGateError("CHAT_RESPONSE_TRACE_ID_MISSING")
    return str(value)


def _route(response: Mapping[str, Any]) -> str:
    assistant = response.get("assistant_message") or {}
    envelope = response.get("answer_envelope") or {}
    return str(assistant.get("route") or envelope.get("route") or "")


def _answer_status(response: Mapping[str, Any]) -> str:
    return str((response.get("assistant_message") or {}).get("status") or "UNKNOWN")


def _ledger_for_request(
    client: httpx.Client,
    *,
    conversation_id: str,
    request_id: str,
) -> dict[str, Any]:
    dashboard = _request_json(
        client,
        "GET",
        "/governance/cost",
        expected={200},
        params={"conversation_id": conversation_id},
    )
    coverage = dashboard.get("coverage") or {}
    entries = [
        item for item in dashboard.get("entries") or []
        if str(item.get("request_id") or "") == request_id
        and str(item.get("conversation_id") or "") == conversation_id
    ]
    return {
        "coverage_source": coverage.get("source"),
        "coverage_complete": coverage.get("complete") is True,
        "request_id_exact": all(item.get("request_id") == request_id for item in entries),
        "invocation_count": len(entries),
        "cost_cny": round(sum(float(item.get("cost_cny") or 0) for item in entries), 8),
        "input_tokens": sum(int(item.get("input_tokens") or 0) for item in entries),
        "output_tokens": sum(int(item.get("output_tokens") or 0) for item in entries),
        "retry_count": sum(int(item.get("retry_count") or 0) for item in entries),
        "fallback_count": sum(int(item.get("fallback_count") or 0) for item in entries),
        "statuses": [str(item.get("status") or "") for item in entries],
        "providers": [str(item.get("provider") or "") for item in entries],
    }


def _trace_evidence(client: httpx.Client, trace_id: str) -> dict[str, Any]:
    detail = _request_json(client, "GET", f"/governance/traces/{trace_id}", expected={200})
    summary = detail.get("trace") or {}
    stages = detail.get("stages") or []
    return {
        "coverage_source": (detail.get("coverage") or {}).get("source"),
        "trace_id_exact": summary.get("trace_id") == trace_id,
        "status": summary.get("status"),
        "duration_ms": int(summary.get("duration_ms") or 0),
        "stage_count": int(summary.get("stage_count") or len(stages)),
        "stages": [str(item.get("stage") or "") for item in stages],
        "tools": sorted({
            str(item.get("tool")) for item in stages if item.get("tool")
        } | {str(item) for item in summary.get("tools") or []}),
        "has_sql": bool(summary.get("has_sql")),
        "has_rag": bool(summary.get("has_rag")),
        "has_agent": bool(summary.get("has_agent")),
        "has_file": bool(summary.get("has_file")),
        "has_vision": bool(summary.get("has_vision")),
        "error_code": summary.get("error_code"),
    }


def _optional_trace_evidence(client: httpx.Client, trace_id: str) -> dict[str, Any]:
    response = client.get(f"/governance/traces/{trace_id}")
    if response.status_code == 404:
        return {"available": False, "trace_id_exact": False, "status": None}
    if response.status_code != 200:
        raise LiveGateError(f"HTTP_{response.status_code}:GET:/governance/traces/TRACE_ID")
    detail = response.json()
    summary = detail.get("trace") or {}
    return {
        "available": True,
        "coverage_source": (detail.get("coverage") or {}).get("source"),
        "trace_id_exact": summary.get("trace_id") == trace_id,
        "status": summary.get("status"),
        "stage_count": int(summary.get("stage_count") or len(detail.get("stages") or [])),
    }


def _verification_evidence(response: Mapping[str, Any]) -> dict[str, Any]:
    primary = _analysis_primary(response)
    envelope = response.get("answer_envelope") or {}
    verification = primary.get("verification") if isinstance(primary, dict) else {}
    if not isinstance(verification, dict):
        verification = {}
    oracle_statuses = [
        str(item.get("status") or "")
        for item in _nested_values(primary, "oracle")
        if isinstance(item, Mapping) and str(item.get("status") or "") == "PASSED"
    ]
    result_signatures = [str(item) for item in _nested_values(primary, "result_signature") if item]
    citation_ids = [str(item) for item in _nested_values(primary, "citation_id") if item]
    envelope_verification = envelope.get("verification") or {}
    status = str(envelope_verification.get("status") or "")
    result_verified = bool(verification.get("result_verified")) or status == "VERIFIED" or bool(oracle_statuses)
    citation_verified = bool(verification.get("citation_verified")) or bool(citation_ids)
    return {
        "result_verified": result_verified,
        "citation_verified": citation_verified,
        "oracle_passed_count": len(oracle_statuses),
        "result_signature_count": len(set(result_signatures)),
        "citation_count": len(set(citation_ids)),
        "envelope_status": status or None,
    }


def _common_failures(
    *,
    expected_route: str,
    model_calls_max: int,
    cost_cny_max: float,
    route: str,
    ledger: Mapping[str, Any],
    trace: Mapping[str, Any],
    assistant_status: str,
) -> list[str]:
    failures: list[str] = []
    if route != expected_route:
        failures.append("route_mismatch")
    if ledger["coverage_source"] != "MODEL_INVOCATION_LEDGER" or not ledger["coverage_complete"]:
        failures.append("model_invocation_ledger_incomplete")
    if not ledger["request_id_exact"]:
        failures.append("model_invocation_request_id_mismatch")
    if ledger["invocation_count"] > int(model_calls_max):
        failures.append("model_call_budget_exceeded")
    if float(ledger["cost_cny"]) > float(cost_cny_max):
        failures.append("cost_budget_exceeded")
    if any(status != "SUCCEEDED" for status in ledger["statuses"]):
        failures.append("model_invocation_not_succeeded")
    if trace["trace_id_exact"] is not True:
        failures.append("trace_id_mismatch")
    if str(trace.get("status") or "") != "SUCCEEDED":
        failures.append("trace_not_succeeded")
    if assistant_status != "SUCCEEDED":
        failures.append("assistant_not_succeeded")
    return failures


def _action_failures(
    *,
    case: Mapping[str, Any],
    response: Mapping[str, Any],
    route: str,
    ledger: Mapping[str, Any],
    trace: Mapping[str, Any],
    verification: Mapping[str, Any],
    answer_oracle: Mapping[str, Any],
) -> list[str]:
    expected = case["expected"]
    action = str(expected["action"])
    contract = case.get("expected_answer_contract") or {}
    failures = _common_failures(
        expected_route=str(expected["route"]),
        model_calls_max=int(expected["model_calls_max"]),
        cost_cny_max=float(expected["cost_cny_max"]),
        route=route,
        ledger=ledger,
        trace=trace,
        assistant_status=_answer_status(response),
    )
    if not expected["sql_execution_allowed"] and trace["has_sql"]:
        failures.append("unexpected_sql_execution")
    if not answer_oracle["answer_present"]:
        failures.append("answer_text_missing")
    if contract.get("refusal_required") and not answer_oracle["refusal_detected"]:
        failures.append("refusal_answer_missing")
    if contract.get("clarification_required") and not answer_oracle["clarification_detected"]:
        failures.append("clarification_answer_missing")
    if contract.get("no_evidence_required") and not answer_oracle["no_evidence_detected"]:
        failures.append("no_evidence_disclosure_missing")
    if contract.get("verified_evidence_required") and not answer_oracle["verified_evidence_present"]:
        failures.append("verified_answer_evidence_missing")
    claim_mode = str(contract.get("claim_mode") or "")
    if claim_mode == "NONE" and answer_oracle["answer_claim_present"]:
        failures.append("answer_claim_forbidden")
    if claim_mode == "DATE_ONLY" and not answer_oracle["date_claim_present"]:
        failures.append("date_answer_missing")
    if claim_mode == "EMPTY_ONLY" and answer_oracle["business_claim_present"]:
        failures.append("empty_result_fabricated_claim")
    if claim_mode == "VERIFIED_ONLY" and not answer_oracle["answer_claim_present"]:
        failures.append("verified_answer_claim_missing")
    if expected["hallucination_allowed"] is not False:
        failures.append("hallucination_policy_not_fail_closed")
    elif answer_oracle["business_claim_present"] and not answer_oracle["verified_evidence_present"]:
        failures.append("unverified_business_claim")
    if action == "MODEL_NONE_DATE" and (ledger["invocation_count"] != 0 or ledger["cost_cny"] != 0):
        failures.append("date_trap_called_model")
    if action == "EMPTY_RESULT_NO_FABRICATION":
        semantic = str(response.get("result_semantic") or "")
        if semantic not in {"ZERO", "NO_ROWS", "NULL_VALUE"}:
            failures.append("empty_result_semantic_missing")
    if action == "NO_EVIDENCE_NO_CLAIM" and response.get("result_semantic") == "VALUE":
        failures.append("unsupported_claim_without_evidence")
    if action in {"QUERY_READ_ONLY", "BOUNDED_VERIFIED_ANALYSIS"} and not verification["result_verified"]:
        failures.append("result_verification_missing")
    return failures


def _sse_events(response: httpx.Response) -> Iterable[dict[str, Any]]:
    def decode(event_name: str | None, data_lines: list[str]) -> dict[str, Any] | None:
        if not event_name or not data_lines:
            return None
        try:
            payload = json.loads("\n".join(data_lines))
        except json.JSONDecodeError as exc:
            raise LiveGateError("INVALID_SSE_JSON") from exc
        if payload.get("event_type") != event_name:
            raise LiveGateError("SSE_EVENT_NAME_MISMATCH")
        return payload

    event_name: str | None = None
    data_lines: list[str] = []
    for line in response.iter_lines():
        if line == "":
            payload = decode(event_name, data_lines)
            if payload is not None:
                yield payload
            event_name = None
            data_lines = []
        elif line.startswith("event:"):
            event_name = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            data_lines.append(line.split(":", 1)[1].strip())
    payload = decode(event_name, data_lines)
    if payload is not None:
        yield payload


class LiveQuestionsGate:
    def __init__(
        self,
        client: httpx.Client,
        *,
        datasource_id: str,
        semantic_model_id: str,
        credentials: Mapping[str, str],
        secret_values: Sequence[str],
    ) -> None:
        self.client = client
        self.datasource_id = datasource_id
        self.semantic_model_id = semantic_model_id
        self.credentials = credentials
        self.secret_values = tuple(value for value in secret_values if value)
        self.cleanup_tracker = CleanupTracker()

    def login(self) -> dict[str, Any]:
        payload = _request_json(
            self.client,
            "POST",
            "/auth/login",
            expected={200},
            json={"email": self.credentials["email"], "password": self.credentials["password"], "remember": False},
        )
        self.cleanup_tracker.authenticated = True
        evidence = {
            "authenticated": payload.get("authenticated") is True,
            "user_id_sha256": sha256_text(str((payload.get("user") or {}).get("id") or "")),
            "workspace_id_sha256": sha256_text(str((payload.get("user") or {}).get("workspace_id") or "")),
        }
        return evidence

    def create_conversation(self, case_id: str, *, suffix: str = "run") -> str:
        payload = _request_json(
            self.client,
            "POST",
            "/conversations",
            expected={201},
            json={"title": f"V1.3 Phase5 {case_id} {suffix}"},
        )
        conversation_id = str(payload["id"])
        self.cleanup_tracker.conversations.append(conversation_id)
        return conversation_id

    def upload_attachment(self, conversation_id: str, attachment: Mapping[str, Any] | None) -> list[str]:
        if not attachment:
            return []
        path = (REPO_ROOT / str(attachment["path"])).resolve()
        if not path.is_relative_to(REPO_ROOT.resolve()) or not path.is_file():
            raise LiveGateError("ATTACHMENT_FIXTURE_INVALID")
        payload = _request_json(
            self.client,
            "POST",
            "/attachments",
            expected={201},
            data={"conversation_id": conversation_id},
            files={"file": (path.name, path.read_bytes(), str(attachment["mime_type"]))},
        )
        attachment_id = str(payload["id"])
        self.cleanup_tracker.attachments.append(attachment_id)
        return [attachment_id]

    def run_question(self, case: Mapping[str, Any], *, explicit_route: bool) -> dict[str, Any]:
        conversation_id = self.create_conversation(str(case["id"]))
        attachment_ids = self.upload_attachment(conversation_id, case.get("attachment"))
        request_id = f"P5-{case['id']}-{uuid4().hex}"
        request_payload: dict[str, Any] = {
            "conversation_id": conversation_id,
            "client_message_id": request_id,
            "content": str(case["question"]),
            "attachment_ids": attachment_ids,
            "datasource_id": self.datasource_id,
            "semantic_model_id": self.semantic_model_id,
        }
        if explicit_route:
            request_payload["route"] = str(case["route"])
        started = perf_counter()
        response = _request_json(self.client, "POST", "/chat", expected={201}, json=request_payload)
        http_total_ms = round((perf_counter() - started) * 1000, 3)
        serialized = json.dumps(response, ensure_ascii=False, sort_keys=True)
        if any(secret in serialized for secret in self.secret_values):
            raise LiveGateError("SECRET_LEAK_IN_CHAT_RESPONSE")
        trace_id = _trace_id(response)
        route = _route(response)
        ledger = _ledger_for_request(
            self.client,
            conversation_id=conversation_id,
            request_id=request_id,
        )
        trace = _trace_evidence(self.client, trace_id)
        verification = _verification_evidence(response)
        answer_oracle = _answer_oracle(response, verification)
        if explicit_route:
            expected = case["expected"]
            failures = _common_failures(
                expected_route=str(case["route"]),
                model_calls_max=int(expected["model_calls_max"]),
                cost_cny_max=float(expected["max_cost_cny"]),
                route=route,
                ledger=ledger,
                trace=trace,
                assistant_status=_answer_status(response),
            )
        else:
            failures = _action_failures(
                case=case,
                response=response,
                route=route,
                ledger=ledger,
                trace=trace,
                verification=verification,
                answer_oracle=answer_oracle,
            )
        evidence = {
            "id": case["id"],
            "category": case.get("category") or case.get("kind"),
            "question_sha256": sha256_text(str(case["question"])),
            "request_id": request_id,
            "conversation_id": conversation_id,
            "trace_id": trace_id,
            "expected_route": case.get("route") or (case.get("expected") or {}).get("route"),
            "actual_route": route,
            "assistant_status": _answer_status(response),
            "result_semantic": response.get("result_semantic"),
            "http_total_ms": http_total_ms,
            "ledger": ledger,
            "trace": trace,
            "verification": verification,
            "answer_oracle": answer_oracle,
            "failures": failures,
            "status": "PASS" if not failures else "FAIL",
        }
        if explicit_route:
            evidence["response_primary"] = _analysis_primary(response)
        return evidence

    def cancel_probe(self, case: Mapping[str, Any]) -> dict[str, Any]:
        conversation_id = self.create_conversation(str(case["id"]), suffix="cancel")
        attachment_ids = self.upload_attachment(conversation_id, case.get("attachment"))
        request_id = f"P5-CANCEL-{case['id']}-{uuid4().hex}"
        payload = {
            "conversation_id": conversation_id,
            "client_message_id": request_id,
            "content": str(case["question"]),
            "attachment_ids": attachment_ids,
            "datasource_id": self.datasource_id,
            "semantic_model_id": self.semantic_model_id,
            "route": str(case["route"]),
        }
        events: list[dict[str, Any]] = []
        cancel_status: int | None = None
        with self.client.stream("POST", "/chat/stream", json=payload) as response:
            if response.status_code != 200:
                raise LiveGateError(f"HTTP_{response.status_code}:POST:/chat/stream")
            for event in _sse_events(response):
                events.append(event)
                if event["event_type"] == "run.started" and cancel_status is None:
                    cancel = self.client.post(
                        "/chat/stream/cancel",
                        json={"conversation_id": conversation_id, "client_message_id": request_id},
                    )
                    cancel_status = cancel.status_code
        terminals = [item for item in events if item.get("event_type") in _TERMINAL_EVENTS]
        trace_ids = {str(item.get("trace_id") or "") for item in events if item.get("trace_id")}
        request_ids = {str(item.get("request_id") or "") for item in events if item.get("request_id")}
        trace_id = next(iter(trace_ids), "") if len(trace_ids) == 1 else ""
        terminal_index = next(
            (index for index, item in enumerate(events) if item.get("event_type") in _TERMINAL_EVENTS),
            None,
        )
        post_terminal_event_count = 0 if terminal_index is None else len(events) - terminal_index - 1
        ledger = _ledger_for_request(
            self.client,
            conversation_id=conversation_id,
            request_id=request_id,
        )
        trace = _optional_trace_evidence(self.client, trace_id) if trace_id else {
            "available": False, "trace_id_exact": False, "status": None,
        }
        conversation = _request_json(
            self.client,
            "GET",
            f"/conversations/{conversation_id}",
            expected={200},
        )
        messages = conversation.get("messages") or []
        matching_messages = [
            item for item in messages
            if request_id in json.dumps(item, ensure_ascii=False)
            or (trace_id and trace_id in json.dumps(item, ensure_ascii=False))
            or (
                str(item.get("role") or "") == "user"
                and str(item.get("content") or "") == str(case["question"])
            )
        ]
        stale_succeeded_assistants = [
            item for item in matching_messages
            if str(item.get("role") or "") == "assistant"
            and str(item.get("status") or "") in {"SUCCEEDED", "PARTIAL"}
        ]
        diagnostics_response = self.client.get("/chat/stream/diagnostics")
        if diagnostics_response.status_code == 200:
            diagnostics_payload = diagnostics_response.json()
            diagnostic_trace_ids = [str(item) for item in diagnostics_payload.get("trace_ids") or []]
            diagnostics = {
                "available": True,
                "trace_released": trace_id not in diagnostic_trace_ids,
                "active_connections": int(diagnostics_payload.get("active_connections") or 0),
                "active_tasks": int(diagnostics_payload.get("active_tasks") or 0),
            }
        elif diagnostics_response.status_code in {403, 404}:
            diagnostics = {"available": False, "trace_released": None}
        else:
            raise LiveGateError(
                f"HTTP_{diagnostics_response.status_code}:GET:/chat/stream/diagnostics"
            )
        failures: list[str] = []
        if cancel_status != 202:
            failures.append("cancel_ack_not_202")
        if len(terminals) != 1:
            failures.append("terminal_count_not_one")
        elif terminals[0]["event_type"] != "run.cancelled":
            failures.append("cancel_terminal_mismatch")
        if post_terminal_event_count != 0:
            failures.append("event_after_terminal")
        if len(trace_ids) != 1:
            failures.append("cancel_trace_identity_mismatch")
        if request_ids != {request_id}:
            failures.append("cancel_request_identity_mismatch")
        if ledger["coverage_source"] != "MODEL_INVOCATION_LEDGER" or not ledger["coverage_complete"]:
            failures.append("cancel_ledger_incomplete")
        if not ledger["request_id_exact"] or ledger["invocation_count"] < 1:
            failures.append("cancel_ledger_request_missing")
        if not ledger["statuses"] or any(status != "CANCELLED" for status in ledger["statuses"]):
            failures.append("cancel_ledger_status_mismatch")
        if float(ledger["cost_cny"]) > float(case["expected"]["max_cost_cny"]):
            failures.append("cancel_cost_budget_exceeded")
        if trace["available"] and (
            trace["trace_id_exact"] is not True or str(trace.get("status") or "") != "CANCELLED"
        ):
            failures.append("cancel_trace_not_cancelled")
        if messages:
            failures.append("cancelled_messages_not_cleaned")
        if stale_succeeded_assistants:
            failures.append("cancel_stale_answer_persisted")
        if diagnostics["available"] and diagnostics["trace_released"] is not True:
            failures.append("cancel_stream_resources_not_released")
        return {
            "request_id": request_id,
            "conversation_id": conversation_id,
            "cancel_ack_status": cancel_status,
            "event_count": len(events),
            "terminal_count": len(terminals),
            "terminal_event": terminals[0]["event_type"] if len(terminals) == 1 else None,
            "post_terminal_event_count": post_terminal_event_count,
            "stream_eof_observed": True,
            "trace_id": trace_id or None,
            "ledger": ledger,
            "governance_trace": trace,
            "conversation_state": {
                "message_count": len(messages),
                "matching_cancelled_message_count": len(matching_messages),
                "stale_succeeded_assistant_count": len(stale_succeeded_assistants),
            },
            "stream_diagnostics": diagnostics,
            "failures": failures,
            "status": "PASS" if not failures else "FAIL",
        }

    def validate_complex(self, case: Mapping[str, Any], evidence: dict[str, Any]) -> list[str]:
        expected = case["expected"]
        primary = evidence.pop("response_primary")
        steps = primary.get("steps") or []
        actual_sequence = [
            {
                "ordinal": step.get("ordinal"),
                "agent_role": step.get("agent_role"),
                "tool_name": step.get("tool_name"),
            }
            for step in steps
        ]
        expected_sequence = [
            {
                "ordinal": step["ordinal"],
                "agent_role": step["role"],
                "tool_name": step.get("tool"),
            }
            for step in case["steps"]
        ]
        actual_tools = [str(item["tool_name"]) for item in actual_sequence if item["tool_name"]]
        actual_roles = [str(item["agent_role"]) for item in actual_sequence]
        expected_tools = [str(step["tool"]) for step in case["steps"] if step.get("tool")]
        trace_tools = set(evidence["trace"]["tools"])
        observed_tools = set(actual_tools) | trace_tools
        failures: list[str] = list(evidence["failures"])
        if actual_sequence != expected_sequence:
            failures.append("complex_step_role_tool_sequence_mismatch")
        if any(str(step.get("status") or "") != "SUCCEEDED" for step in steps):
            failures.append("complex_step_not_succeeded")
        if len(steps) > int(expected["max_steps"]):
            failures.append("complex_step_budget_exceeded")
        if len(actual_tools) > int(expected["max_tool_calls"]):
            failures.append("complex_tool_budget_exceeded")
        if set(actual_tools) != set(expected_tools) or trace_tools != set(expected_tools):
            failures.append("complex_tool_trace_not_exact")
        total_latency_ms = max(evidence["http_total_ms"], evidence["trace"]["duration_ms"])
        performance = primary.get("performance") or {}
        total_latency_ms = max(total_latency_ms, int(performance.get("total_latency_ms") or 0))
        if total_latency_ms > int(expected["max_latency_ms"]):
            failures.append("complex_latency_budget_exceeded")
        if float(evidence["ledger"]["cost_cny"]) > float(expected["max_cost_cny"]):
            failures.append("complex_cost_budget_exceeded")
        if expected["verification_required"] and not evidence["verification"]["result_verified"]:
            failures.append("complex_result_verification_missing")
        if case["kind"] == "DATA_RAG" and not evidence["verification"]["citation_verified"]:
            failures.append("complex_citation_verification_missing")
        if not evidence["answer_oracle"]["answer_present"]:
            failures.append("complex_answer_text_missing")
        elif not evidence["answer_oracle"]["answer_claim_present"]:
            failures.append("complex_answer_claim_missing")

        frozen = expected["expected_evidence"]
        result_contract = frozen["result"]
        result_payload = _first_mapping(primary, "result_evidence")
        metrics = _named_values(result_payload, "metrics")
        dimensions = _named_values(result_payload, "dimensions")
        row_counts = [
            int(value) for value in _nested_values(result_payload, "row_count")
            if isinstance(value, (int, float)) or str(value).isdigit()
        ]
        result_evidence = {
            "result_semantic": evidence["result_semantic"],
            "oracle_status": "PASSED" if evidence["verification"]["oracle_passed_count"] else None,
            "metrics": sorted(metrics),
            "dimensions": sorted(dimensions),
            "maximum_row_count": max(row_counts, default=0),
        }
        if result_evidence["result_semantic"] != result_contract["result_semantic"]:
            failures.append("complex_frozen_result_semantic_mismatch")
        if result_evidence["oracle_status"] != result_contract["oracle_status"]:
            failures.append("complex_frozen_oracle_status_mismatch")
        if not set(result_contract["required_metrics"]).issubset(metrics):
            failures.append("complex_frozen_metric_evidence_missing")
        if not set(result_contract["required_dimensions"]).issubset(dimensions):
            failures.append("complex_frozen_dimension_evidence_missing")
        if result_evidence["maximum_row_count"] < int(result_contract["minimum_row_count"]):
            failures.append("complex_frozen_row_evidence_missing")

        citation_contract = frozen["citation"]
        citation_titles: list[str] = []
        for citation_container in _nested_values(primary, "citations"):
            citation_titles.extend(
                str(value) for value in _nested_values(citation_container, "title") if value
            )
        citation_text = " ".join(citation_titles)
        if citation_contract["required"]:
            if len(citation_titles) < int(citation_contract["minimum_count"]):
                failures.append("complex_frozen_citation_count_missing")
            if any(term not in citation_text for term in citation_contract["required_title_terms"]):
                failures.append("complex_frozen_citation_terms_missing")

        file_contract = frozen["file"]
        file_evidence = _first_mapping(primary, "file_evidence")
        if file_contract["required"]:
            observed_file = {
                "required": True,
                "sha256": str(file_evidence.get("sha256") or ""),
                "row_count": int(file_evidence.get("row_count") or 0),
                "columns": list(file_evidence.get("columns") or []),
                "revenue_sum": file_evidence.get("revenue_sum"),
                "cost_sum": file_evidence.get("cost_sum"),
            }
            if observed_file != file_contract:
                failures.append("complex_frozen_file_evidence_mismatch")
        else:
            observed_file = {"required": False}

        sandbox_contract = frozen["sandbox"]
        sandbox_evidence = _first_mapping(primary, "sandbox_evidence")
        if sandbox_contract["required"]:
            observed_sandbox = {
                "required": True,
                "status": sandbox_evidence.get("status"),
                "runtime_verified": sandbox_evidence.get("runtime_verified") is True,
                "container_destroyed": sandbox_evidence.get("container_destroyed") is True,
                "operation": sandbox_evidence.get("operation"),
            }
            if observed_sandbox != sandbox_contract:
                failures.append("complex_frozen_sandbox_evidence_mismatch")
        else:
            observed_sandbox = {"required": False}
        evidence["observed"] = {
            "step_count": len(steps),
            "steps": [
                {
                    "ordinal": step.get("ordinal"),
                    "agent_role": step.get("agent_role"),
                    "tool_name": step.get("tool_name"),
                    "status": step.get("status"),
                    "duration_ms": step.get("duration_ms"),
                }
                for step in steps
            ],
            "tools": sorted(observed_tools),
            "roles": sorted(set(actual_roles)),
            "total_latency_ms": total_latency_ms,
            "accuracy_metric": expected["accuracy_metric"],
            "frozen_result_evidence": result_evidence,
            "frozen_citation_titles_sha256": [sha256_text(item) for item in citation_titles],
            "frozen_file_evidence": observed_file,
            "frozen_sandbox_evidence": observed_sandbox,
            "accuracy_evidence_passed": not any(
                item.startswith("complex_frozen_") or "accuracy" in item or "verification" in item
                for item in failures
            ),
        }
        return list(dict.fromkeys(failures))

    def cleanup(self) -> dict[str, Any]:
        counts = {
            "attachment_delete_204": 0,
            "attachment_absence_404": 0,
            "conversation_delete_204": 0,
            "conversation_absence_404": 0,
            "logout_204": 0,
        }
        errors: list[str] = []
        for attachment_id in reversed(self.cleanup_tracker.attachments):
            try:
                deleted = self.client.delete(f"/attachments/{attachment_id}")
                absent = self.client.get(f"/attachments/{attachment_id}")
                counts["attachment_delete_204"] += deleted.status_code == 204
                counts["attachment_absence_404"] += absent.status_code == 404
                verified = deleted.status_code == 204 and absent.status_code == 404
            except httpx.HTTPError:
                verified = False
            if not verified:
                errors.append("attachment_cleanup_failed")
        for conversation_id in reversed(self.cleanup_tracker.conversations):
            try:
                deleted = self.client.delete(f"/conversations/{conversation_id}")
                absent = self.client.get(f"/conversations/{conversation_id}")
                counts["conversation_delete_204"] += deleted.status_code == 204
                counts["conversation_absence_404"] += absent.status_code == 404
                verified = deleted.status_code == 204 and absent.status_code == 404
            except httpx.HTTPError:
                verified = False
            if not verified:
                errors.append("conversation_cleanup_failed")
        if self.cleanup_tracker.authenticated:
            try:
                logout = self.client.post("/auth/logout")
                counts["logout_204"] = int(logout.status_code == 204)
                verified = logout.status_code == 204
            except httpx.HTTPError:
                verified = False
            if not verified:
                errors.append("logout_failed")
        return {
            **counts,
            "expected_attachments": len(self.cleanup_tracker.attachments),
            "expected_conversations": len(self.cleanup_tracker.conversations),
            "failures": sorted(set(errors)),
            "verified": not errors,
        }


def run_live_gate(
    *,
    client: httpx.Client,
    weird_manifest: dict[str, Any],
    complex_manifest: dict[str, Any],
    datasource_id: str,
    semantic_model_id: str,
    credentials: Mapping[str, str],
) -> dict[str, Any]:
    started_at = utc_now()
    gate = LiveQuestionsGate(
        client,
        datasource_id=datasource_id,
        semantic_model_id=semantic_model_id,
        credentials=credentials,
        secret_values=(credentials["password"],),
    )
    weird_results: list[dict[str, Any]] = []
    complex_results: list[dict[str, Any]] = []
    runtime_error: str | None = None
    auth: dict[str, Any] = {}
    try:
        auth = gate.login()
        if not auth["authenticated"]:
            raise LiveGateError("AUTHENTICATION_NOT_CONFIRMED")
        for case in weird_manifest["cases"]:
            action = str((case.get("expected") or {}).get("action") or "")
            contract = (weird_manifest.get("answer_contracts") or {}).get(action)
            if not isinstance(contract, dict):
                raise LiveGateError(f"ANSWER_CONTRACT_MISSING:{action}")
            executable_case = {**case, "expected_answer_contract": contract}
            weird_results.append(gate.run_question(executable_case, explicit_route=False))
        for case in complex_manifest["cases"]:
            evidence = gate.run_question(case, explicit_route=True)
            failures = gate.validate_complex(case, evidence)
            cancel = gate.cancel_probe(case)
            failures.extend(cancel["failures"])
            evidence["cancel"] = cancel
            evidence["failures"] = list(dict.fromkeys(failures))
            evidence["status"] = "PASS" if not failures else "FAIL"
            complex_results.append(evidence)
    except Exception as exc:
        runtime_error = type(exc).__name__ if not isinstance(exc, LiveGateError) else str(exc)
    finally:
        cleanup = gate.cleanup()

    failures = [
        *(f"weird:{item['id']}:{code}" for item in weird_results for code in item["failures"]),
        *(f"complex:{item['id']}:{code}" for item in complex_results for code in item["failures"]),
    ]
    if runtime_error:
        failures.append(f"runtime:{runtime_error}")
    if len(weird_results) != 50:
        failures.append("weird_case_execution_incomplete")
    if len(complex_results) != 5:
        failures.append("complex_case_execution_incomplete")
    if not cleanup["verified"]:
        failures.append("cleanup_not_verified")
    tested_sha = git_sha()
    if tested_sha is None:
        failures.append("tested_sha_missing")
    evidence = {
        "schema_version": "chatbi.v13.phase5.live-questions.v1",
        "status": "PASS" if not failures else "FAIL",
        "tested_sha": tested_sha,
        "started_at": iso(started_at),
        "completed_at": iso(utc_now()),
        "authentication": auth,
        "manifests": {
            "weird_50_sha256": sha256_bytes(json.dumps(weird_manifest, ensure_ascii=False, sort_keys=True).encode("utf-8")),
            "complex_5_sha256": sha256_bytes(json.dumps(complex_manifest, ensure_ascii=False, sort_keys=True).encode("utf-8")),
        },
        "weird_50": {
            "executed": len(weird_results),
            "passed": sum(item["status"] == "PASS" for item in weird_results),
            "automatic_route_count": len(weird_results),
            "cases": weird_results,
        },
        "complex_5": {
            "executed": len(complex_results),
            "passed": sum(item["status"] == "PASS" for item in complex_results),
            "cancel_passed": sum(item.get("cancel", {}).get("status") == "PASS" for item in complex_results),
            "cases": complex_results,
        },
        "cleanup": cleanup,
        "failures": failures,
    }
    serialized = json.dumps(evidence, ensure_ascii=False, sort_keys=True)
    if any(secret and secret in serialized for secret in (credentials["password"],)):
        raise LiveGateError("SECRET_LEAK_IN_EVIDENCE")
    return evidence


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the authenticated ChatBI V1.3 Phase5 live questions gate")
    parser.add_argument("--env-file", type=Path, required=True, help="External file containing Phase5 credentials")
    parser.add_argument("--api-base", default="http://127.0.0.1:8000/api/v1")
    parser.add_argument("--datasource-id", required=True)
    parser.add_argument("--semantic-model-id", required=True)
    parser.add_argument("--weird-manifest", type=Path, default=DEFAULT_WEIRD_MANIFEST)
    parser.add_argument("--complex-manifest", type=Path, default=DEFAULT_COMPLEX_MANIFEST)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.timeout_seconds <= 0:
        raise SystemExit("--timeout-seconds must be positive")
    credentials = load_external_credentials(args.env_file)
    weird = load_manifest(args.weird_manifest, expected_count=50)
    complex_manifest = load_manifest(args.complex_manifest, expected_count=5)
    api_base = validate_backend_url(args.api_base)
    with httpx.Client(
        base_url=api_base,
        timeout=httpx.Timeout(args.timeout_seconds),
        follow_redirects=False,
        trust_env=False,
        headers={"User-Agent": "chatbi-v13-phase5-live-gate"},
    ) as client:
        evidence = run_live_gate(
            client=client,
            weird_manifest=weird,
            complex_manifest=complex_manifest,
            datasource_id=args.datasource_id,
            semantic_model_id=args.semantic_model_id,
            credentials=credentials,
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": evidence["status"],
        "tested_sha": evidence["tested_sha"],
        "weird_passed": evidence["weird_50"]["passed"],
        "complex_passed": evidence["complex_5"]["passed"],
        "cancel_passed": evidence["complex_5"]["cancel_passed"],
        "cleanup_verified": evidence["cleanup"]["verified"],
        "failure_count": len(evidence["failures"]),
        "evidence": str(args.output),
    }, ensure_ascii=False))
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
