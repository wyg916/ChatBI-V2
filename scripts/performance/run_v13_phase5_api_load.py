from __future__ import annotations

import argparse
import copy
import ctypes
import hashlib
import hmac
import json
import math
import os
import platform
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import zlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Sequence
from urllib.parse import urlparse

import httpx
from sqlalchemy import create_engine, delete, func, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session


REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from scripts.run_v13_phase5_data_performance_gate import (  # noqa: E402
    SystemProbe,
    aggregate_cost_ledger,
    distribution,
    validate_local_postgres_url,
)
from app.core.auth import hash_password  # noqa: E402
from app.models import (  # noqa: E402
    AppUser,
    Attachment,
    AuditEvent,
    AuthSession,
    ChatMessage,
    Conversation,
    DataSource,
    ModelInvocation,
    QueryRun,
    ResourceGrant,
    SemanticModel,
    Workspace,
)
from app.services.attachments import attachment_path  # noqa: E402
from app.services.governance import cost_ledger_entries  # noqa: E402


_TERMINAL_EVENTS = {"run.completed", "run.failed", "run.cancelled"}
_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
_REQUEST_PREFIX_RE = re.compile(r"^phase5api-[a-f0-9]{12}-$")
_METADATA_SCHEMA_RE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
DEFAULT_CORE_DATA_MANIFEST = REPO_ROOT / "evaluation" / "golden" / "v13-phase5-data-100.json"
RELEASE_THRESHOLDS = {
    "min_users": 20,
    "min_duration_seconds": 900,
    "min_success_rate": 1.0,
    "max_ttfe_p95_ms": 1_000.0,
    "max_ttft_p95_ms": 15_000.0,
    "max_total_p95_ms": 30_000.0,
    "max_total_p99_ms": 35_000.0,
    "max_host_cpu_p99_percent": 90.0,
    "max_host_ram_p99_percent": 90.0,
    "max_backend_cpu_p99_percent": 90.0,
    "max_db_connections": 60,
    "max_kimi_premium_share": 0.10,
    "min_saving_vs_all_premium": 0.60,
}
DEFAULT_API_USERS = 20
DEFAULT_API_DURATION_SECONDS = 15 * 60


@dataclass(frozen=True)
class Credential:
    email: str
    password: str


@dataclass(frozen=True)
class BootstrapReceipt:
    metadata_schema: str
    user_ids: tuple[str, ...]
    users_created: int
    grants_created: int


@dataclass
class UserRuntime:
    index: int
    client: httpx.Client
    user_id: str
    workspace_id: str
    conversation_id: str
    csv_attachment_id: str
    image_attachment_id: str


@dataclass(frozen=True)
class ApiSample:
    user_index: int
    kind: str
    ttfe_ms: float
    ttft_ms: float
    total_ms: float
    status_code: int
    event_count: int
    terminal_event: str | None
    terminal_count: int
    success: bool
    error_code: str | None
    request_id: str = ""
    observed_route: str | None = None
    business_valid: bool = False
    business_checks: tuple[str, ...] = ()


@dataclass(frozen=True)
class ResourceSample:
    host_cpu_percent: float | None
    host_ram_percent: float | None
    backend_cpu_percent: float | None
    backend_rss_mib: float | None
    db_connections: int
    db_active_connections: int


WORKLOAD_MIX: tuple[str, ...] = (
    *("DATA" for _ in range(35)),
    *("RAG" for _ in range(15)),
    *("HYBRID" for _ in range(15)),
    *("AGENT" for _ in range(15)),
    *("FILE" for _ in range(15)),
    *("VISION" for _ in range(5)),
)


QUESTIONS = {
    "DATA": "统计全部订单收入，并返回可核验结果。",
    "RAG": "根据已授权业务知识说明收入指标口径，并给出可核验引用。",
    "HYBRID": "结合订单数据与已授权业务口径，分析收入结果并给出引用。",
    "AGENT": "对全部订单收入做复杂分析，结合已授权业务口径验证后给出结论。",
    "FILE": "计算附件中收入合计并按区域比较，给出可核验明细。",
    "VISION": "识别附件图表中的各月收入柱并总结趋势，不要编造不可见数值。",
}
VISION_EXPECTED_VALUES = (100, 120, 90, 150, 130, 170)
FILE_EXPECTED_REVENUE = 2_194_620
EXPECTED_REVENUE_KNOWLEDGE_TITLE = "收入口径与退款处理"
EXPECTED_REVENUE_KNOWLEDGE_TEXT = (
    "收入（营收、销售额）按已确认且有效订单的 revenue 求和；取消订单不计入，"
    "退款按实际冲减金额扣除。数据结果必须经过 SQL Guard 与 Result Oracle 后发布。"
)
EXPECTED_REVENUE_KNOWLEDGE_SHA256 = hashlib.sha256(
    EXPECTED_REVENUE_KNOWLEDGE_TEXT.encode("utf-8")
).hexdigest()
_INLINE_CITATION_RE = re.compile(r"\[citation:([^\]]+)\]", re.IGNORECASE)
_KNOWLEDGE_INJECTION_RE = re.compile(
    r"ignore\s+(?:all\s+)?previous\s+instructions|忽略.{0,12}(?:之前|以上|系统).{0,8}(?:指令|提示)|"
    r"(?:system|developer)\s*prompt|(?:绕过|跳过|disable).{0,16}(?:权限|guard|acl|安全)|"
    r"(?:exfiltrate|reveal).{0,24}(?:secret|credential|prompt)",
    re.IGNORECASE,
)
_NUMBER_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9])[+-]?\d[\d,]*(?:\.\d+)?")
_DIGITS = {
    "0": ("111", "101", "101", "101", "111"),
    "1": ("010", "110", "010", "010", "111"),
    "2": ("111", "001", "111", "100", "111"),
    "3": ("111", "001", "111", "001", "111"),
    "4": ("101", "101", "111", "001", "001"),
    "5": ("111", "100", "111", "001", "111"),
    "6": ("111", "100", "111", "101", "111"),
    "7": ("111", "001", "010", "010", "010"),
    "8": ("111", "101", "111", "101", "111"),
    "9": ("111", "101", "111", "001", "111"),
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def validate_backend_url(base_url: str) -> str:
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or (parsed.hostname or "").casefold() not in _LOCAL_HOSTS:
        raise ValueError("Phase5 API load must target a loopback Backend HTTP(S) endpoint")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Backend URL must not contain credentials, query or fragment")
    return base_url.rstrip("/")


def derive_credentials(base_password: str, *, request_prefix: str, users: int) -> list[Credential]:
    if len(base_password) < 10:
        raise ValueError("external Phase5 base password must contain at least 10 characters")
    if not _REQUEST_PREFIX_RE.fullmatch(request_prefix) or users <= 0:
        raise ValueError("invalid Phase5 credential derivation scope")
    token = request_prefix.removeprefix("phase5api-").removesuffix("-")
    credentials = []
    for index in range(users):
        digest = hmac.new(
            base_password.encode("utf-8"),
            f"{request_prefix}{index:02d}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        credentials.append(Credential(
            email=f"phase5api+{token}-{index:02d}@load.chatbi.invalid",
            password=f"{base_password}-{digest}",
        ))
    return credentials


def _canonical_manifest_hash(manifest: dict[str, Any]) -> str:
    value = copy.deepcopy(manifest)
    value["manifest_sha256"] = None
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_core_data_manifest(path: Path = DEFAULT_CORE_DATA_MANIFEST) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    manifest_path = path.resolve()
    if manifest_path != REPO_ROOT.resolve() and REPO_ROOT.resolve() not in manifest_path.parents:
        raise ValueError("Core Data100 manifest must remain inside the repository")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("frozen") is not True or _canonical_manifest_hash(manifest) != manifest.get("manifest_sha256"):
        raise ValueError("Core Data100 manifest is not frozen or its SHA-256 is invalid")
    base_relative = Path(str(manifest.get("base_manifest") or ""))
    base_path = (REPO_ROOT / base_relative).resolve()
    if REPO_ROOT.resolve() not in base_path.parents or not base_path.is_file():
        raise ValueError("Core Data100 base manifest path is invalid")
    base = json.loads(base_path.read_text(encoding="utf-8"))
    if (
        _canonical_manifest_hash(base) != manifest.get("base_manifest_sha256")
        or base.get("manifest_sha256") != manifest.get("base_manifest_sha256")
    ):
        raise ValueError("Core Data100 base manifest SHA-256 mismatch")
    base_cases = copy.deepcopy(base.get("cases") or [])
    overrides = manifest.get("base_case_question_overrides") or {}
    if set(overrides) != {"G21", "G22"}:
        raise ValueError("Core Data100 must explicitly de-duplicate the two inherited Day4 question collisions")
    for case in base_cases:
        if case.get("id") in overrides:
            case["question"] = str(overrides[case["id"]])
    extension = copy.deepcopy(manifest.get("extension_cases") or [])
    cases = base_cases + extension
    ids = [str(item.get("id") or "") for item in cases]
    questions = [str(item.get("question") or "").strip().casefold() for item in cases]
    categories = {str(item.get("category") or "") for item in cases}
    required_categories = {str(item) for item in manifest.get("required_categories") or []}
    if len(base_cases) != 50 or len(extension) != 50 or len(cases) != 100:
        raise ValueError("Core Data100 requires the frozen Day4 50 plus exactly 50 extensions")
    if not all(ids) or len(set(ids)) != 100 or not all(questions) or len(set(questions)) != 100:
        raise ValueError("Core Data100 case IDs and questions must be non-empty and unique")
    if not required_categories <= categories:
        raise ValueError("Core Data100 required category coverage is incomplete")
    return manifest, cases


def select_load_data_case(cases: Sequence[dict[str, Any]], case_id: str) -> tuple[dict[str, Any], Decimal]:
    case = next((item for item in cases if str(item.get("id")) == case_id), None)
    if case is None or str(case.get("expected_outcome") or "PASSED") not in {"PASSED", "SUCCEEDED_AND_VERIFIED"}:
        raise ValueError("API load DATA case must be a successful frozen Core Data100 case")
    rows = case.get("expected_result") if isinstance(case.get("expected_result"), list) else []
    if len(rows) != 1 or not isinstance(rows[0], dict):
        raise ValueError("API load DATA case must have exactly one frozen expected row")
    numeric_values = [value for value in rows[0].values() if _decimal(value) is not None]
    signature = str(case.get("expected_signature") or "")
    if len(numeric_values) != 1 or len(signature) != 64:
        raise ValueError("API load DATA case requires one exact numeric value and a frozen result signature")
    return case, _decimal(numeric_values[0])  # type: ignore[return-value]


def _canonical_scalar(value: Any) -> Any:
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    if isinstance(value, (int, float, Decimal)):
        decimal = Decimal(str(value))
        if decimal == decimal.to_integral():
            return str(decimal.quantize(Decimal(1)))
        return format(decimal.normalize(), "f")
    return str(value)


