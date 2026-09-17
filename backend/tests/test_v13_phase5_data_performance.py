from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.run_v13_phase5_data_performance_gate import (
    DEFAULT_DURATION_SECONDS,
    DEFAULT_MANIFEST,
    DEFAULT_ROWS,
    DEFAULT_USERS,
    DatasetReceipt,
    PostgresPerformanceDataset,
    RequestSample,
    SystemSample,
    _quoted_schema,
    _schema_name,
    aggregate_cost_ledger,
    build_parser,
    compute_token_cost,
    distribution,
    evaluate_gate,
    load_manifest,
    manifest_hash,
    percentile,
    scheduled_case_index,
    summarize_requests,
    validate_local_postgres_url,
)


def test_phase5_manifest_is_frozen_unique_10m_datasource_sql_performance_100() -> None:
    manifest = load_manifest(DEFAULT_MANIFEST)
    cases = manifest["cases"]

    assert manifest["suite"] == "CHATBI_V13_PHASE5_10M_DATASOURCE_SQL_PERFORMANCE_100"
    assert manifest["classification"] == "10M_DATASOURCE_SQL_PERFORMANCE"
    assert manifest["core_data_golden_status"].startswith("NOT_PROVEN")
    assert manifest["frozen"] is True
    assert manifest["dataset"]["engine"] == "local_postgresql"
    assert manifest["dataset"]["row_count"] == DEFAULT_ROWS == 10_000_000
    assert len(cases) == 100
    assert len({case["id"] for case in cases}) == 100
    assert len({" ".join(case["question"].split()).casefold() for case in cases}) == 100
    assert len({" ".join(case["sql_template"].split()).casefold() for case in cases}) == 100
    assert len({case["category"] for case in cases}) == 5
    assert manifest["manifest_sha256"] == manifest_hash(manifest)
    assert all(case["expectation"]["column"] == "value" for case in cases)
    assert all(isinstance(case["expectation"]["value"], int) for case in cases)


def test_release_defaults_separate_10m_measurement_from_20_user_api_load(tmp_path: Path) -> None:
    args = build_parser().parse_args([
        "--output", str(tmp_path / "evidence.json"),
    ])

    assert args.users == DEFAULT_USERS == 4
    assert args.duration_seconds == DEFAULT_DURATION_SECONDS == 120
    assert DEFAULT_ROWS == 10_000_000


@pytest.mark.parametrize(
    "database_url",
    [
        "postgresql+psycopg://user@db.example.invalid/chatbi",
        "mysql+pymysql://user@127.0.0.1/chatbi",
        "sqlite+pysqlite:///:memory:",
    ],
)
def test_release_runner_rejects_non_local_or_non_postgres_database(database_url: str) -> None:
    with pytest.raises(ValueError):
        validate_local_postgres_url(database_url)


@pytest.mark.parametrize(
    "database_url",
    [
        "postgresql+psycopg://user@127.0.0.1/chatbi",
        "postgresql+psycopg://user@localhost:5432/chatbi",
        "postgresql+psycopg://user@[::1]:5432/chatbi",
    ],
)
def test_release_runner_accepts_only_loopback_postgresql(database_url: str) -> None:
    validate_local_postgres_url(database_url)


def test_percentiles_are_deterministic_and_report_p50_p95_p99() -> None:
    values = [float(value) for value in range(1, 101)]

    assert percentile(values, 0.50) == 50.5
    assert percentile(values, 0.95) == 95.05
    assert percentile(values, 0.99) == 99.01
    assert distribution(values) == {
        "min": 1.0,
        "p50": 50.5,
        "p95": 95.05,
        "p99": 99.01,
        "max": 100.0,
    }


def test_mixed_schedule_covers_all_100_cases_with_four_users_in_25_requests_each() -> None:
    scheduled = {
        scheduled_case_index(user, sequence, DEFAULT_USERS, 100)
        for user in range(DEFAULT_USERS)
        for sequence in range(25)
    }

    assert scheduled == set(range(100))


def test_metrics_include_query_total_cpu_ram_and_db_connection_percentiles() -> None:
    requests = [
        RequestSample(0, "A", "metric", 10.0, 15.0, True, None),
        RequestSample(1, "B", "join", 20.0, 25.0, True, None),
        RequestSample(1, "C", "time", 30.0, 35.0, False, "RESULT_MISMATCH"),
    ]
    telemetry = [
        SystemSample(None, 50.0, 1),
        SystemSample(40.0, 60.0, 2),
        SystemSample(60.0, 70.0, 3),
    ]

    metrics = summarize_requests(
        requests,
        telemetry,
        elapsed_seconds=2.0,
        expected_cases=3,
        users=2,
    )

    assert metrics["query_ms"]["p50"] == 20.0
    assert metrics["total_ms"]["p99"] == 34.8
    assert metrics["cpu_percent"]["p95"] == 59.0
    assert metrics["ram_percent"]["p99"] == 69.8
    assert metrics["db_connections"]["max"] == 3.0
    assert metrics["cpu_sample_count"] == 2
    assert metrics["ram_sample_count"] == 3
    assert metrics["db_connection_sample_count"] == 3
    assert metrics["errors"] == {"RESULT_MISMATCH": 1}


