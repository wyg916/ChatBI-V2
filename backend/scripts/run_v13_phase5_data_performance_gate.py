from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import math
import os
import platform
import re
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session


BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
DEFAULT_MANIFEST = REPO_ROOT / "evaluation" / "golden" / "v13-phase5-10m-sql-performance-100.json"
DEFAULT_ROWS = 10_000_000
DEFAULT_USERS = 4
DEFAULT_DURATION_SECONDS = 2 * 60
MIN_GOLDEN_CASES = 100
_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
_SCHEMA_RE = re.compile(r"^phase5_perf_[a-z0-9_]{6,48}$")
_FORBIDDEN_SQL = re.compile(
    r"\b(insert|update|delete|drop|alter|create|grant|revoke|copy|call|do|vacuum|analyze)\b",
    re.IGNORECASE,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("ledger timestamps must include an explicit timezone")
    return parsed.astimezone(timezone.utc)


def percentile(values: Sequence[float], quantile: float) -> float:
    if not values:
        return 0.0
    if not 0.0 <= quantile <= 1.0:
        raise ValueError("quantile must be between zero and one")
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return round(ordered[0], 3)
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        result = ordered[lower]
    else:
        weight = position - lower
        result = ordered[lower] * (1.0 - weight) + ordered[upper] * weight
    return round(result, 3)


def distribution(values: Sequence[float]) -> dict[str, float]:
    if not values:
        return {"min": 0.0, "p50": 0.0, "p95": 0.0, "p99": 0.0, "max": 0.0}
    return {
        "min": round(min(values), 3),
        "p50": percentile(values, 0.50),
        "p95": percentile(values, 0.95),
        "p99": percentile(values, 0.99),
        "max": round(max(values), 3),
    }


def manifest_hash(manifest: dict[str, Any]) -> str:
    payload = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load_manifest(path: Path) -> dict[str, Any]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    cases = manifest.get("cases")
    if not isinstance(cases, list) or len(cases) < MIN_GOLDEN_CASES:
        raise ValueError(f"Phase5 10M SQL performance manifest requires at least {MIN_GOLDEN_CASES} cases")
    expected_hash = str(manifest.get("manifest_sha256") or "")
    actual_hash = manifest_hash(manifest)
    if expected_hash != actual_hash:
        raise ValueError("Phase5 10M SQL performance manifest hash mismatch")
    if int((manifest.get("dataset") or {}).get("row_count") or 0) != DEFAULT_ROWS:
        raise ValueError("Phase5 release dataset must declare exactly 10,000,000 fact rows")

    ids: set[str] = set()
    questions: set[str] = set()
    sql_texts: set[str] = set()
    categories: set[str] = set()
    for case in cases:
        case_id = str(case.get("id") or "").strip()
        question = " ".join(str(case.get("question") or "").split()).casefold()
        query = " ".join(str(case.get("sql_template") or "").split()).casefold()
        category = str(case.get("category") or "").strip()
        if not case_id or not question or not query or not category:
            raise ValueError("Every Phase5 case requires id, category, question and sql_template")
        if case_id in ids or question in questions or query in sql_texts:
            raise ValueError(f"Duplicate Phase5 10M SQL performance case: {case_id}")
        if "$schema$" not in query or not query.startswith("select "):
            raise ValueError(f"Case {case_id} is not a schema-bound SELECT")
        if ";" in query or _FORBIDDEN_SQL.search(query):
            raise ValueError(f"Case {case_id} contains non-read-only SQL")
        expectation = case.get("expectation") or {}
        if expectation.get("column") != "value" or not isinstance(expectation.get("value"), int):
            raise ValueError(f"Case {case_id} requires an exact integer value oracle")
        ids.add(case_id)
        questions.add(question)
        sql_texts.add(query)
        categories.add(category)
    if len(categories) < 4:
        raise ValueError("Phase5 mixed workload requires at least four request categories")
    return manifest


def validate_local_postgres_url(database_url: str) -> None:
    url = make_url(database_url)
    if url.get_backend_name() != "postgresql":
        raise ValueError("Phase5 performance data must use PostgreSQL")
    if (url.host or "").casefold() not in _LOCAL_HOSTS:
        raise ValueError("Phase5 performance data must use isolated local PostgreSQL")
    if not url.database:
        raise ValueError("Phase5 PostgreSQL database name is required")


def _schema_name(run_id: str | None = None) -> str:
    suffix = re.sub(r"[^a-z0-9_]", "", (run_id or "").casefold())
    if not suffix:
        suffix = hashlib.sha256(f"{time.time_ns()}:{os.getpid()}".encode()).hexdigest()[:12]
    name = f"phase5_perf_{suffix[:48]}"
    if not _SCHEMA_RE.fullmatch(name):
        raise ValueError("run id cannot form a safe Phase5 schema name")
    return name


def _quoted_schema(schema: str) -> str:
    if not _SCHEMA_RE.fullmatch(schema):
        raise ValueError("unsafe Phase5 schema name")
    return f'"{schema}"'


@dataclass(frozen=True)
class DatasetReceipt:
    schema: str
    row_count: int
    min_order_id: int
    max_order_id: int
    revenue_cents: int
    cost_cents: int


class PostgresPerformanceDataset:
    """Create and unconditionally remove one isolated local PostgreSQL schema."""

    def __init__(self, database_url: str, *, schema: str, rows: int) -> None:
        validate_local_postgres_url(database_url)
        if rows != DEFAULT_ROWS:
            raise ValueError("release Phase5 dataset must contain exactly 10,000,000 fact rows")
        self.database_url = database_url
        self.schema = schema
        self.rows = rows
        self.control_engine = create_engine(
            database_url,
            pool_pre_ping=True,
            pool_size=2,
            max_overflow=0,
            connect_args={"application_name": "chatbi-v13-phase5-control"},
        )

    def prepare(self) -> DatasetReceipt:
        schema = _quoted_schema(self.schema)
        with self.control_engine.begin() as connection:
            existing = connection.execute(
                text("SELECT to_regnamespace(:schema_name)"), {"schema_name": self.schema}
            ).scalar_one()
            if existing is not None:
                raise RuntimeError("isolated Phase5 schema already exists")
            connection.exec_driver_sql(f"CREATE SCHEMA {schema}")
            connection.exec_driver_sql(
                f"CREATE TABLE {schema}.dim_region AS "
                "SELECT g::smallint AS region_id, "
                "('区域-' || lpad(g::text, 2, '0'))::text AS region_name "
                "FROM generate_series(1, 20) AS s(g)"
            )
            connection.exec_driver_sql(
                f"CREATE TABLE {schema}.dim_product AS "
                "SELECT g::smallint AS product_id, "
                "('产品-' || lpad(g::text, 2, '0'))::text AS product_name "
                "FROM generate_series(1, 50) AS s(g)"
            )
            connection.execute(
                text(
                    f"CREATE TABLE {schema}.fact_orders AS "
                    "SELECT g::bigint AS order_id, "
                    "DATE '2024-01-01' + (((g - 1) % 730)::integer) AS order_day, "
                    "(((g - 1) % 20) + 1)::smallint AS region_id, "
                    "(((g * 7 - 1) % 50) + 1)::smallint AS product_id, "
                    "(((g * 13 - 1) % 1000) + 1)::integer AS customer_id, "
                    "(ARRAY['PAID','SHIPPED','REFUNDED','PENDING','CANCELLED'])[((g - 1) % 5)::integer + 1] AS status, "
                    "(10000 + ((g * 37) % 90000))::bigint AS revenue_cents, "
                    "(((10000 + ((g * 37) % 90000)) * (50 + (g % 31))) / 100)::bigint AS cost_cents "
                    "FROM generate_series(1, CAST(:rows AS bigint)) AS s(g)"
                ),
                {"rows": self.rows},
            )
            connection.exec_driver_sql(
                f"CREATE INDEX phase5_fact_region_idx ON {schema}.fact_orders (region_id)"
            )
            connection.exec_driver_sql(
                f"CREATE INDEX phase5_fact_product_idx ON {schema}.fact_orders (product_id)"
            )
            connection.exec_driver_sql(
                f"CREATE INDEX phase5_fact_day_idx ON {schema}.fact_orders (order_day)"
            )
            connection.exec_driver_sql(f"ANALYZE {schema}.fact_orders")

        with self.control_engine.connect() as connection:
            row = connection.execute(text(
                f"SELECT COUNT(*)::bigint AS row_count, MIN(order_id)::bigint AS min_order_id, "
                f"MAX(order_id)::bigint AS max_order_id, SUM(revenue_cents)::bigint AS revenue_cents, "
                f"SUM(cost_cents)::bigint AS cost_cents FROM {schema}.fact_orders"
            )).mappings().one()
        receipt = DatasetReceipt(schema=self.schema, **{key: int(value) for key, value in row.items()})
        if (receipt.row_count, receipt.min_order_id, receipt.max_order_id) != (self.rows, 1, self.rows):
            raise RuntimeError("Phase5 dataset exact row identity verification failed")
        return receipt

    def workload_engine(self, users: int, application_name: str) -> Engine:
        return create_engine(
            self.database_url,
            pool_pre_ping=True,
            pool_size=users,
            max_overflow=0,
            pool_timeout=30,
            connect_args={"application_name": application_name},
        )

    def connection_count(self, application_name: str) -> int:
        with self.control_engine.connect() as connection:
            return int(connection.execute(text(
                "SELECT COUNT(*) FROM pg_stat_activity WHERE application_name = :application_name"
            ), {"application_name": application_name}).scalar_one())

    def cleanup(self) -> dict[str, Any]:
        schema = _quoted_schema(self.schema)
        dropped = False
        verified_absent = False
        error_code: str | None = None
        try:
            with self.control_engine.begin() as connection:
                connection.exec_driver_sql(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
                dropped = True
            with self.control_engine.connect() as connection:
                verified_absent = connection.execute(
                    text("SELECT to_regnamespace(:schema_name) IS NULL"),
                    {"schema_name": self.schema},
                ).scalar_one() is True
        except Exception as exc:  # evidence must never contain connection details
            error_code = type(exc).__name__
        finally:
            self.control_engine.dispose()
        return {
            "drop_schema_executed": dropped,
            "verified_absent": verified_absent,
            "error_code": error_code,
        }


class SystemProbe:
    def __init__(self) -> None:
        self._cpu_state: tuple[int, int] | None = None

    def sample(self) -> tuple[float | None, float | None]:
        if os.name == "nt":
            return self._sample_windows()
        if platform.system() == "Linux":
            return self._sample_linux()
        return None, None

    @staticmethod
    def _filetime(value: Any) -> int:
        return (int(value.dwHighDateTime) << 32) | int(value.dwLowDateTime)

    def _sample_windows(self) -> tuple[float | None, float | None]:
        class FileTime(ctypes.Structure):
            _fields_ = [("dwLowDateTime", ctypes.c_uint32), ("dwHighDateTime", ctypes.c_uint32)]

        class MemoryStatus(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_uint32), ("dwMemoryLoad", ctypes.c_uint32),
                ("ullTotalPhys", ctypes.c_uint64), ("ullAvailPhys", ctypes.c_uint64),
                ("ullTotalPageFile", ctypes.c_uint64), ("ullAvailPageFile", ctypes.c_uint64),
                ("ullTotalVirtual", ctypes.c_uint64), ("ullAvailVirtual", ctypes.c_uint64),
                ("ullAvailExtendedVirtual", ctypes.c_uint64),
            ]

        idle, kernel, user = FileTime(), FileTime(), FileTime()
        cpu: float | None = None
        if ctypes.windll.kernel32.GetSystemTimes(
            ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)
        ):
            idle_value = self._filetime(idle)
            total_value = self._filetime(kernel) + self._filetime(user)
            if self._cpu_state is not None:
                idle_delta = idle_value - self._cpu_state[0]
                total_delta = total_value - self._cpu_state[1]
                if total_delta > 0:
                    cpu = max(0.0, min(100.0, (total_delta - idle_delta) * 100.0 / total_delta))
            self._cpu_state = (idle_value, total_value)
        memory = MemoryStatus()
        memory.dwLength = ctypes.sizeof(memory)
        ram = float(memory.dwMemoryLoad) if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory)) else None
        return cpu, ram

    def _sample_linux(self) -> tuple[float | None, float | None]:
        fields = [int(item) for item in Path("/proc/stat").read_text().splitlines()[0].split()[1:]]
        idle_value = fields[3] + (fields[4] if len(fields) > 4 else 0)
        total_value = sum(fields)
        cpu: float | None = None
        if self._cpu_state is not None:
            idle_delta = idle_value - self._cpu_state[0]
            total_delta = total_value - self._cpu_state[1]
            if total_delta > 0:
                cpu = max(0.0, min(100.0, (total_delta - idle_delta) * 100.0 / total_delta))
        self._cpu_state = (idle_value, total_value)
        memory: dict[str, int] = {}
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, value = line.split(":", 1)
            memory[key] = int(value.strip().split()[0])
        total = memory.get("MemTotal", 0)
        available = memory.get("MemAvailable", 0)
        ram = (total - available) * 100.0 / total if total else None
        return cpu, ram


