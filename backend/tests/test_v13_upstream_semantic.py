from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path
from statistics import quantiles

from app.core.config import Settings
from app.query.sql_guard import SqlGuard
from app.semantic_runtime import SemanticRuntime
from app.semantic_runtime._upstream.openchatbi import catalog_store
from app.semantic_runtime._upstream.wren import type_mapping, wren_dialect
from test_query_pipeline import semantic_context
from test_v21_semantic_runtime import CASES, benchmark_context


BACKEND_ROOT = Path(__file__).resolve().parents[1]
UPSTREAM_ROOT = BACKEND_ROOT / "app" / "semantic_runtime" / "_upstream"


def _canonical_lf_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def test_selected_sources_are_real_pinned_files_with_closed_imports():
    provenance = json.loads((UPSTREAM_ROOT / "provenance.json").read_text(encoding="utf-8"))
    selected = [
        (catalog_store, provenance["openchatbi"]["selected_files"][0]),
        (type_mapping, provenance["wrenai"]["selected_files"][0]),
        (wren_dialect, provenance["wrenai"]["selected_files"][1]),
    ]
    for module, record in selected:
        source_path = Path(inspect.getsourcefile(module) or "").resolve()
        assert UPSTREAM_ROOT in source_path.parents
        assert _canonical_lf_sha256(source_path) == record["raw_sha256"] == record["destination_sha256"]
    assert provenance["openchatbi"]["import_closure"] == [
        "python stdlib", "SQLAlchemy 2.0.43 (already pinned by ChatBI)",
    ]
    assert provenance["wrenai"]["import_closure"] == [
        "python stdlib", "sqlglot 30.17.0 (already pinned by ChatBI)",
    ]


def test_selected_wren_source_normalizes_postgresql_field_types():
    normalized = type_mapping.parse_types([
        {"column": "id", "raw_type": "int8"},
        {"column": "name", "raw_type": "character varying(255)"},
        {"column": "business_date", "raw_type": "date"},
        {"column": "amount", "raw_type": "numeric(12,2)"},
        {"column": "attributes", "raw_type": "jsonb"},
    ], dialect="postgres")

    assert [item["type"] for item in normalized] == [
        "BIGINT", "VARCHAR(255)", "DATE", "DECIMAL(12, 2)", "JSONB",
    ]


def test_selected_source_trace_recall_latency_mdl_dry_plan_and_ab_consistency():
    settings = Settings(_env_file=None, semantic_runtime_mode="wren")
    selected_runtime = SemanticRuntime(settings, upstream_reuse_mode="selected_source")
    clean_runtime = SemanticRuntime(settings, upstream_reuse_mode="clean_room")
    hits = 0
    total = 0
    catalog_latency_ms: list[float] = []

    for question, expected_metrics, expected_dimensions, _, _ in CASES:
        context = benchmark_context()
        selected_plan, selected_trace = selected_runtime.plan(question=question, context=context)
        clean_plan, clean_trace = clean_runtime.plan(question=question, context=context)

        assert selected_plan.generated_sql == clean_plan.generated_sql
        assert selected_plan.provider == "wrenai-upstream-runtime"
        assert clean_plan.provider == "wren-clean-room-runtime"
        assert SqlGuard().validate(
            selected_plan.generated_sql,
            dialect=context.dialect,
            policy=context.security_policy,
        ).allowed

        linking = selected_trace.schema_linking
        mdl = selected_trace.wren_mdl
        dry_plan = selected_trace.wren_dry_plan
        assert linking is not None and mdl is not None and dry_plan is not None
        assert linking.adapter == "openchatbi-selected-source"
        assert linking.upstream_source_commit == "c8786cb180081dbdd18d841efa33b70d77b633e9"
        assert linking.upstream_call_count > 0
        assert mdl.adapter == "wrenai-selected-source"
        assert mdl.upstream_source_commit == "7830cc746c11602d5899d8fdec1e28de4ce11a87"
        assert mdl.upstream_call_count == 1
        assert mdl.mapping_coverage == 1.0
        assert dry_plan.adapter == "wrenai-selected-source"
        assert dry_plan.status == "READY"
        assert dry_plan.upstream_call_count == 1
        assert dry_plan.semantic_sql and dry_plan.upstream_ast
        assert selected_trace.upstream_runtime_call_count == {
            "openchatbi": linking.upstream_call_count,
            "wrenai": 2,
        }
        assert clean_trace.upstream_runtime_call_count == {"openchatbi": 0, "wrenai": 0}
        assert clean_trace.schema_linking is not None
        assert clean_trace.schema_linking.adapter == "openchatbi-clean-room"
        assert clean_trace.wren_mdl is not None
        assert clean_trace.wren_mdl.adapter == "wren-clean-room"

        metric_top5 = [item.name for item in linking.candidates if item.object_type == "metric"][:5]
        dimension_top5 = [item.name for item in linking.candidates if item.object_type == "dimension"][:5]
        hits += sum(item in metric_top5 for item in expected_metrics)
        hits += sum(item in dimension_top5 for item in expected_dimensions)
        total += len(expected_metrics) + len(expected_dimensions)
        catalog_latency_ms.append(linking.elapsed_ms)

    assert hits / total >= 0.95
    p95 = quantiles(catalog_latency_ms, n=20, method="inclusive")[18]
    assert p95 < 100.0