def _canonical_rows(rows: Any) -> list[str]:
    normalized: list[str] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            normalized.append(json.dumps(_canonical_scalar(row), ensure_ascii=False, sort_keys=True))
            continue
        value = {str(key): _canonical_scalar(item) for key, item in sorted(row.items())}
        normalized.append(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return sorted(normalized)


def _independent_result_signature(columns: Any, rows: Any) -> str:
    ordered_columns = [str(item) for item in columns] if isinstance(columns, list) else []
    source_rows = rows if isinstance(rows, list) else []
    normalized_rows = [
        {column: row.get(column) for column in ordered_columns}
        for row in source_rows if isinstance(row, dict)
    ]
    normalized_rows.sort(key=lambda row: json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    payload = json.dumps(
        {"columns": ordered_columns, "rows": normalized_rows},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _semantic_failures(case: dict[str, Any], actual: dict[str, Any]) -> list[str]:
    plan = actual.get("plan") if isinstance(actual.get("plan"), dict) else {}
    failures: list[str] = []
    if list(plan.get("metrics") or []) != list(case.get("expected_metrics") or []):
        failures.append("SEMANTIC_METRICS_MISMATCH")
    if list(plan.get("dimensions") or []) != list(case.get("expected_dimensions") or []):
        failures.append("SEMANTIC_DIMENSIONS_MISMATCH")
    if not set(case.get("expected_entities") or []) <= set(plan.get("selected_entities") or []):
        failures.append("SEMANTIC_ENTITIES_MISMATCH")
    expected_filters = {
        (str(item.get("field")), json.dumps(item.get("value"), ensure_ascii=False, sort_keys=True))
        for item in case.get("expected_filters") or [] if isinstance(item, dict)
    }
    actual_filters = {
        (str(item.get("field")), json.dumps(item.get("value"), ensure_ascii=False, sort_keys=True))
        for item in plan.get("filters") or [] if isinstance(item, dict)
    }
    if not expected_filters <= actual_filters:
        failures.append("SEMANTIC_FILTERS_MISMATCH")
    expected_time = case.get("expected_time_range")
    actual_time = plan.get("time_range") if isinstance(plan.get("time_range"), dict) else None
    if expected_time and (
        not actual_time
        or actual_time.get("start") != expected_time.get("start")
        or actual_time.get("end_exclusive") != expected_time.get("end_exclusive")
    ):
        failures.append("SEMANTIC_TIME_RANGE_MISMATCH")
    return failures


def execute_core_data_case(
    client: httpx.Client,
    case: dict[str, Any],
    *,
    datasource_id: str,
    semantic_model_id: str,
) -> dict[str, Any]:
    started = time.perf_counter()
    failures: list[str] = []
    response = client.post("/api/v1/ask", json={
        "question": case["question"],
        "datasource_id": datasource_id,
        "semantic_model_id": semantic_model_id,
        "row_limit": 500,
    })
    if response.status_code != 201:
        return {
            "id": case["id"], "category": case["category"], "status": "FAIL",
            "expected_outcome": str(case.get("expected_outcome") or "PASSED"),
            "http_status": response.status_code, "failures": [f"ASK_HTTP_{response.status_code}"],
            "guard": {}, "execution": {}, "expected_actual_value_match": False,
            "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 3),
        }
    actual = response.json()
    context = actual.get("context") if isinstance(actual.get("context"), dict) else {}
    request_context = context.get("request_context") if isinstance(context.get("request_context"), dict) else {}
    route = str(request_context.get("route") or "") or None
    plan = actual.get("plan") if isinstance(actual.get("plan"), dict) else {}
    guard = actual.get("guard") if isinstance(actual.get("guard"), dict) else {}
    execution = actual.get("execution") if isinstance(actual.get("execution"), dict) else {}
    oracle_before = actual.get("oracle") if isinstance(actual.get("oracle"), dict) else {}
    verification_query = context.get("verification_query") if isinstance(context.get("verification_query"), dict) else {}
    generated_sql = str(plan.get("generated_sql") or "")
    normalized_sql = str(guard.get("normalized_sql") or "")
    if route != "DATA_QUERY":
        failures.append("ACTUAL_ROUTE_NOT_DATA_QUERY")

    expected_outcome = str(case.get("expected_outcome") or "PASSED")
    oracle_after: dict[str, Any] = {}
    value_match = False
    if expected_outcome in {"PASSED", "SUCCEEDED_AND_VERIFIED"}:
        failures.extend(_semantic_failures(case, actual))
        if str(actual.get("status")) != "SUCCEEDED":
            failures.append("PIPELINE_STATUS_NOT_SUCCEEDED")
        if guard.get("allowed") is not True or not normalized_sql.lstrip().upper().startswith(("SELECT ", "WITH ")):
            failures.append("SQL_GUARD_NOT_READ_ONLY_ALLOWED")
        actual_signature = str(execution.get("result_signature") or "")
        independent_signature = _independent_result_signature(execution.get("columns"), execution.get("rows"))
        if str(execution.get("status")) != "SUCCEEDED" or len(actual_signature) != 64:
            failures.append("SQL_EXECUTION_OR_SIGNATURE_NOT_PROVEN")
        if actual_signature != independent_signature:
            failures.append("RESULT_SIGNATURE_NOT_INDEPENDENTLY_REPRODUCED")
        if case.get("expected_signature") and actual_signature != str(case.get("expected_signature")):
            failures.append("FROZEN_EXPECTED_SIGNATURE_MISMATCH")
        if str(oracle_before.get("status")) != "PASSED":
            failures.append("PIPELINE_ORACLE_NOT_PASSED")
        if not verification_query or verification_query.get("passed") is not True:
            failures.append("INTERNAL_VERIFICATION_QUERY_NOT_PASSED")
        expected_rows = case.get("expected_result") or []
        value_match = _canonical_rows(execution.get("rows")) == _canonical_rows(expected_rows)
        if not value_match:
            failures.append("EXPECTED_ACTUAL_VALUE_MISMATCH")
        query_id = str(actual.get("id") or "")
        if not query_id:
            failures.append("QUERY_ID_MISSING")
        else:
            verify = client.post(f"/api/v1/queries/{query_id}/verify", json={"expected": {
                "columns": list(expected_rows[0]) if expected_rows else list(execution.get("columns") or []),
                "rows": expected_rows,
                "tolerance": 0.0001,
                "order_independent": True,
                "metric_names": list(case.get("expected_metrics") or []),
                "dimension_names": list(case.get("expected_dimensions") or []),
                "expected_signature": case.get("expected_signature"),
            }})
            if verify.status_code == 200:
                verified_payload = verify.json()
                oracle_after = verified_payload.get("oracle") if isinstance(verified_payload.get("oracle"), dict) else {}
            else:
                failures.append(f"VERIFY_HTTP_{verify.status_code}")
            if str(oracle_after.get("status")) != "PASSED":
                failures.append("EXPECTED_RESULT_ORACLE_NOT_PASSED")
    else:
        allowed_statuses = {str(item) for item in case.get("allowed_statuses") or []}
        if str(actual.get("status")) not in allowed_statuses:
            failures.append("FAIL_CLOSED_STATUS_MISMATCH")
        if str(execution.get("status") or "") == "SUCCEEDED" or execution.get("rows"):
            failures.append("FAIL_CLOSED_CASE_EXECUTED_SQL")
        if case.get("category") in {"dangerous_sql", "wrong_field"} and (
            guard.get("allowed") is not False or not guard.get("issues")
        ):
            failures.append("SQL_GUARD_BLOCK_NOT_PROVEN")

    return {
        "id": case["id"],
        "category": case["category"],
        "expected_outcome": expected_outcome,
        "status": "PASS" if not failures else "FAIL",
        "actual_route": route,
        "query_id": actual.get("id"),
        "pipeline_status": actual.get("status"),
        "generated_sql": generated_sql or None,
        "normalized_sql": normalized_sql or None,
        "golden_verification_sql": case.get("expected_sql"),
        "guard": {
            "allowed": guard.get("allowed"), "statement_type": guard.get("statement_type"),
            "issues": guard.get("issues") or [],
        },
        "execution": {
            "status": execution.get("status"), "row_count": execution.get("row_count"),
            "result_signature": execution.get("result_signature"), "error_code": execution.get("error_code"),
        },
        "pipeline_verification_query": verification_query or None,
        "oracle_before_expected_verify": oracle_before,
        "oracle_after_expected_verify": oracle_after or None,
        "expected_rows": case.get("expected_result"),
        "actual_rows": execution.get("rows"),
        "expected_actual_value_match": value_match,
        "error_code": actual.get("error_code"),
        "failures": failures,
        "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 3),
    }


def run_core_data100(
    client: httpx.Client,
    cases: Sequence[dict[str, Any]],
    *,
    datasource_id: str,
    semantic_model_id: str,
) -> dict[str, Any]:
    started = time.perf_counter()
    results = [
        execute_core_data_case(
            client, case, datasource_id=datasource_id, semantic_model_id=semantic_model_id,
        )
        for case in cases
    ]
    success_cases = [item for item in results if item["expected_outcome"] in {"PASSED", "SUCCEEDED_AND_VERIFIED"}]
    dangerous_cases = [item for item in results if item["category"] == "dangerous_sql"]
    passed = sum(item["status"] == "PASS" for item in results)
    execution_pass = sum(item["execution"].get("status") == "SUCCEEDED" for item in success_cases)
    value_pass = sum(item["expected_actual_value_match"] is True for item in success_cases)
    dangerous_pass = sum(
        item["guard"].get("allowed") is False and item["execution"].get("status") != "SUCCEEDED"
        for item in dangerous_cases
    )
    return {
        "status": "PASS" if passed == 100 else "FAIL",
        "total": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "actual_elapsed_seconds": round(time.perf_counter() - started, 3),
        "sql_execution_rate": round(execution_pass / len(success_cases), 6) if success_cases else 0.0,
        "result_value_accuracy": round(value_pass / len(success_cases), 6) if success_cases else 0.0,
        "dangerous_sql_block_rate": round(dangerous_pass / len(dangerous_cases), 6) if dangerous_cases else 0.0,
        "category_counts": {
            category: sum(item["category"] == category for item in results)
            for category in sorted({item["category"] for item in results})
        },
        "cases": results,
    }


class MetadataBootstrap:
    """Atomically create and exactly remove run-scoped metadata identities."""

    def __init__(
        self,
        database_url: str,
        *,
        metadata_schema: str,
        workspace_id: str,
        datasource_id: str,
        semantic_model_id: str,
        request_prefix: str,
    ) -> None:
        validate_local_postgres_url(database_url)
        if not _METADATA_SCHEMA_RE.fullmatch(metadata_schema):
            raise ValueError("metadata schema must be a safe PostgreSQL identifier")
        if not _REQUEST_PREFIX_RE.fullmatch(request_prefix):
            raise ValueError("invalid Phase5 metadata bootstrap prefix")
        self.metadata_schema = metadata_schema
        self.workspace_id = workspace_id
        self.datasource_id = datasource_id
        self.semantic_model_id = semantic_model_id
        self.request_prefix = request_prefix
        self.engine = create_engine(
            database_url,
            pool_pre_ping=True,
            pool_size=2,
            max_overflow=0,
            connect_args={
                "application_name": "chatbi-v13-phase5-api-bootstrap",
                "options": f"-csearch_path={metadata_schema}",
            },
        )

    def bootstrap(self, credentials: Sequence[Credential]) -> BootstrapReceipt:
        with Session(self.engine) as session, session.begin():
            current_schema = str(session.execute(text("SELECT current_schema()" )).scalar_one())
            if current_schema != self.metadata_schema:
                raise RuntimeError("METADATA_SCHEMA_MISMATCH")
            workspace = session.get(Workspace, self.workspace_id)
            datasource = session.get(DataSource, self.datasource_id)
            semantic_model = session.get(SemanticModel, self.semantic_model_id)
            if workspace is None:
                raise RuntimeError("WORKSPACE_NOT_FOUND")
            if datasource is None or datasource.workspace_id != self.workspace_id:
                raise RuntimeError("DATASOURCE_WORKSPACE_MISMATCH")
            if (
                semantic_model is None
                or semantic_model.workspace_id != self.workspace_id
                or semantic_model.datasource_id != self.datasource_id
            ):
                raise RuntimeError("SEMANTIC_MODEL_SCOPE_MISMATCH")
            emails = [item.email for item in credentials]
            existing = session.scalar(select(func.count(AppUser.id)).where(AppUser.email.in_(emails))) or 0
            if existing:
                raise RuntimeError("PHASE5_TEMP_USER_COLLISION")
            users = [
                AppUser(
                    workspace_id=self.workspace_id,
                    email=credential.email,
                    display_name=f"Phase5 Load User {index:02d}",
                    role="ANALYST",
                    status="ACTIVE",
                    password_hash=hash_password(credential.password),
                    password_changed_at=_utc_now(),
                )
                for index, credential in enumerate(credentials)
            ]
            session.add_all(users)
            session.flush()
            grants = [
                ResourceGrant(
                    user_id=user.id,
                    resource_type=resource_type,
                    resource_id=resource_id,
                    can_read=True,
                    can_query=True,
                )
                for user in users
                for resource_type, resource_id in (
                    ("DATASOURCE", self.datasource_id),
                    ("SEMANTIC_MODEL", self.semantic_model_id),
                )
            ]
            session.add_all(grants)
            session.flush()
            user_ids = tuple(user.id for user in users)
        return BootstrapReceipt(
            metadata_schema=self.metadata_schema,
            user_ids=user_ids,
            users_created=len(user_ids),
            grants_created=len(credentials) * 2,
        )

    def cleanup(self, receipt: BootstrapReceipt | None) -> dict[str, Any]:
        result = {
            "metadata_sessions_deleted": 0,
            "metadata_grants_deleted": 0,
            "metadata_users_deleted": 0,
            "metadata_conversations_before_delete": 0,
            "metadata_attachments_before_delete": 0,
            "metadata_messages_before_delete": 0,
            "metadata_model_invocations_removed": 0,
            "metadata_load_model_invocations_removed": 0,
            "metadata_query_runs_deleted": 0,
            "metadata_attachment_files_removed": 0,
            "metadata_absence_verified": False,
        }
        if receipt is None:
            return result
        user_ids = list(receipt.user_ids)
        paths: list[Path] = []
        with Session(self.engine) as session, session.begin():
            attachments = list(session.scalars(select(Attachment).where(Attachment.user_id.in_(user_ids))))
            paths = [attachment_path(item) for item in attachments]
            result["metadata_conversations_before_delete"] = int(session.scalar(
                select(func.count(Conversation.id)).where(Conversation.user_id.in_(user_ids))
            ) or 0)
            result["metadata_attachments_before_delete"] = len(attachments)
            result["metadata_messages_before_delete"] = int(session.scalar(
                select(func.count(ChatMessage.id)).where(ChatMessage.user_id.in_(user_ids))
            ) or 0)
            result["metadata_model_invocations_removed"] = int(session.scalar(
                select(func.count(ModelInvocation.id)).where(ModelInvocation.user_id.in_(user_ids))
            ) or 0)
            result["metadata_load_model_invocations_removed"] = int(session.scalar(
                select(func.count(ModelInvocation.id)).where(
                    ModelInvocation.user_id.in_(user_ids),
                    ModelInvocation.request_id.like(f"{self.request_prefix}%"),
                )
            ) or 0)
            query_run_ids = {
                str(value)
                for value in session.scalars(select(AuditEvent.resource_id).where(
                    AuditEvent.actor_user_id.in_(user_ids),
                    AuditEvent.resource_type == "QUERY_RUN",
                    AuditEvent.resource_id.is_not(None),
                ))
                if value
            }
            if query_run_ids:
                result["metadata_query_runs_deleted"] = int(session.execute(
                    delete(QueryRun).where(QueryRun.id.in_(query_run_ids))
                ).rowcount or 0)
            result["metadata_sessions_deleted"] = int(session.execute(
                delete(AuthSession).where(AuthSession.user_id.in_(user_ids))
            ).rowcount or 0)
            result["metadata_grants_deleted"] = int(session.execute(
                delete(ResourceGrant).where(ResourceGrant.user_id.in_(user_ids))
            ).rowcount or 0)
            result["metadata_users_deleted"] = int(session.execute(
                delete(AppUser).where(AppUser.id.in_(user_ids))
            ).rowcount or 0)
        for path in paths:
            existed = path.exists()
            path.unlink(missing_ok=True)
            result["metadata_attachment_files_removed"] += int(existed and not path.exists())
        with Session(self.engine) as session:
            remaining = {
                "users": session.scalar(select(func.count(AppUser.id)).where(AppUser.id.in_(user_ids))) or 0,
                "sessions": session.scalar(select(func.count(AuthSession.id)).where(AuthSession.user_id.in_(user_ids))) or 0,
                "grants": session.scalar(select(func.count(ResourceGrant.id)).where(ResourceGrant.user_id.in_(user_ids))) or 0,
                "conversations": session.scalar(select(func.count(Conversation.id)).where(Conversation.user_id.in_(user_ids))) or 0,
                "attachments": session.scalar(select(func.count(Attachment.id)).where(Attachment.user_id.in_(user_ids))) or 0,
                "messages": session.scalar(select(func.count(ChatMessage.id)).where(ChatMessage.user_id.in_(user_ids))) or 0,
                "ledger": session.scalar(select(func.count(ModelInvocation.id)).where(ModelInvocation.user_id.in_(user_ids))) or 0,
                "query_runs": session.scalar(select(func.count(QueryRun.id)).where(QueryRun.id.in_(query_run_ids))) or 0,
            }
        result["metadata_absence_verified"] = all(int(value) == 0 for value in remaining.values())
        result["metadata_remaining"] = {key: int(value) for key, value in remaining.items()}
        return result

    def close(self) -> None:
        self.engine.dispose()


def deterministic_csv_bytes() -> bytes:
    rows = ["month,region,revenue,cost"]
    regions = ("华东", "华南", "华北", "西部")
    for index in range(1, 121):
        month = (index - 1) % 12 + 1
        region = regions[(index - 1) % len(regions)]
        revenue = 10_000 + index * 137
        cost = 6_000 + index * 79
        rows.append(f"2026-{month:02d},{region},{revenue},{cost}")
    return ("\n".join(rows) + "\n").encode("utf-8")


def deterministic_png_bytes(width: int = 160, height: int = 96) -> bytes:
    """Generate a stable RGB bar-chart PNG without an image dependency."""
    pixels = [[(248, 250, 252) for _x in range(width)] for _y in range(height)]

    def rectangle(left: int, top: int, right: int, bottom: int, color: tuple[int, int, int]) -> None:
        for y in range(max(0, top), min(height, bottom)):
            for x in range(max(0, left), min(width, right)):
                pixels[y][x] = color

    def digits(value: str, left: int, top: int, scale: int = 1) -> None:
        cursor = left
        for digit in value:
            pattern = _DIGITS[digit]
            for row, bits in enumerate(pattern):
                for column, bit in enumerate(bits):
                    if bit == "1":
                        rectangle(
                            cursor + column * scale,
                            top + row * scale,
                            cursor + (column + 1) * scale,
                            top + (row + 1) * scale,
                            (15, 23, 42),
                        )
            cursor += 4 * scale

    rectangle(10, height - 13, width - 4, height - 12, (51, 65, 85))
    rectangle(11, 8, 12, height - 12, (51, 65, 85))
    for index, value in enumerate(VISION_EXPECTED_VALUES):
        bar_height = round(value * 0.28)
        left = 20 + index * 23
        rectangle(left, height - 13 - bar_height, left + 13, height - 13, (37, 99 + index * 8, 235 - index * 9))
        digits(str(value), left - 1, max(1, height - 21 - bar_height), 1)
        digits(f"{index + 1:02d}", left + 2, height - 9, 1)

    raw = bytearray()
    for row in pixels:
        raw.append(0)
        for color in row:
            raw.extend(color)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b"")


def create_fixtures() -> tuple[Path, Path, Path]:
    directory = Path(tempfile.mkdtemp(prefix="chatbi-phase5-api-"))
    csv_path = directory / "phase5_operating_data.csv"
    png_path = directory / "phase5_revenue_chart.png"
    csv_path.write_bytes(deterministic_csv_bytes())
    png_path.write_bytes(deterministic_png_bytes())
    return directory, csv_path, png_path


def workload_kind(user_index: int, sequence: int, users: int) -> str:
    if user_index < 0 or sequence < 0 or users <= 0:
        raise ValueError("workload schedule inputs are invalid")
    return WORKLOAD_MIX[(user_index + sequence * users) % len(WORKLOAD_MIX)]


def _raise_status(response: httpx.Response, expected: set[int]) -> None:
    if response.status_code not in expected:
        raise RuntimeError(f"HTTP_{response.status_code}")


def prepare_user(
    *,
    index: int,
    credential: Credential,
    base_url: str,
    workspace_id: str,
    csv_bytes: bytes,
    png_bytes: bytes,
    timeout_seconds: float,
) -> UserRuntime:
    client = httpx.Client(
        base_url=base_url,
        timeout=httpx.Timeout(timeout_seconds, connect=10.0),
        follow_redirects=False,
        trust_env=False,
        headers={"User-Agent": "ChatBI-V13-Phase5-Real-Load/1.0"},
    )
    conversation_id: str | None = None
    attachment_ids: list[str] = []
    try:
        login = client.post("/api/v1/auth/login", json={
            "email": credential.email, "password": credential.password, "remember": False,
        })
        _raise_status(login, {200})
        me = client.get("/api/v1/auth/me")
        _raise_status(me, {200})
        user = me.json()["user"]
        if str(user["workspace_id"]) != workspace_id:
            raise RuntimeError("WORKSPACE_MISMATCH")
        conversation = client.post("/api/v1/conversations", json={
            "title": f"Phase5 API Load User {index:02d}",
        })
        _raise_status(conversation, {201})
        conversation_id = str(conversation.json()["id"])
        csv_upload = client.post(
            "/api/v1/attachments",
            data={"conversation_id": conversation_id},
            files={"file": ("phase5_operating_data.csv", csv_bytes, "text/csv")},
        )
        _raise_status(csv_upload, {201})
        attachment_ids.append(str(csv_upload.json()["id"]))
        image_upload = client.post(
            "/api/v1/attachments",
            data={"conversation_id": conversation_id},
            files={"file": ("phase5_revenue_chart.png", png_bytes, "image/png")},
        )
        _raise_status(image_upload, {201})
        attachment_ids.append(str(image_upload.json()["id"]))
        return UserRuntime(
            index=index,
            client=client,
            user_id=str(user["id"]),
            workspace_id=str(user["workspace_id"]),
            conversation_id=conversation_id,
            csv_attachment_id=attachment_ids[0],
            image_attachment_id=attachment_ids[1],
        )
    except Exception:
        for attachment_id in attachment_ids:
            try:
                client.delete(f"/api/v1/attachments/{attachment_id}")
            except Exception:
                pass
        if conversation_id:
            try:
                client.delete(f"/api/v1/conversations/{conversation_id}")
            except Exception:
                pass
        try:
            client.post("/api/v1/auth/logout")
        except Exception:
            pass
        client.close()
        raise


def cleanup_user(user: UserRuntime) -> dict[str, int]:
    result = {
        "attachment_delete_204": 0,
        "attachment_absence_404": 0,
        "conversation_delete_204": 0,
        "conversation_absence_404": 0,
        "logout_204": 0,
    }
    def status(method: str, path: str) -> int:
        try:
            return int(user.client.request(method, path).status_code)
        except Exception:
            return 0

    try:
        for attachment_id in (user.csv_attachment_id, user.image_attachment_id):
            result["attachment_delete_204"] += status("DELETE", f"/api/v1/attachments/{attachment_id}") == 204
            result["attachment_absence_404"] += status("GET", f"/api/v1/attachments/{attachment_id}") == 404
        result["conversation_delete_204"] += status("DELETE", f"/api/v1/conversations/{user.conversation_id}") == 204
        result["conversation_absence_404"] += status("GET", f"/api/v1/conversations/{user.conversation_id}") == 404
        result["logout_204"] += status("POST", "/api/v1/auth/logout") == 204
    finally:
        user.client.close()
    return result


def _decimal(value: Any) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        return None


def _numeric_claims(value: Any) -> set[Decimal]:
    if isinstance(value, bool) or value is None:
        return set()
    if isinstance(value, (int, float, Decimal)):
        converted = _decimal(value)
        return {converted} if converted is not None else set()
    if isinstance(value, dict):
        result: set[Decimal] = set()
        for item in value.values():
            result.update(_numeric_claims(item))
        return result
    if isinstance(value, (list, tuple)):
        result = set()
        for item in value:
            result.update(_numeric_claims(item))
        return result
    if isinstance(value, str):
        return {
            converted
            for token in _NUMBER_TOKEN_RE.findall(value)
            for converted in [_decimal(token)]
            if converted is not None
        }
    return set()


def _analysis_payload(terminal: dict[str, Any]) -> tuple[str | None, dict[str, Any]]:
    response = terminal.get("response") if isinstance(terminal.get("response"), dict) else {}
    assistant = response.get("assistant_message") if isinstance(response.get("assistant_message"), dict) else {}
    response_payload = assistant.get("response_payload") if isinstance(assistant.get("response_payload"), dict) else {}
    analysis = response_payload.get("analysis") if isinstance(response_payload.get("analysis"), dict) else {}
    observed_route = str(analysis.get("route") or assistant.get("route") or "") or None
    return observed_route, analysis


def _independent_knowledge_failures(
    knowledge: dict[str, Any], *, require_inline_claims: bool,
) -> list[str]:
    """Validate frozen citation content and answer claims without trusting service verdict fields."""
    failures: list[str] = []
    citations = knowledge.get("citations") if isinstance(knowledge.get("citations"), list) else []
    citation_by_id: dict[str, dict[str, Any]] = {
        str(item.get("citation_id")): item
        for item in citations
        if isinstance(item, dict) and item.get("citation_id")
    }
    frozen = [
        item for item in citation_by_id.values()
        if str(item.get("title") or "") == EXPECTED_REVENUE_KNOWLEDGE_TITLE
        and str(item.get("text") or item.get("citation_text") or "") == EXPECTED_REVENUE_KNOWLEDGE_TEXT
    ]
    if not frozen or any(
        hashlib.sha256(str(item.get("text") or item.get("citation_text") or "").encode("utf-8")).hexdigest()
        != EXPECTED_REVENUE_KNOWLEDGE_SHA256
        for item in frozen
    ):
        failures.append("FROZEN_REVENUE_KNOWLEDGE_CONTENT_NOT_PROVEN")
    if any(
        _KNOWLEDGE_INJECTION_RE.search(str(item.get("text") or item.get("citation_text") or ""))
        for item in citation_by_id.values()
    ):
        failures.append("PROMPT_INJECTION_CITATION_PRESENT")

    if require_inline_claims:
        summary = str(knowledge.get("summary") or "").strip()
        factual_lines = [line.strip() for line in summary.splitlines() if line.strip()]
        if not factual_lines:
            failures.append("KNOWLEDGE_ANSWER_MISSING")
        for line in factual_lines:
            cited_ids = _INLINE_CITATION_RE.findall(line)
            claim = " ".join(_INLINE_CITATION_RE.sub("", line).split()).strip("#*- ")
            if not claim or not cited_ids or any(identifier not in citation_by_id for identifier in cited_ids):
                failures.append("KNOWLEDGE_INLINE_CLAIM_CITATION_INVALID")
                continue
            cited_text = " ".join(
                str(citation_by_id[identifier].get("text") or citation_by_id[identifier].get("citation_text") or "")
                for identifier in cited_ids
            )
            normalized_claim = "".join(claim.casefold().split())
            normalized_evidence = "".join(cited_text.casefold().split())
            if normalized_claim not in normalized_evidence:
                failures.append("KNOWLEDGE_CLAIM_NOT_ENTAILED_BY_FROZEN_CITATION")
    return failures


def _data_failures(
    data: dict[str, Any], expected_value: Decimal, expected_signature: str | None = None,
) -> list[str]:
    failures: list[str] = []
    guard = data.get("guard") if isinstance(data.get("guard"), dict) else {}
    execution = data.get("execution") if isinstance(data.get("execution"), dict) else {}
    oracle = data.get("oracle") if isinstance(data.get("oracle"), dict) else {}
    if str(data.get("status")) != "SUCCEEDED":
        failures.append("DATA_STATUS_NOT_SUCCEEDED")
    normalized_sql = str(guard.get("normalized_sql") or "").lstrip().upper()
    if guard.get("allowed") is not True or not normalized_sql.startswith(("SELECT ", "WITH ")):
        failures.append("DATA_SQL_GUARD_NOT_PROVEN")
    rows = execution.get("rows") if isinstance(execution.get("rows"), list) else []
    columns = execution.get("columns") if isinstance(execution.get("columns"), list) else []
    actual_signature = str(execution.get("result_signature") or "")
    independent_signature = _independent_result_signature(columns, rows)
    if str(execution.get("status")) != "SUCCEEDED" or len(actual_signature) != 64:
        failures.append("DATA_EXECUTION_NOT_PROVEN")
    if actual_signature != independent_signature:
        failures.append("DATA_RESULT_SIGNATURE_NOT_INDEPENDENTLY_REPRODUCED")
    if expected_signature and actual_signature != expected_signature:
        failures.append("DATA_FROZEN_RESULT_SIGNATURE_MISMATCH")
    if str(oracle.get("status")) != "PASSED":
        failures.append("DATA_ORACLE_NOT_PASSED")
    values = [
        decimal
        for row in rows[:1] if isinstance(row, dict)
        for value in row.values()
        for decimal in [_decimal(value)]
        if decimal is not None
    ]
    if expected_value not in values:
        failures.append("DATA_EXPECTED_VALUE_NOT_PROVEN")
    return failures


def validate_business_result(
    kind: str,
    terminal: dict[str, Any] | None,
    *,
    expected_data_value: Decimal,
    expected_data_signature: str | None = None,
) -> tuple[str | None, bool, tuple[str, ...]]:
    if not isinstance(terminal, dict):
        return None, False, ("TERMINAL_PAYLOAD_MISSING",)
    observed_route, analysis = _analysis_payload(terminal)
    expected_route = {
        "DATA": "DATA_QUERY",
        "RAG": "KNOWLEDGE_QUERY",
        "HYBRID": "HYBRID_ANALYSIS",
        "AGENT": "COMPLEX_ANALYSIS",
        "FILE": "FILE_QUERY",
        "VISION": "MULTIMODAL_QUERY",
    }[kind]
    failures: list[str] = []
    if observed_route != expected_route:
        failures.append("OBSERVED_ROUTE_MISMATCH")

    if kind == "DATA":
        primary = analysis.get("primary") if isinstance(analysis.get("primary"), dict) else {}
        failures.extend(_data_failures(primary, expected_data_value, expected_data_signature))
    elif kind == "RAG":
        primary = analysis.get("primary") if isinstance(analysis.get("primary"), dict) else {}
        citations = primary.get("citations") if isinstance(primary.get("citations"), list) else []
        guard = primary.get("answer_guard_evidence") if isinstance(primary.get("answer_guard_evidence"), dict) else {}
        citation_ids = {
            str(item.get("citation_id")) for item in citations if isinstance(item, dict) and item.get("citation_id")
        }
        cited_ids = {str(item) for item in guard.get("cited_ids") or []}
        if str(analysis.get("status")) != "SUCCEEDED" or str(primary.get("status")) != "SUCCEEDED":
            failures.append("RAG_STATUS_NOT_SUCCEEDED")
        failures.extend(_independent_knowledge_failures(primary, require_inline_claims=True))
        if not citations or not all(
            isinstance(item, dict)
            and item.get("citation_id") and item.get("document_id") and item.get("document_version_id")
            and item.get("chunk_id") and item.get("source") and item.get("locator")
            for item in citations
        ):
            failures.append("RAG_CITATION_LOCATOR_NOT_PROVEN")
        if (
            primary.get("answer_guard") != "PASSED"
            or guard.get("status") != "PASSED"
            or float(guard.get("citation_accuracy") or 0.0) < 0.95
            or int(guard.get("prompt_injection_evidence_used", -1)) != 0
            or int(guard.get("factual_units") or 0) <= 0
            or not cited_ids
            or not cited_ids <= citation_ids
        ):
            failures.append("RAG_CITATION_GUARD_CLAIM_EVIDENCE_NOT_PROVEN")
    elif kind == "HYBRID":
        primary = analysis.get("primary") if isinstance(analysis.get("primary"), dict) else {}
        data = primary.get("data") if isinstance(primary.get("data"), dict) else {}
        knowledge = primary.get("knowledge") if isinstance(primary.get("knowledge"), dict) else {}
        failures.extend(_data_failures(data, expected_data_value, expected_data_signature))
        failures.extend(_independent_knowledge_failures(knowledge, require_inline_claims=True))
        citations = knowledge.get("citations") if isinstance(knowledge.get("citations"), list) else []
        guard = knowledge.get("answer_guard_evidence") if isinstance(knowledge.get("answer_guard_evidence"), dict) else {}
        citation_ids = {
            str(item.get("citation_id")) for item in citations if isinstance(item, dict) and item.get("citation_id")
        }
        cited_ids = {str(item) for item in guard.get("cited_ids") or []}
        if primary.get("evidence_merge") != "ORACLE_PASSED_AND_CITATIONS_VERIFIED":
            failures.append("HYBRID_VERIFIED_MERGE_NOT_PROVEN")
        if (
            str(analysis.get("status")) != "SUCCEEDED"
            or str(primary.get("status")) != "SUCCEEDED"
            or analysis.get("fallback_used") is True
            or not citations
            or not all(
                isinstance(item, dict)
                and item.get("citation_id") and item.get("document_id") and item.get("document_version_id")
                and item.get("chunk_id") and item.get("source") and item.get("locator")
                for item in citations
            )
            or knowledge.get("answer_guard") != "PASSED"
            or guard.get("status") != "PASSED"
            or float(guard.get("citation_accuracy") or 0.0) < 0.95
            or int(guard.get("prompt_injection_evidence_used", -1)) != 0
            or int(guard.get("factual_units") or 0) <= 0
            or not cited_ids
            or not cited_ids <= citation_ids
        ):
            failures.append("HYBRID_CITATION_LOCATOR_GUARD_CLAIM_NOT_PROVEN")
    elif kind == "AGENT":
        primary = analysis.get("primary") if isinstance(analysis.get("primary"), dict) else {}
        steps = primary.get("steps") if isinstance(primary.get("steps"), list) else []
        tools = {str(item.get("tool_name")) for item in steps if isinstance(item, dict) and item.get("tool_name")}
        allowed_tools = {
            "QUERY_DATA", "RETRIEVE_KNOWLEDGE", "VERIFY_RESULT",
            "VERIFY_CITATION", "GENERATE_CHART", "GENERATE_INSIGHT",
        }
        allowed_roles = {
            "PlannerAgent", "DataAnalystAgent", "KnowledgeAgent", "VerificationAgent", "InsightAgent",
        }
        roles = {str(item.get("agent_role")) for item in steps if isinstance(item, dict) and item.get("agent_role")}
        verification = primary.get("verification") if isinstance(primary.get("verification"), dict) else {}
        data_evidence = primary.get("data_evidence") if isinstance(primary.get("data_evidence"), dict) else {}
        knowledge_evidence = (
            primary.get("knowledge_evidence") if isinstance(primary.get("knowledge_evidence"), dict) else {}
        )
        failures.extend(_data_failures(data_evidence, expected_data_value, expected_data_signature))
        failures.extend(_independent_knowledge_failures(knowledge_evidence, require_inline_claims=False))
        answer = str(primary.get("answer") or "")
        data_rows = (
            (data_evidence.get("execution") or {}).get("rows")
            if isinstance(data_evidence.get("execution"), dict) else []
        )
        expected_answer_numbers = _numeric_claims(data_rows) | {expected_data_value}
        actual_answer_numbers = _numeric_claims(answer)
        if expected_data_value not in actual_answer_numbers:
            failures.append("AGENT_ANSWER_FROZEN_VALUE_NOT_PROVEN")
        if actual_answer_numbers - expected_answer_numbers:
            failures.append("AGENT_ANSWER_UNMATCHED_NUMERIC_CLAIM")
        if EXPECTED_REVENUE_KNOWLEDGE_TITLE not in answer:
            failures.append("AGENT_ANSWER_FROZEN_KNOWLEDGE_NOT_PROVEN")
        if str(primary.get("status")) != "SUCCEEDED" or analysis.get("fallback_used") is True:
            failures.append("AGENT_STATUS_OR_FALLBACK_INVALID")
        if primary.get("trace_complete") is not True or not steps:
            failures.append("AGENT_TRACE_NOT_COMPLETE")
        if tools != allowed_tools or int(primary.get("tool_call_count") or 0) != len(allowed_tools):
            failures.append("AGENT_TOOLS_NOT_PROVEN")
        if roles != allowed_roles or not all(str(item.get("status")) == "SUCCEEDED" for item in steps if isinstance(item, dict)):
            failures.append("AGENT_ROLES_OR_STEP_SUCCESS_NOT_PROVEN")
        if not verification or not all(bool(value) for value in verification.values()):
            failures.append("AGENT_SELF_REPORTED_VERIFICATION_INVALID")
    elif kind == "FILE":
        response = terminal.get("response") if isinstance(terminal.get("response"), dict) else {}
        assistant = response.get("assistant_message") if isinstance(response.get("assistant_message"), dict) else {}
        payload = assistant.get("response_payload") if isinstance(assistant.get("response_payload"), dict) else {}
        file_analysis = payload.get("file_analysis") if isinstance(payload.get("file_analysis"), dict) else {}
        result = file_analysis.get("result") if isinstance(file_analysis.get("result"), dict) else {}
        rows = result.get("rows") if isinstance(result.get("rows"), list) else []
        sums = [
            decimal
            for row in rows if isinstance(row, dict)
            for key, value in row.items() if key in {"sum", "revenue", "value"} or key.endswith("_sum")
            for decimal in [_decimal(value)] if decimal is not None
        ]
        if str(file_analysis.get("status")) != "SUCCEEDED" or result.get("exact_for_full_file") is not True:
            failures.append("FILE_FULL_RESULT_NOT_PROVEN")
        file_signature = str(result.get("result_signature") or "")
        if (
            len(file_signature) != 64
            or file_signature != _independent_result_signature(result.get("columns"), rows)
        ):
            failures.append("FILE_RESULT_SIGNATURE_NOT_PROVEN")
        if sum(sums, Decimal(0)) != Decimal(FILE_EXPECTED_REVENUE):
            failures.append("FILE_EXPECTED_VALUE_NOT_PROVEN")
    elif kind == "VISION":
        response = terminal.get("response") if isinstance(terminal.get("response"), dict) else {}
        assistant = response.get("assistant_message") if isinstance(response.get("assistant_message"), dict) else {}
        payload = assistant.get("response_payload") if isinstance(assistant.get("response_payload"), dict) else {}
        evidences = payload.get("visual_evidence") if isinstance(payload.get("visual_evidence"), list) else []
        claims = [
            claim
            for evidence in evidences if isinstance(evidence, dict)
            for claim in (evidence.get("claims") or []) if isinstance(claim, dict)
        ]
        numeric_claims = [(item, _decimal(item.get("value"))) for item in claims if _decimal(item.get("value")) is not None]
        values = {value for _item, value in numeric_claims}
        expected = {Decimal(value) for value in VISION_EXPECTED_VALUES}
        if not evidences or not all(
            len(str(item.get("signature") or "")) == 64
            and str(item.get("signature")) == hashlib.sha256(json.dumps(
                {key: value for key, value in item.items() if key != "signature"},
                ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            ).encode("utf-8")).hexdigest()
            and item.get("injection_detected") is False
            for item in evidences if isinstance(item, dict)
        ):
            failures.append("VISION_SAFE_EVIDENCE_NOT_PROVEN")
        if (
            values != expected
            or len(numeric_claims) != len(expected)
            or not all(float(item.get("confidence") or 0.0) >= 0.5 and item.get("locator") for item, _value in numeric_claims)
        ):
            failures.append("VISION_EXPECTED_VALUES_NOT_PROVEN")
    return observed_route, not failures, tuple(failures)


def _sse_observation(
    client: httpx.Client,
    *,
    path: str,
    payload: dict[str, Any],
    user_index: int,
    kind: str,
    expected_data_value: Decimal,
    expected_data_signature: str | None = None,
    clock: Callable[[], float] = time.perf_counter,
) -> ApiSample:
    started = clock()
    ttfe: float | None = None
    ttft: float | None = None
    status_code = 0
    event_count = 0
    terminal_events: list[str] = []
    terminal_payload: dict[str, Any] | None = None
    current_event: str | None = None
    error_code: str | None = None
    try:
        with client.stream("POST", path, json=payload) as response:
            status_code = response.status_code
            if response.status_code != 200:
                error_code = f"HTTP_{response.status_code}"
            else:
                for line in response.iter_lines():
                    if line.startswith("event:"):
                        current_event = line.split(":", 1)[1].strip()
                        event_type = current_event
                        event_count += 1
                        elapsed_ms = (clock() - started) * 1000.0
                        if ttfe is None:
                            ttfe = elapsed_ms
                        if event_type == "answer.delta" and ttft is None:
                            ttft = elapsed_ms
                        if event_type in _TERMINAL_EVENTS:
                            terminal_events.append(event_type)
                        continue
                    if line.startswith("data:") and current_event in _TERMINAL_EVENTS:
                        try:
                            parsed = json.loads(line.split(":", 1)[1].strip())
                            terminal_payload = parsed if isinstance(parsed, dict) else None
                        except json.JSONDecodeError:
                            terminal_payload = None
    except Exception as exc:
        error_code = type(exc).__name__
    total_ms = (clock() - started) * 1000.0
    terminal = terminal_events[-1] if terminal_events else None
    observed_route, business_valid, business_checks = validate_business_result(
        kind,
        terminal_payload,
        expected_data_value=expected_data_value,
        expected_data_signature=expected_data_signature,
    )
    success = (
        status_code == 200
        and ttfe is not None
        and ttft is not None
        and terminal == "run.completed"
        and len(terminal_events) == 1
        and business_valid
    )
    if error_code is None and not success:
        error_code = "SSE_CONTRACT_FAILED"
    return ApiSample(
        user_index=user_index,
        kind=kind,
        ttfe_ms=round(ttfe or 0.0, 3),
        ttft_ms=round(ttft or 0.0, 3),
        total_ms=round(total_ms, 3),
        status_code=status_code,
        event_count=event_count,
        terminal_event=terminal,
        terminal_count=len(terminal_events),
        success=success,
        error_code=error_code,
        request_id=str(payload.get("idempotency_key") or payload.get("client_message_id") or ""),
        observed_route=observed_route,
        business_valid=business_valid,
        business_checks=business_checks,
    )


def execute_request(
    user: UserRuntime,
    *,
    kind: str,
    request_id: str,
    datasource_id: str,
    semantic_model_id: str,
    expected_data_value: Decimal,
    expected_data_signature: str,
    data_question: str,
) -> ApiSample:
    if kind in {"DATA", "RAG", "HYBRID", "AGENT"}:
        route = {
            "DATA": "DATA_QUERY",
            "RAG": "KNOWLEDGE_QUERY",
            "HYBRID": "HYBRID_ANALYSIS",
            "AGENT": "COMPLEX_ANALYSIS",
        }[kind]
        payload: dict[str, Any] = {
            "question": data_question if kind == "DATA" else QUESTIONS[kind],
            "route": route,
            "idempotency_key": request_id,
        }
        if kind in {"DATA", "HYBRID", "AGENT"}:
            payload.update({"datasource_id": datasource_id, "semantic_model_id": semantic_model_id})
        return _sse_observation(
            user.client,
            path="/api/v1/analysis/stream",
            payload=payload,
            user_index=user.index,
            kind=kind,
            expected_data_value=expected_data_value,
            expected_data_signature=expected_data_signature,
        )

    attachment_id = user.csv_attachment_id if kind == "FILE" else user.image_attachment_id
    route = "FILE_QUERY" if kind == "FILE" else "MULTIMODAL_QUERY"
    payload = {
        "conversation_id": user.conversation_id,
        "content": QUESTIONS[kind],
        "client_message_id": request_id,
        "attachment_ids": [attachment_id],
        "route": route,
    }
    if kind == "VISION":
        payload["datasource_id"] = datasource_id
        payload["semantic_model_id"] = semantic_model_id
    return _sse_observation(
        user.client,
        path="/api/v1/chat/stream",
        payload=payload,
        user_index=user.index,
        kind=kind,
        expected_data_value=expected_data_value,
        expected_data_signature=expected_data_signature,
    )


class BackendProcessProbe:
    def __init__(self, pid: int) -> None:
        if pid <= 0:
            raise ValueError("backend pid must be positive")
        self.pid = pid
        self._state: tuple[int, int] | None = None

    def sample(self) -> tuple[float | None, float | None]:
        if os.name == "nt":
            return self._windows()
        if platform.system() == "Linux":
            return self._linux()
        return None, None

    @staticmethod
    def _filetime(value: Any) -> int:
        return (int(value.dwHighDateTime) << 32) | int(value.dwLowDateTime)

    def _windows(self) -> tuple[float | None, float | None]:
        class FileTime(ctypes.Structure):
            _fields_ = [("dwLowDateTime", ctypes.c_uint32), ("dwHighDateTime", ctypes.c_uint32)]

        size_t = ctypes.c_size_t

        class ProcessMemory(ctypes.Structure):
            _fields_ = [
                ("cb", ctypes.c_uint32), ("PageFaultCount", ctypes.c_uint32),
                ("PeakWorkingSetSize", size_t), ("WorkingSetSize", size_t),
                ("QuotaPeakPagedPoolUsage", size_t), ("QuotaPagedPoolUsage", size_t),
                ("QuotaPeakNonPagedPoolUsage", size_t), ("QuotaNonPagedPoolUsage", size_t),
                ("PagefileUsage", size_t), ("PeakPagefileUsage", size_t),
            ]

        handle = ctypes.windll.kernel32.OpenProcess(0x0400 | 0x0010, False, self.pid)
        if not handle:
            raise RuntimeError("BACKEND_PROCESS_NOT_FOUND")
        try:
            created, exited, kernel, user = FileTime(), FileTime(), FileTime(), FileTime()
            idle_system, kernel_system, user_system = FileTime(), FileTime(), FileTime()
            if not ctypes.windll.kernel32.GetProcessTimes(
                handle, ctypes.byref(created), ctypes.byref(exited), ctypes.byref(kernel), ctypes.byref(user)
            ):
                raise RuntimeError("BACKEND_PROCESS_TIMES_UNAVAILABLE")
            if not ctypes.windll.kernel32.GetSystemTimes(
                ctypes.byref(idle_system), ctypes.byref(kernel_system), ctypes.byref(user_system)
            ):
                raise RuntimeError("SYSTEM_TIMES_UNAVAILABLE")
            process_value = self._filetime(kernel) + self._filetime(user)
            system_value = self._filetime(kernel_system) + self._filetime(user_system)
            cpu: float | None = None
            if self._state is not None and system_value > self._state[1]:
                cpu = max(0.0, min(100.0, (process_value - self._state[0]) * 100.0 / (system_value - self._state[1])))
            self._state = (process_value, system_value)
            memory = ProcessMemory()
            memory.cb = ctypes.sizeof(memory)
            if not ctypes.windll.psapi.GetProcessMemoryInfo(handle, ctypes.byref(memory), memory.cb):
                raise RuntimeError("BACKEND_MEMORY_UNAVAILABLE")
            return cpu, round(int(memory.WorkingSetSize) / (1024 * 1024), 3)
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)

    def _linux(self) -> tuple[float | None, float | None]:
        stat = Path(f"/proc/{self.pid}/stat").read_text(encoding="utf-8")
        fields = stat.rsplit(") ", 1)[1].split()
        process_value = int(fields[11]) + int(fields[12])
        system_fields = [int(item) for item in Path("/proc/stat").read_text().splitlines()[0].split()[1:]]
        system_value = sum(system_fields)
        cpu: float | None = None
        if self._state is not None and system_value > self._state[1]:
            cpu = max(0.0, min(100.0, (process_value - self._state[0]) * 100.0 / (system_value - self._state[1])))
        self._state = (process_value, system_value)
        status = Path(f"/proc/{self.pid}/status").read_text(encoding="utf-8")
        rss_kib = next(int(line.split()[1]) for line in status.splitlines() if line.startswith("VmRSS:"))
        return cpu, round(rss_kib / 1024, 3)


class DatabaseConnectionProbe:
    def __init__(self, database_url: str, *, metadata_schema: str) -> None:
        validate_local_postgres_url(database_url)
        self.engine: Engine = create_engine(
            database_url,
            pool_pre_ping=True,
            pool_size=1,
            max_overflow=0,
            connect_args={
                "application_name": "chatbi-v13-phase5-api-telemetry",
                "options": f"-csearch_path={metadata_schema}",
            },
        )

    def sample(self) -> tuple[int, int]:
        with self.engine.connect() as connection:
            row = connection.execute(text(
                "SELECT COUNT(*)::integer AS total, "
                "COUNT(*) FILTER (WHERE state = 'active')::integer AS active "
                "FROM pg_stat_activity WHERE datname = current_database()"
            )).mappings().one()
        return int(row["total"]), int(row["active"])

    def close(self) -> None:
        self.engine.dispose()


def run_api_load(
    users: Sequence[UserRuntime],
    *,
    duration_seconds: int,
    request_prefix: str,
    datasource_id: str,
    semantic_model_id: str,
    expected_data_value: Decimal,
    expected_data_signature: str,
    data_question: str,
    sample_resources: Callable[[], ResourceSample],
    sample_interval_seconds: float = 1.0,
) -> tuple[list[ApiSample], list[ResourceSample], float]:
    if not _REQUEST_PREFIX_RE.fullmatch(request_prefix):
        raise ValueError("invalid Phase5 request prefix")
    observations: list[ApiSample] = []
    resources: list[ResourceSample] = []
    lock = threading.Lock()
    stop = threading.Event()
    barrier = threading.Barrier(len(users) + 1)
    deadline = 0.0

    def worker(user: UserRuntime) -> None:
        nonlocal deadline
        barrier.wait()
        sequence = 0
        while time.perf_counter() < deadline:
            kind = workload_kind(user.index, sequence, len(users))
            request_id = f"{request_prefix}{user.index:02d}-{sequence:08d}"
            sample = execute_request(
                user,
                kind=kind,
                request_id=request_id,
                datasource_id=datasource_id,
                semantic_model_id=semantic_model_id,
                expected_data_value=expected_data_value,
                expected_data_signature=expected_data_signature,
                data_question=data_question,
            )
            with lock:
                observations.append(sample)
            sequence += 1

    def sampler() -> None:
        while not stop.is_set():
            try:
                sample = sample_resources()
            except Exception:
                sample = ResourceSample(None, None, None, None, -1, -1)
            with lock:
                resources.append(sample)
            stop.wait(sample_interval_seconds)

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=len(users), thread_name_prefix="phase5-api-user") as executor:
        futures = [executor.submit(worker, user) for user in users]
        sample_thread = threading.Thread(target=sampler, name="phase5-api-resource", daemon=True)
        sample_thread.start()
        deadline = time.perf_counter() + duration_seconds
        barrier.wait()
        for future in futures:
            future.result()
        stop.set()
        sample_thread.join(timeout=max(2.0, sample_interval_seconds * 2))
    return observations, resources, time.perf_counter() - started