@dataclass(frozen=True)
class SystemSample:
    cpu_percent: float | None
    ram_percent: float | None
    db_connections: int


@dataclass(frozen=True)
class RequestSample:
    user_index: int
    case_id: str
    category: str
    query_ms: float
    total_ms: float
    success: bool
    error_code: str | None


def summarize_requests(
    requests: Sequence[RequestSample],
    system_samples: Sequence[SystemSample],
    *,
    elapsed_seconds: float,
    expected_cases: int,
    users: int,
) -> dict[str, Any]:
    query = [item.query_ms for item in requests]
    total = [item.total_ms for item in requests]
    cpu = [item.cpu_percent for item in system_samples if item.cpu_percent is not None]
    ram = [item.ram_percent for item in system_samples if item.ram_percent is not None]
    connections = [float(item.db_connections) for item in system_samples]
    successes = sum(item.success for item in requests)
    categories = sorted({item.category for item in requests})
    cases = {item.case_id for item in requests}
    active_users = {item.user_index for item in requests}
    errors: dict[str, int] = {}
    for item in requests:
        if item.error_code:
            errors[item.error_code] = errors.get(item.error_code, 0) + 1
    return {
        "requests": len(requests),
        "successes": successes,
        "failures": len(requests) - successes,
        "success_rate": round(successes / len(requests), 6) if requests else 0.0,
        "actual_elapsed_seconds": round(elapsed_seconds, 3),
        "throughput_rps": round(len(requests) / max(elapsed_seconds, 0.001), 3),
        "active_users": len(active_users),
        "configured_users": users,
        "case_coverage": round(len(cases) / expected_cases, 6) if expected_cases else 0.0,
        "categories_executed": categories,
        "query_ms": distribution(query),
        "total_ms": distribution(total),
        "cpu_percent": distribution(cpu),
        "ram_percent": distribution(ram),
        "db_connections": distribution(connections),
        "system_sample_count": len(system_samples),
        "cpu_sample_count": len(cpu),
        "ram_sample_count": len(ram),
        "db_connection_sample_count": len(connections),
        "errors": dict(sorted(errors.items())),
    }