def test_real_ledger_aggregation_enforces_kimi_share_and_all_premium_counterfactual() -> None:
    mimo = {"cached_input": 0.02, "uncached_input": 1.0, "output": 2.0}
    kimi = {"cached_input": 1.1, "uncached_input": 6.5, "output": 27.0}
    entries = []
    for index in range(10):
        provider = "kimi" if index == 0 else "mimo"
        provider_price = kimi if provider == "kimi" else mimo
        entries.append({
            "provider": provider,
            "status": "SUCCEEDED",
            "input_tokens": 1_000,
            "cached_input_tokens": 200,
            "output_tokens": 200,
            "cost_cny": compute_token_cost(
                provider_price,
                input_tokens=1_000,
                cached_input_tokens=200,
                output_tokens=200,
            ),
        })

    result = aggregate_cost_ledger(
        entries,
        coverage={"source": "MODEL_INVOCATION_LEDGER", "complete": True, "warnings": []},
        kimi_pricing=kimi,
    )

    assert result["invocations"] == 10
    assert result["token_bearing_invocations"] == 10
    assert result["kimi_invocations"] == 1
    assert result["kimi_premium_share"] == 0.10
    assert result["all_premium_cost_cny"] > result["actual_cost_cny"]
    assert result["saving_vs_all_premium"] >= 0.60


def _passing_performance() -> dict:
    return {
        "requests": 100,
        "successes": 100,
        "failures": 0,
        "success_rate": 1.0,
        "actual_elapsed_seconds": 120.0,
        "throughput_rps": 10.0,
        "active_users": 4,
        "configured_users": 4,
        "case_coverage": 1.0,
        "categories_executed": ["a", "b", "c", "d"],
        "query_ms": {"min": 1.0, "p50": 100.0, "p95": 1000.0, "p99": 2000.0, "max": 2500.0},
        "total_ms": {"min": 2.0, "p50": 120.0, "p95": 1200.0, "p99": 2200.0, "max": 2600.0},
        "cpu_percent": {"min": 20.0, "p50": 40.0, "p95": 60.0, "p99": 70.0, "max": 75.0},
        "ram_percent": {"min": 30.0, "p50": 50.0, "p95": 65.0, "p99": 75.0, "max": 80.0},
        "db_connections": {"min": 1.0, "p50": 15.0, "p95": 20.0, "p99": 20.0, "max": 20.0},
        "system_sample_count": 120,
        "cpu_sample_count": 119,
        "ram_sample_count": 120,
        "db_connection_sample_count": 120,
        "errors": {},
    }


def test_10m_sql_performance_gate_requires_exact_dataset_measurement_and_cleanup() -> None:
    manifest = load_manifest(DEFAULT_MANIFEST)
    dataset = DatasetReceipt(
        schema="phase5_perf_testgate",
        row_count=DEFAULT_ROWS,
        min_order_id=1,
        max_order_id=DEFAULT_ROWS,
        revenue_cents=manifest["dataset"]["expected_revenue_cents"],
        cost_cents=manifest["dataset"]["expected_cost_cents"],
    )
    config = {
        "fact_rows": DEFAULT_ROWS,
        "users": DEFAULT_USERS,
        "duration_seconds": DEFAULT_DURATION_SECONDS,
        "query_timeout_ms": 30_000,
    }

    assert evaluate_gate(
        manifest=manifest,
        dataset=dataset,
        config=config,
        performance=_passing_performance(),
        cleanup={"drop_schema_executed": True, "verified_absent": True, "error_code": None},
        runtime_error=None,
    ) == []

    failures = evaluate_gate(
        manifest=manifest,
        dataset=dataset,
        config={**config, "users": 3, "duration_seconds": 119},
        performance={**_passing_performance(), "active_users": 3, "actual_elapsed_seconds": 118.0},
        cleanup={"drop_schema_executed": True, "verified_absent": False, "error_code": None},
        runtime_error=None,
    )
    assert {
        "concurrency_below_10m_measurement_gate",
        "duration_below_10m_measurement_gate",
        "isolated_schema_cleanup_not_verified",
        "actual_duration_below_configured_measurement",
    }.issubset(failures)


def test_cleanup_uses_exact_validated_schema_and_verifies_absence() -> None:
    statements: list[str] = []

    class Result:
        def scalar_one(self) -> bool:
            return True

    class Connection:
        def exec_driver_sql(self, statement: str) -> None:
            statements.append(statement)

        def execute(self, _statement, parameters):
            assert parameters == {"schema_name": "phase5_perf_cleanup1"}
            return Result()

    class Context:
        def __enter__(self) -> Connection:
            return Connection()

        def __exit__(self, *_args) -> None:
            return None

    class Engine:
        disposed = False

        def begin(self) -> Context:
            return Context()

        def connect(self) -> Context:
            return Context()

        def dispose(self) -> None:
            self.disposed = True

    dataset = object.__new__(PostgresPerformanceDataset)
    dataset.schema = "phase5_perf_cleanup1"
    dataset.control_engine = Engine()

    receipt = dataset.cleanup()

    assert statements == ['DROP SCHEMA IF EXISTS "phase5_perf_cleanup1" CASCADE']
    assert receipt == {"drop_schema_executed": True, "verified_absent": True, "error_code": None}
    assert dataset.control_engine.disposed is True
    assert _quoted_schema(_schema_name("cleanup1")) == '"phase5_perf_cleanup1"'


def test_manifest_file_contains_no_duplicate_serialized_cases() -> None:
    payload = json.loads(DEFAULT_MANIFEST.read_text(encoding="utf-8"))
    serialized = [json.dumps(case, ensure_ascii=False, sort_keys=True) for case in payload["cases"]]
    assert len(serialized) == len(set(serialized)) == 100