def summarize_api_load(
    observations: Sequence[ApiSample],
    resources: Sequence[ResourceSample],
    *,
    elapsed_seconds: float,
    configured_users: int,
) -> dict[str, Any]:
    successes = sum(item.success for item in observations)
    errors: dict[str, int] = {}
    by_kind: dict[str, dict[str, Any]] = {}
    business_failures: dict[str, int] = {}
    for item in observations:
        if item.error_code:
            errors[item.error_code] = errors.get(item.error_code, 0) + 1
        for check in item.business_checks:
            business_failures[check] = business_failures.get(check, 0) + 1
    for kind in ("DATA", "RAG", "HYBRID", "AGENT", "FILE", "VISION"):
        rows = [item for item in observations if item.kind == kind]
        by_kind[kind] = {
            "requests": len(rows),
            "success_rate": round(sum(item.success for item in rows) / len(rows), 6) if rows else 0.0,
            "business_validation_rate": round(sum(item.business_valid for item in rows) / len(rows), 6) if rows else 0.0,
            "observed_routes": sorted({item.observed_route for item in rows if item.observed_route}),
            "ttfe_ms": distribution([item.ttfe_ms for item in rows]),
            "ttft_ms": distribution([item.ttft_ms for item in rows]),
            "total_ms": distribution([item.total_ms for item in rows]),
        }
    resource_metrics = {
        "host_cpu_percent": distribution([item.host_cpu_percent for item in resources if item.host_cpu_percent is not None]),
        "host_ram_percent": distribution([item.host_ram_percent for item in resources if item.host_ram_percent is not None]),
        "backend_cpu_percent": distribution([item.backend_cpu_percent for item in resources if item.backend_cpu_percent is not None]),
        "backend_rss_mib": distribution([item.backend_rss_mib for item in resources if item.backend_rss_mib is not None]),
        "db_connections": distribution([float(item.db_connections) for item in resources if item.db_connections >= 0]),
        "db_active_connections": distribution([float(item.db_active_connections) for item in resources if item.db_active_connections >= 0]),
        "sample_count": len(resources),
        "complete_sample_count": sum(
            item.host_cpu_percent is not None
            and item.host_ram_percent is not None
            and item.backend_cpu_percent is not None
            and item.backend_rss_mib is not None
            and item.db_connections >= 0
            for item in resources
        ),
    }
    return {
        "requests": len(observations),
        "successes": successes,
        "failures": len(observations) - successes,
        "success_rate": round(successes / len(observations), 6) if observations else 0.0,
        "actual_elapsed_seconds": round(elapsed_seconds, 3),
        "throughput_rps": round(len(observations) / max(elapsed_seconds, 0.001), 3),
        "active_users": len({item.user_index for item in observations}),
        "configured_users": configured_users,
        "terminal_contract_violations": sum(item.terminal_count != 1 for item in observations),
        "business_validation_rate": round(sum(item.business_valid for item in observations) / len(observations), 6) if observations else 0.0,
        "kind_coverage": sorted({item.kind for item in observations}),
        "by_kind": by_kind,
        "resources": resource_metrics,
        "errors": dict(sorted(errors.items())),
        "business_failures": dict(sorted(business_failures.items())),
    }