def scheduled_case_index(user_index: int, sequence: int, users: int, case_count: int) -> int:
    if users <= 0 or case_count <= 0 or user_index < 0 or sequence < 0:
        raise ValueError("schedule inputs must be non-negative with positive users and case count")
    return (user_index + sequence * users) % case_count


def _execute_case(
    engine: Engine,
    case: dict[str, Any],
    *,
    schema: str,
    user_index: int,
    timeout_ms: int,
) -> RequestSample:
    total_started = time.perf_counter()
    query_ms = 0.0
    success = False
    error_code: str | None = None
    try:
        sql = str(case["sql_template"]).replace("$SCHEMA$", _quoted_schema(schema))
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                connection.exec_driver_sql("SET TRANSACTION READ ONLY")
                connection.exec_driver_sql(f"SET LOCAL statement_timeout = {int(timeout_ms)}")
                query_started = time.perf_counter()
                row = connection.execute(text(sql)).mappings().one()
                query_ms = (time.perf_counter() - query_started) * 1000.0
                expectation = case["expectation"]
                success = int(row[expectation["column"]]) == int(expectation["value"])
                if not success:
                    error_code = "RESULT_MISMATCH"
            finally:
                transaction.rollback()
    except Exception as exc:
        error_code = type(exc).__name__
    return RequestSample(
        user_index=user_index,
        case_id=str(case["id"]),
        category=str(case["category"]),
        query_ms=round(query_ms, 3),
        total_ms=round((time.perf_counter() - total_started) * 1000.0, 3),
        success=success,
        error_code=error_code,
    )