def test_selected_source_cache_counts_only_actual_invocations_and_ab_cache_isolated():
    settings = Settings(_env_file=None, semantic_runtime_mode="wren")
    selected = SemanticRuntime(settings, upstream_reuse_mode="selected_source")
    clean = SemanticRuntime(settings, upstream_reuse_mode="clean_room")
    context = benchmark_context()

    _, first = selected.plan(question="租户 1 2025年按地区统计销售额", context=context)
    _, cached = selected.plan(question="租户 1 2025年按地区统计销售额", context=context)
    _, clean_trace = clean.plan(question="租户 1 2025年按地区统计销售额", context=context)

    assert first.schema_linking is not None and first.schema_linking.upstream_call_count > 0
    assert cached.schema_linking is not None and cached.schema_linking.cache_hit is True
    assert cached.schema_linking.upstream_call_count == 0
    assert cached.upstream_runtime_call_count["openchatbi"] == 0
    assert cached.upstream_runtime_call_count["wrenai"] == 2
    assert clean_trace.schema_linking is not None and clean_trace.schema_linking.cache_hit is False
    assert clean_trace.upstream_runtime_call_count == {"openchatbi": 0, "wrenai": 0}


def test_local_mode_remains_full_runtime_rollback():
    runtime = SemanticRuntime(
        Settings(_env_file=None, semantic_runtime_mode="local"),
        upstream_reuse_mode="selected_source",
    )
    _, trace = runtime.plan(question="2025年按地区统计收入", context=benchmark_context())
    assert trace.mode == "local"
    assert trace.openchatbi_called is False
    assert trace.wren_called is False
    assert trace.upstream_runtime_call_count == {}


def test_settings_switch_selects_clean_room_without_code_change():
    runtime = SemanticRuntime(Settings(
        _env_file=None,
        semantic_runtime_mode="wren",
        semantic_upstream_reuse_mode="clean_room",
    ))

    plan, trace = runtime.plan(question="2025年按地区统计收入", context=benchmark_context())

    assert runtime.capabilities()["upstream_reuse_mode"] == "clean_room"
    assert plan.provider == "wren-clean-room-runtime"
    assert trace.upstream_runtime_call_count == {"openchatbi": 0, "wrenai": 0}


def test_revenue_contribution_intent_allows_non_contiguous_business_wording():
    runtime = SemanticRuntime(Settings(_env_file=None, semantic_runtime_mode="wren"))

    plan, _ = runtime.plan(
        question="每个区域对总收入的贡献度是多少",
        context=semantic_context(),
    )

    assert plan.metrics == ["revenue_share"]
    assert plan.dimensions == ["region"]