def aggregate_scoped_cost_ledger(
    entries: Sequence[dict[str, Any]],
    *,
    base_coverage: dict[str, Any],
    observations: Sequence[ApiSample],
    request_prefix: str,
    kimi_pricing: dict[str, float],
) -> dict[str, Any]:
    scoped = [item for item in entries if str(item.get("request_id") or "").startswith(request_prefix)]
    billable_kinds = {"DATA", "RAG", "HYBRID", "AGENT", "VISION"}
    expected_ids = {item.request_id for item in observations if item.kind in billable_kinds and item.request_id}
    route_by_request = {
        item.request_id: str(item.observed_route or "NOT_PROVEN")
        for item in observations if item.request_id
    }
    observed_ids = {str(item.get("request_id")) for item in scoped if item.get("request_id")}
    matched = expected_ids & observed_ids
    missing = expected_ids - observed_ids
    coverage = {
        "source": base_coverage.get("source"),
        "database_complete": bool(base_coverage.get("complete")),
        "complete": bool(base_coverage.get("complete")) and not missing and bool(expected_ids),
        "warnings": list(base_coverage.get("warnings") or []),
        "scope": "EXACT_PREFIX_AND_LOAD_WINDOW",
        "expected_billable_requests": len(expected_ids),
        "covered_billable_requests": len(matched),
        "missing_billable_requests": len(missing),
        "request_coverage": round(len(matched) / len(expected_ids), 6) if expected_ids else 0.0,
        "route_source": "VALIDATED_SSE_OBSERVED_ROUTE",
        "billing_expectation": {
            "MODEL_REQUIRED": sorted(billable_kinds),
            "MODEL_OPTIONAL_DETERMINISTIC": ["FILE"],
        },
        "request_prefix_sha256": hashlib.sha256(request_prefix.encode()).hexdigest(),
    }
    result = aggregate_cost_ledger(scoped, coverage=coverage, kimi_pricing=kimi_pricing)
    by_route: dict[str, dict[str, Any]] = {}
    by_provider: dict[str, dict[str, Any]] = {}
    for key, target in (("route", by_route), ("provider", by_provider)):
        def group_name(item: dict[str, Any]) -> str:
            if key == "route":
                return route_by_request.get(str(item.get("request_id") or ""), "UNMAPPED")
            return str(item.get(key) or "UNKNOWN")

        groups = sorted({group_name(item) for item in scoped})
        for group in groups:
            rows = [item for item in scoped if group_name(item) == group]
            target[group] = {
                "invocations": len(rows),
                "unique_requests": len({str(item.get("request_id")) for item in rows}),
                "input_tokens": sum(int(item.get("input_tokens") or 0) for item in rows),
                "output_tokens": sum(int(item.get("output_tokens") or 0) for item in rows),
                "cost_cny": round(sum(float(item.get("cost_cny") or 0.0) for item in rows), 8),
            }
    digest_rows = sorted(
        (
            str(item.get("request_id") or ""), str(item.get("provider") or ""),
            str(item.get("route") or ""), int(item.get("input_tokens") or 0),
            int(item.get("output_tokens") or 0), round(float(item.get("cost_cny") or 0.0), 8),
        )
        for item in scoped
    )
    return {
        **result,
        "by_route": by_route,
        "by_provider": by_provider,
        "scoped_ledger_sha256": hashlib.sha256(
            json.dumps(digest_rows, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
    }


def evaluate_api_gate(
    *,
    users: int,
    duration_seconds: int,
    metrics: dict[str, Any] | None,
    core_data: dict[str, Any] | None,
    cost: dict[str, Any] | None,
    cleanup: dict[str, Any],
    runtime_error: str | None,
) -> list[str]:
    failures: list[str] = []
    if runtime_error:
        failures.append(f"runtime_error:{runtime_error}")
    if users < RELEASE_THRESHOLDS["min_users"]:
        failures.append("authenticated_users_below_20")
    if duration_seconds < RELEASE_THRESHOLDS["min_duration_seconds"]:
        failures.append("duration_below_15_minutes")
    if core_data is None:
        failures.append("backend_core_data100_missing")
    elif (
        core_data.get("status") != "PASS"
        or core_data.get("total") != 100
        or core_data.get("passed") != 100
        or core_data.get("sql_execution_rate") != 1.0
        or core_data.get("result_value_accuracy") != 1.0
        or core_data.get("dangerous_sql_block_rate") != 1.0
    ):
        failures.append("backend_core_data100_not_strict_100_of_100")
    expected_attachments = users * 2
    cleanup_checks = {
        "attachment_delete_not_exact": cleanup.get("attachment_delete_204") != expected_attachments,
        "attachment_absence_not_verified": cleanup.get("attachment_absence_404") != expected_attachments,
        "conversation_delete_not_exact": cleanup.get("conversation_delete_204") != users,
        "conversation_absence_not_verified": cleanup.get("conversation_absence_404") != users,
        "logout_not_exact": cleanup.get("logout_204") != users,
        "fixture_directory_not_removed": not cleanup.get("fixture_directory_absent", False),
        "metadata_temp_users_not_deleted": cleanup.get("metadata_users_deleted") != users,
        "metadata_temp_grants_not_deleted": cleanup.get("metadata_grants_deleted") != users * 2,
        "metadata_temp_sessions_not_deleted": cleanup.get("metadata_sessions_deleted") != users,
        "metadata_conversations_remained_after_api_cleanup": cleanup.get("metadata_conversations_before_delete") != 0,
        "metadata_attachments_remained_after_api_cleanup": cleanup.get("metadata_attachments_before_delete") != 0,
        "metadata_messages_remained_after_api_cleanup": cleanup.get("metadata_messages_before_delete") != 0,
        "metadata_absence_not_verified": not cleanup.get("metadata_absence_verified", False),
    }
    failures.extend(code for code, failed in cleanup_checks.items() if failed)
    if metrics is None:
        failures.append("api_metrics_missing")
    else:
        expected_kinds = {"DATA", "RAG", "HYBRID", "AGENT", "FILE", "VISION"}
        if float(metrics.get("actual_elapsed_seconds") or 0.0) < float(duration_seconds):
            failures.append("actual_api_load_duration_below_15_minutes")
        if metrics["active_users"] != users:
            failures.append("not_all_authenticated_users_active")
        if set(metrics["kind_coverage"]) != expected_kinds:
            failures.append("api_mixed_route_coverage_incomplete")
        if metrics["success_rate"] < RELEASE_THRESHOLDS["min_success_rate"]:
            failures.append("api_success_rate_below_gate")
        if metrics["terminal_contract_violations"] != 0:
            failures.append("sse_terminal_contract_violation")
        if metrics.get("business_validation_rate") != 1.0:
            failures.append("sse_business_result_not_proven")
        expected_routes = {
            "DATA": "DATA_QUERY", "RAG": "KNOWLEDGE_QUERY",
            "HYBRID": "HYBRID_ANALYSIS", "AGENT": "COMPLEX_ANALYSIS",
            "FILE": "FILE_QUERY", "VISION": "MULTIMODAL_QUERY",
        }
        for kind in expected_kinds:
            row = metrics["by_kind"][kind]
            if row["requests"] <= 0 or row["success_rate"] < RELEASE_THRESHOLDS["min_success_rate"]:
                failures.append(f"{kind.lower()}_route_failed")
            if row.get("business_validation_rate") != 1.0 or row.get("observed_routes") != [expected_routes[kind]]:
                failures.append(f"{kind.lower()}_business_result_not_proven")
            if row["ttfe_ms"]["p95"] > RELEASE_THRESHOLDS["max_ttfe_p95_ms"]:
                failures.append(f"{kind.lower()}_ttfe_p95_above_gate")
            if row["ttft_ms"]["p95"] > RELEASE_THRESHOLDS["max_ttft_p95_ms"]:
                failures.append(f"{kind.lower()}_ttft_p95_above_gate")
            if row["total_ms"]["p95"] > RELEASE_THRESHOLDS["max_total_p95_ms"]:
                failures.append(f"{kind.lower()}_total_p95_above_gate")
            if row["total_ms"]["p99"] > RELEASE_THRESHOLDS["max_total_p99_ms"]:
                failures.append(f"{kind.lower()}_total_p99_above_gate")
        resource = metrics["resources"]
        minimum_resource_samples = math.ceil(float(duration_seconds) / 2)
        if (
            resource["sample_count"] < minimum_resource_samples
            or resource["complete_sample_count"] < minimum_resource_samples
        ):
            failures.append("api_resource_telemetry_coverage_below_half_duration")
        if resource["host_cpu_percent"]["p99"] > RELEASE_THRESHOLDS["max_host_cpu_p99_percent"]:
            failures.append("host_cpu_p99_above_gate")
        if resource["host_ram_percent"]["p99"] > RELEASE_THRESHOLDS["max_host_ram_p99_percent"]:
            failures.append("host_ram_p99_above_gate")
        if resource["backend_cpu_percent"]["p99"] > RELEASE_THRESHOLDS["max_backend_cpu_p99_percent"]:
            failures.append("backend_cpu_p99_above_gate")
        if resource["db_connections"]["max"] > RELEASE_THRESHOLDS["max_db_connections"]:
            failures.append("db_connections_above_gate")
    if cost is None:
        failures.append("real_model_invocation_cost_ledger_missing")
    else:
        if cost["coverage"].get("source") != "MODEL_INVOCATION_LEDGER" or not cost["coverage"].get("complete"):
            failures.append("model_invocation_ledger_coverage_incomplete")
        if cost["coverage"].get("scope") != "EXACT_PREFIX_AND_LOAD_WINDOW" or cost["coverage"].get("request_coverage") != 1.0:
            failures.append("model_invocation_request_coverage_incomplete")
        if cost["invocations"] <= 0 or cost["token_bearing_invocations"] <= 0:
            failures.append("model_invocation_ledger_window_empty")
        if cleanup.get("metadata_load_model_invocations_removed") != cost["invocations"]:
            failures.append("model_invocation_cleanup_count_mismatch")
        expected_cost_routes = {
            "DATA_QUERY", "KNOWLEDGE_QUERY", "HYBRID_ANALYSIS", "COMPLEX_ANALYSIS", "MULTIMODAL_QUERY",
        }
        cost_routes = set(cost.get("by_route") or {})
        if not expected_cost_routes <= cost_routes or "NOT_PROVEN" in cost_routes or not cost.get("by_provider"):
            failures.append("model_invocation_route_provider_breakdown_incomplete")
        if cost["kimi_premium_share"] > RELEASE_THRESHOLDS["max_kimi_premium_share"]:
            failures.append("kimi_premium_share_above_0_10")
        if cost["saving_vs_all_premium"] < RELEASE_THRESHOLDS["min_saving_vs_all_premium"]:
            failures.append("saving_vs_all_premium_below_0_60")
    return sorted(set(failures))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ChatBI V1.3 Phase5 real authenticated API/SSE load gate")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--database-url", default=os.getenv("CHATBI_PHASE5_DATABASE_URL") or os.getenv("CHATBI_DATABASE_URL"))
    parser.add_argument("--metadata-schema", required=True, help="Already migrated isolated metadata schema used by Backend")
    parser.add_argument("--base-password-env", default="CHATBI_PHASE5_BASE_PASSWORD")
    parser.add_argument("--workspace-id", required=True)
    parser.add_argument("--datasource-id", required=True)
    parser.add_argument("--semantic-model-id", required=True)
    parser.add_argument("--core-data-manifest", type=Path, default=DEFAULT_CORE_DATA_MANIFEST)
    parser.add_argument("--load-data-case-id", default="G01", help="Frozen Core Data100 scalar case used by DATA/HYBRID validation")
    parser.add_argument("--backend-pid", type=int, required=True)
    parser.add_argument("--users", type=int, default=DEFAULT_API_USERS)
    parser.add_argument("--duration-seconds", type=int, default=DEFAULT_API_DURATION_SECONDS)
    parser.add_argument("--request-timeout-seconds", type=float, default=40.0)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def _git_sha() -> str | None:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True, check=False
    )
    return completed.stdout.strip() if completed.returncode == 0 else None


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.database_url:
        raise SystemExit("--database-url or CHATBI_PHASE5_DATABASE_URL is required")
    if args.users <= 0 or args.duration_seconds <= 0 or args.request_timeout_seconds <= 0:
        raise SystemExit("users, duration and request timeout must be positive")
    base_url = validate_backend_url(args.base_url)
    validate_local_postgres_url(args.database_url)
    request_prefix = f"phase5api-{hashlib.sha256(f'{time.time_ns()}:{os.getpid()}'.encode()).hexdigest()[:12]}-"
    base_password = os.getenv(args.base_password_env, "")
    if not base_password:
        raise SystemExit(f"external base password environment variable {args.base_password_env} is required")
    credentials = derive_credentials(base_password, request_prefix=request_prefix, users=args.users)
    core_manifest, core_cases = load_core_data_manifest(args.core_data_manifest)
    load_data_case, expected_data_value = select_load_data_case(core_cases, args.load_data_case_id)
    expected_data_signature = str(load_data_case["expected_signature"])
    started_at = _utc_now()
    fixture_directory, csv_path, png_path = create_fixtures()
    fixture_hashes = {
        "csv_sha256": hashlib.sha256(csv_path.read_bytes()).hexdigest(),
        "png_sha256": hashlib.sha256(png_path.read_bytes()).hexdigest(),
    }
    runtimes: list[UserRuntime] = []
    observations: list[ApiSample] = []
    metrics: dict[str, Any] | None = None
    cost: dict[str, Any] | None = None
    core_data: dict[str, Any] | None = None
    runtime_error: str | None = None
    cleanup = {
        "attachment_delete_204": 0,
        "attachment_absence_404": 0,
        "conversation_delete_204": 0,
        "conversation_absence_404": 0,
        "logout_204": 0,
        "fixture_directory_absent": False,
        "metadata_sessions_deleted": 0,
        "metadata_grants_deleted": 0,
        "metadata_users_deleted": 0,
        "metadata_conversations_before_delete": 0,
        "metadata_attachments_before_delete": 0,
        "metadata_messages_before_delete": 0,
        "metadata_model_invocations_removed": 0,
        "metadata_load_model_invocations_removed": 0,
        "metadata_query_runs_deleted": 0,
        "metadata_attachment_files_removed": 0,
        "metadata_absence_verified": False,
    }
    metadata = MetadataBootstrap(
        args.database_url,
        metadata_schema=args.metadata_schema,
        workspace_id=args.workspace_id,
        datasource_id=args.datasource_id,
        semantic_model_id=args.semantic_model_id,
        request_prefix=request_prefix,
    )
    bootstrap_receipt: BootstrapReceipt | None = None
    db_probe: DatabaseConnectionProbe | None = None
    load_started_at = _utc_now()
    load_completed_at = load_started_at

    try:
        bootstrap_receipt = metadata.bootstrap(credentials)
        csv_bytes = csv_path.read_bytes()
        png_bytes = png_path.read_bytes()
        with ThreadPoolExecutor(max_workers=args.users, thread_name_prefix="phase5-api-setup") as executor:
            futures = [executor.submit(
                prepare_user,
                index=index,
                credential=credential,
                base_url=base_url,
                workspace_id=args.workspace_id,
                csv_bytes=csv_bytes,
                png_bytes=png_bytes,
                timeout_seconds=args.request_timeout_seconds,
            ) for index, credential in enumerate(credentials)]
            setup_failures = 0
            for future in futures:
                try:
                    runtimes.append(future.result())
                except Exception:
                    setup_failures += 1
            if setup_failures:
                raise RuntimeError("AUTHENTICATED_USER_SETUP_FAILED")
        runtimes.sort(key=lambda item: item.index)
        if len({item.user_id for item in runtimes}) != args.users:
            raise RuntimeError("AUTHENTICATED_USER_IDENTITY_NOT_UNIQUE")

        core_data = run_core_data100(
            runtimes[0].client,
            core_cases,
            datasource_id=args.datasource_id,
            semantic_model_id=args.semantic_model_id,
        )

        host_probe = SystemProbe()
        process_probe = BackendProcessProbe(args.backend_pid)
        db_probe = DatabaseConnectionProbe(args.database_url, metadata_schema=args.metadata_schema)

        def sample_resources() -> ResourceSample:
            host_cpu, host_ram = host_probe.sample()
            backend_cpu, backend_rss = process_probe.sample()
            db_total, db_active = db_probe.sample()
            return ResourceSample(host_cpu, host_ram, backend_cpu, backend_rss, db_total, db_active)

        load_started_at = _utc_now()
        observations, resources, elapsed = run_api_load(
            runtimes,
            duration_seconds=args.duration_seconds,
            request_prefix=request_prefix,
            datasource_id=args.datasource_id,
            semantic_model_id=args.semantic_model_id,
            expected_data_value=expected_data_value,
            expected_data_signature=expected_data_signature,
            data_question=str(load_data_case["question"]),
            sample_resources=sample_resources,
        )
        load_completed_at = _utc_now()
        metrics = summarize_api_load(
            observations,
            resources,
            elapsed_seconds=elapsed,
            configured_users=args.users,
        )
        with Session(metadata.engine) as session:
            entries, coverage = cost_ledger_entries(
                session,
                workspace_id=args.workspace_id,
                from_at=load_started_at,
                to_at=load_completed_at,
            )
        pricing = json.loads((BACKEND_ROOT / "config" / "model_pricing.yaml").read_text(encoding="utf-8"))
        cost = aggregate_scoped_cost_ledger(
            entries,
            base_coverage=coverage,
            observations=observations,
            request_prefix=request_prefix,
            kimi_pricing=pricing["providers"]["kimi"],
        )
    except Exception as exc:
        runtime_error = type(exc).__name__
    finally:
        if db_probe is not None:
            db_probe.close()
        for runtime in runtimes:
            receipt = cleanup_user(runtime)
            for key, value in receipt.items():
                cleanup[key] += value
        try:
            cleanup.update(metadata.cleanup(bootstrap_receipt))
        except Exception as exc:
            runtime_error = runtime_error or type(exc).__name__
        finally:
            metadata.close()
        try:
            shutil.rmtree(fixture_directory, ignore_errors=False)
        except Exception:
            pass
        cleanup["fixture_directory_absent"] = not fixture_directory.exists()

    failures = evaluate_api_gate(
        users=args.users,
        duration_seconds=args.duration_seconds,
        metrics=metrics,
        core_data=core_data,
        cost=cost,
        cleanup=cleanup,
        runtime_error=runtime_error,
    )
    evidence = {
        "schema_version": "chatbi.v13.phase5.authenticated-api-load.v1",
        "suite": "CHATBI_V13_PHASE5_REAL_API_SSE_20X15M",
        "status": "PASS" if not failures else "FAIL",
        "tested_sha": _git_sha(),
        "started_at": _iso(started_at),
        "load_started_at": _iso(load_started_at),
        "load_completed_at": _iso(load_completed_at),
        "completed_at": _iso(_utc_now()),
        "config": {
            "users": args.users,
            "duration_seconds": args.duration_seconds,
            "production_default_duration_seconds": DEFAULT_API_DURATION_SECONDS,
            "transport": "REAL_AUTHENTICATED_BACKEND_API_SSE",
            "route_evidence_scope": "CALLER_PINNED_ROUTE_SPECIFIC_LOAD_NOT_ROUTER_CLASSIFICATION_EVIDENCE",
            "temporary_identity_bootstrap": "ATOMIC_APP_USER_RESOURCE_GRANT",
            "metadata_schema": args.metadata_schema,
            "workload_mix_percent": {
                kind: WORKLOAD_MIX.count(kind) for kind in ("DATA", "RAG", "HYBRID", "AGENT", "FILE", "VISION")
            },
            "vision_share": WORKLOAD_MIX.count("VISION") / len(WORKLOAD_MIX),
            "request_prefix_sha256": hashlib.sha256(request_prefix.encode()).hexdigest(),
            "workspace_id_sha256": hashlib.sha256(args.workspace_id.encode()).hexdigest(),
            "datasource_id_sha256": hashlib.sha256(args.datasource_id.encode()).hexdigest(),
            "semantic_model_id_sha256": hashlib.sha256(args.semantic_model_id.encode()).hexdigest(),
            "expected_data_value_sha256": hashlib.sha256(str(expected_data_value).encode()).hexdigest(),
            "load_data_case": {
                "id": load_data_case["id"],
                "manifest_sha256": core_manifest["manifest_sha256"],
                "expected_result_signature": expected_data_signature,
                "question_sha256": hashlib.sha256(str(load_data_case["question"]).encode()).hexdigest(),
            },
        },
        "bootstrap": {
            "users_created": bootstrap_receipt.users_created if bootstrap_receipt else 0,
            "grants_created": bootstrap_receipt.grants_created if bootstrap_receipt else 0,
            "distinct_derived_credentials": len(credentials),
            "secrets_persisted_in_evidence": 0,
        },
        "core_data100_manifest": {
            "path": str(args.core_data_manifest.resolve().relative_to(REPO_ROOT.resolve())).replace("\\", "/"),
            "sha256": core_manifest["manifest_sha256"],
            "base_manifest_sha256": core_manifest["base_manifest_sha256"],
            "case_count": len(core_cases),
        },
        "core_data100": core_data,
        "fixtures": {**fixture_hashes, "generated_outside_repository": True},
        "metrics": metrics,
        "cost_ledger": cost,
        "cleanup": cleanup,
        "failures": failures,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": evidence["status"],
        "evidence": str(args.output),
        "requests": (metrics or {}).get("requests", 0),
        "cleanup": cleanup,
        "failures": failures,
    }, ensure_ascii=False))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