def run_mixed_load(
    engine: Engine,
    cases: Sequence[dict[str, Any]],
    *,
    schema: str,
    users: int,
    duration_seconds: int,
    timeout_ms: int,
    sample_system: Callable[[], SystemSample],
    sample_interval_seconds: float = 1.0,
) -> tuple[list[RequestSample], list[SystemSample], float]:
    requests: list[RequestSample] = []
    system_samples: list[SystemSample] = []
    lock = threading.Lock()
    stop = threading.Event()
    barrier = threading.Barrier(users + 1)
    deadline = 0.0

    def worker(user_index: int) -> None:
        nonlocal deadline
        barrier.wait()
        sequence = 0
        while time.perf_counter() < deadline:
            index = scheduled_case_index(user_index, sequence, users, len(cases))
            sample = _execute_case(
                engine, cases[index], schema=schema, user_index=user_index, timeout_ms=timeout_ms
            )
            with lock:
                requests.append(sample)
            sequence += 1

    def sampler() -> None:
        while not stop.is_set():
            try:
                sample = sample_system()
            except Exception:
                sample = SystemSample(None, None, -1)
            with lock:
                system_samples.append(sample)
            stop.wait(sample_interval_seconds)

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=users, thread_name_prefix="phase5-user") as executor:
        futures = [executor.submit(worker, index) for index in range(users)]
        sample_thread = threading.Thread(target=sampler, name="phase5-telemetry", daemon=True)
        sample_thread.start()
        deadline = time.perf_counter() + duration_seconds
        barrier.wait()
        for future in futures:
            future.result()
        stop.set()
        sample_thread.join(timeout=max(2.0, sample_interval_seconds * 2))
    return requests, system_samples, time.perf_counter() - started


def compute_token_cost(
    pricing: dict[str, float], *, input_tokens: int, cached_input_tokens: int, output_tokens: int
) -> float:
    input_count = max(0, int(input_tokens))
    cached_count = min(input_count, max(0, int(cached_input_tokens)))
    uncached_count = input_count - cached_count
    cost = (
        cached_count * float(pricing["cached_input"])
        + uncached_count * float(pricing["uncached_input"])
        + max(0, int(output_tokens)) * float(pricing["output"])
    ) / 1_000_000
    return round(cost, 12)


def aggregate_cost_ledger(
    entries: Sequence[dict[str, Any]],
    *,
    coverage: dict[str, Any],
    kimi_pricing: dict[str, float],
) -> dict[str, Any]:
    actual_cost = sum(float(item.get("cost_cny") or 0.0) for item in entries)
    all_premium = sum(compute_token_cost(
        kimi_pricing,
        input_tokens=int(item.get("input_tokens") or 0),
        cached_input_tokens=int(item.get("cached_input_tokens") or 0),
        output_tokens=int(item.get("output_tokens") or 0),
    ) for item in entries)
    kimi_count = sum(str(item.get("provider") or "").casefold() == "kimi" for item in entries)
    premium_share = kimi_count / len(entries) if entries else 0.0
    savings = 1.0 - actual_cost / all_premium if all_premium > 0 else 0.0
    providers: dict[str, int] = {}
    for item in entries:
        provider = str(item.get("provider") or "UNKNOWN")
        providers[provider] = providers.get(provider, 0) + 1
    return {
        "coverage": coverage,
        "invocations": len(entries),
        "token_bearing_invocations": sum(
            int(item.get("input_tokens") or 0) + int(item.get("output_tokens") or 0) > 0
            for item in entries
        ),
        "providers": dict(sorted(providers.items())),
        "kimi_invocations": kimi_count,
        "kimi_premium_share": round(premium_share, 6),
        "actual_cost_cny": round(actual_cost, 8),
        "all_premium_cost_cny": round(all_premium, 8),
        "saving_vs_all_premium": round(savings, 6),
    }


def load_real_cost_ledger(
    database_url: str,
    *,
    workspace_id: str,
    from_at: datetime,
    to_at: datetime,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    validate_local_postgres_url(database_url)
    sys.path.insert(0, str(BACKEND_ROOT)) if str(BACKEND_ROOT) not in sys.path else None
    from app.services.governance import cost_ledger_entries

    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with Session(engine) as session:
            return cost_ledger_entries(
                session,
                workspace_id=workspace_id,
                from_at=from_at,
                to_at=to_at,
            )
    finally:
        engine.dispose()


def evaluate_gate(
    *,
    manifest: dict[str, Any],
    dataset: DatasetReceipt | None,
    config: dict[str, Any],
    performance: dict[str, Any] | None,
    cleanup: dict[str, Any],
    runtime_error: str | None,
) -> list[str]:
    failures: list[str] = []
    thresholds = manifest["release_gate"]
    if runtime_error:
        failures.append(f"runtime_error:{runtime_error}")
    if dataset is None or dataset.row_count != DEFAULT_ROWS:
        failures.append("dataset_rows_not_exactly_10000000")
    elif (
        dataset.revenue_cents != int(manifest["dataset"]["expected_revenue_cents"])
        or dataset.cost_cents != int(manifest["dataset"]["expected_cost_cents"])
    ):
        failures.append("dataset_deterministic_fingerprint_mismatch")
    if int(config["users"]) < int(thresholds["min_users"]):
        failures.append("concurrency_below_10m_measurement_gate")
    if int(config["duration_seconds"]) < int(thresholds["min_duration_seconds"]):
        failures.append("duration_below_10m_measurement_gate")
    if not cleanup.get("drop_schema_executed") or not cleanup.get("verified_absent"):
        failures.append("isolated_schema_cleanup_not_verified")

    if performance is None:
        failures.append("performance_metrics_missing")
    else:
        checks = [
            (performance.get("actual_elapsed_seconds", 0.0) >= float(config["duration_seconds"]), "actual_duration_below_configured_measurement"),
            (performance["active_users"] == config["users"], "not_all_users_active"),
            (performance["case_coverage"] >= 1.0, "sql_performance_case_coverage_below_100_percent"),
            (performance["success_rate"] >= float(thresholds["min_success_rate"]), "request_success_rate_below_gate"),
            (performance["system_sample_count"] >= math.ceil(float(config["duration_seconds"]) / 2), "system_telemetry_coverage_below_half_duration"),
            (performance.get("cpu_sample_count", 0) >= math.ceil(float(config["duration_seconds"]) / 2), "cpu_telemetry_coverage_below_half_duration"),
            (performance.get("ram_sample_count", 0) >= math.ceil(float(config["duration_seconds"]) / 2), "ram_telemetry_coverage_below_half_duration"),
            (performance.get("db_connection_sample_count", 0) >= math.ceil(float(config["duration_seconds"]) / 2), "db_connection_telemetry_coverage_below_half_duration"),
        ]
        failures.extend(code for passed, code in checks if not passed)
    return failures


def _git_sha() -> str | None:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True, check=False
    )
    return completed.stdout.strip() if completed.returncode == 0 else None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ChatBI V1.3 Phase5 isolated 10M datasource SQL performance gate")
    parser.add_argument("--database-url", default=os.getenv("CHATBI_PHASE5_DATABASE_URL") or os.getenv("CHATBI_DATABASE_URL"))
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--run-id")
    parser.add_argument("--users", type=int, default=DEFAULT_USERS)
    parser.add_argument("--duration-seconds", type=int, default=DEFAULT_DURATION_SECONDS)
    parser.add_argument("--query-timeout-ms", type=int, default=30_000)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.database_url:
        raise SystemExit("--database-url or CHATBI_PHASE5_DATABASE_URL is required")
    if args.users <= 0 or args.duration_seconds <= 0 or args.query_timeout_ms <= 0:
        raise SystemExit("users, duration and query timeout must be positive")
    validate_local_postgres_url(args.database_url)
    manifest = load_manifest(args.manifest)
    schema = _schema_name(args.run_id)
    started_at = _utc_now()

    dataset_runner = PostgresPerformanceDataset(
        args.database_url, schema=schema, rows=int(manifest["dataset"]["row_count"])
    )
    dataset: DatasetReceipt | None = None
    performance: dict[str, Any] | None = None
    runtime_error: str | None = None
    cleanup: dict[str, Any] = {"drop_schema_executed": False, "verified_absent": False, "error_code": None}
    workload_engine: Engine | None = None
    application_name = f"chatbi-v13-phase5-{schema[-12:]}"

    try:
        dataset = dataset_runner.prepare()
        workload_engine = dataset_runner.workload_engine(args.users, application_name)
        probe = SystemProbe()

        def system_sample() -> SystemSample:
            cpu, ram = probe.sample()
            return SystemSample(cpu, ram, dataset_runner.connection_count(application_name))

        requests, telemetry, elapsed = run_mixed_load(
            workload_engine,
            manifest["cases"],
            schema=schema,
            users=args.users,
            duration_seconds=args.duration_seconds,
            timeout_ms=args.query_timeout_ms,
            sample_system=system_sample,
        )
        performance = summarize_requests(
            requests,
            telemetry,
            elapsed_seconds=elapsed,
            expected_cases=len(manifest["cases"]),
            users=args.users,
        )
    except Exception as exc:
        runtime_error = type(exc).__name__
    finally:
        if workload_engine is not None:
            workload_engine.dispose()
        cleanup = dataset_runner.cleanup()

    config = {
        "fact_rows": int(manifest["dataset"]["row_count"]),
        "users": args.users,
        "duration_seconds": args.duration_seconds,
        "query_timeout_ms": args.query_timeout_ms,
        "workload_scope": "ISOLATED_LOCAL_POSTGRESQL_10M_DATASOURCE_SQL_PERFORMANCE",
        "classification": "10M_DATASOURCE_SQL_PERFORMANCE",
        "core_data_golden_status": "NOT_PROVEN_NOT_EXECUTED_THROUGH_BACKEND",
        "production_default_duration_seconds": DEFAULT_DURATION_SECONDS,
    }
    failures = evaluate_gate(
        manifest=manifest,
        dataset=dataset,
        config=config,
        performance=performance,
        cleanup=cleanup,
        runtime_error=runtime_error,
    )
    evidence = {
        "schema_version": "chatbi.v13.phase5.10m-sql-performance.v1",
        "suite": manifest["suite"],
        "status": "PASS" if not failures else "FAIL",
        "tested_sha": _git_sha(),
        "started_at": _iso(started_at),
        "completed_at": _iso(_utc_now()),
        "manifest": {
            "path": str(args.manifest.resolve().relative_to(REPO_ROOT.resolve())).replace("\\", "/"),
            "sha256": manifest["manifest_sha256"],
            "case_count": len(manifest["cases"]),
        },
        "config": config,
        "dataset": asdict(dataset) if dataset is not None else None,
        "performance": performance,
        "cost_gate_scope": "SEPARATE_AUTHENTICATED_API_LOAD_MODEL_INVOCATION_LEDGER",
        "cleanup": cleanup,
        "failures": failures,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": evidence["status"],
        "evidence": str(args.output),
        "requests": (performance or {}).get("requests", 0),
        "failures": failures,
        "cleanup_verified": cleanup.get("verified_absent", False),
    }, ensure_ascii=False))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
