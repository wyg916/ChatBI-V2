from __future__ import annotations

import argparse
import asyncio
import csv
import json
import math
import os
import secrets
import statistics
import re
import subprocess
import sys
import time
from collections import Counter, defaultdict
from contextlib import AsyncExitStack
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import httpx


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEMO_DB = PROJECT_ROOT / "scripts" / "demo_db"
BACKEND = PROJECT_ROOT / "backend"
sys.path.insert(0, str(DEMO_DB))
sys.path.insert(0, str(BACKEND))

from _common import atomic_json, connect, connection_kwargs, load_env, validate_schema  # noqa: E402


def _configure_backend_environment(env: dict[str, str]) -> None:
    """Make host-side SQLAlchemy use the same metadata credentials as the selected env file."""
    from sqlalchemy.engine import URL

    for key, value in env.items():
        if key.startswith("CHATBI_") and value:
            os.environ.setdefault(key, value)
    if not os.environ.get("CHATBI_DATABASE_URL"):
        values = connection_kwargs(env)
        os.environ["CHATBI_DATABASE_URL"] = URL.create(
            "postgresql+psycopg", username=values["user"], password=values["password"],
            host=values["host"], port=values["port"], database=values["dbname"],
        ).render_as_string(hide_password=False)


def percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(quantile * len(ordered)) - 1))
    return round(ordered[index], 3)


def run_database_benchmarks(env: dict[str, str], schema: str, repeats: int) -> dict:
    queries = {
        "simple": f'''SELECT net_sales FROM "{schema}".agg_monthly_sales
            WHERE tenant_id=1 AND month_start=date '2025-07-01' ''',
        "standard": f'''SELECT region_id, round(sum(net_amount-refund_amount)::numeric,2) AS value
            FROM "{schema}".fact_sales
            WHERE tenant_id=1 AND order_date>=date '2025-01-01' AND order_date<date '2026-01-01'
            AND order_status <> 'TEST' GROUP BY region_id ORDER BY value DESC LIMIT 10''',
        "complex": f'''SELECT p.category, r.region_group, round(sum(f.net_amount-f.refund_amount)::numeric,2) AS value
            FROM "{schema}".fact_sales f
            JOIN "{schema}".dim_product p ON p.product_id=f.product_id
            JOIN "{schema}".dim_region r ON r.region_id=f.region_id
            WHERE f.tenant_id=1 AND f.order_date>=date '2025-01-01' AND f.order_date<date '2026-01-01'
            AND f.order_status IN ('VALID','PARTIAL_REFUND','REFUNDED')
            GROUP BY p.category,r.region_group ORDER BY value DESC''',
        "advanced": f'''SELECT aging_bucket, sum(invoice_count) AS invoice_count,
                   round(sum(outstanding_amount)::numeric,2) AS outstanding
            FROM "{schema}".agg_receivable_aging
            WHERE tenant_id=1 AND month_start>=date '2025-01-01' AND month_start<date '2026-01-01'
            GROUP BY aging_bucket ORDER BY outstanding DESC''',
    }
    samples: dict[str, list[float]] = defaultdict(list)
    with connect(env) as conn:
        conn.execute("SET statement_timeout='60s'")
        for name, query in queries.items():
            conn.execute(query).fetchall()
            for _ in range(repeats):
                started = time.perf_counter()
                conn.execute(query).fetchall()
                samples[name].append((time.perf_counter() - started) * 1000)
    return {
        name: {
            "runs": len(values), "p50_ms": percentile(values, 0.50),
            "p95_ms": percentile(values, 0.95), "p99_ms": percentile(values, 0.99),
            "max_ms": round(max(values), 3),
        }
        for name, values in samples.items()
    }


ROUTE_QUESTIONS = {
    "DATA_QUERY": "今年华东区销售额是多少？",
    "KNOWLEDGE_QUERY": "有效订单的业务定义是什么？",
    "HYBRID_ANALYSIS": "为什么本月销售额发生变化？请结合业务规则说明。",
    "COMPLEX_ANALYSIS": "请按区域和产品分解今年销售额并给出有证据的建议。",
    "FILE_QUERY": "汇总附件中每个区域的金额并生成图表。",
}
MIXED_ROUTES = (
    "DATA_QUERY", "KNOWLEDGE_QUERY", "HYBRID_ANALYSIS", "COMPLEX_ANALYSIS",
    "FILE_QUERY", "SQL_WORKSPACE", "FEEDBACK", "EVALUATION",
)


@dataclass
class Actor:
    label: str
    email: str
    password: str
    datasource_id: str
    semantic_model_id: str
    workspace_id: str
    client: httpx.AsyncClient | None = None


def _clone_release_load_tenant() -> Actor:
    """Create a temporary second Workspace over the same read-only source."""
    from sqlalchemy import select

    from app.core.auth import hash_password
    from app.db.session import SessionLocal
    from app.models import (
        AppUser, BusinessTerm, DataSource, DataSourceColumn, DataSourceRelation,
        DataSourceSchema, DataSourceTable, Dimension, Metric, ResourceGrant,
        SemanticEntity, SemanticModel, SemanticRelation, Workspace,
    )
    from app.services.runtime_seed import seed_v1_runtime

    password = secrets.token_urlsafe(24)
    email = "v21-final-load@chatbi.local"
    with SessionLocal() as db:
        workspace = db.scalar(select(Workspace).where(Workspace.name == "V2.1 Final Load Workspace"))
        if workspace is None:
            workspace = Workspace(name="V2.1 Final Load Workspace")
            db.add(workspace); db.flush()
        source = db.scalar(select(DataSource).where(DataSource.type == "postgresql").order_by(DataSource.created_at))
        if source is None:
            raise RuntimeError("No PostgreSQL datasource is available for the release load tenant")
        datasource = db.scalar(select(DataSource).where(
            DataSource.workspace_id == workspace.id, DataSource.name == "V2.1 Load PostgreSQL",
        ))
        if datasource is None:
            datasource = DataSource(
                workspace_id=workspace.id, name="V2.1 Load PostgreSQL", type=source.type,
                host=source.host, port=source.port, database=source.database,
                username=source.username, password_encrypted=source.password_encrypted,
                ssl=source.ssl, schema=source.schema, status=source.status,
                last_sync_at=source.last_sync_at,
            )
            db.add(datasource); db.flush()
            schema_map: dict[str, DataSourceSchema] = {}
            table_map: dict[str, DataSourceTable] = {}
            source_schemas = list(db.scalars(select(DataSourceSchema).where(DataSourceSchema.datasource_id == source.id)))
            for old in source_schemas:
                new = DataSourceSchema(datasource_id=datasource.id, name=old.name, qualified_name=old.qualified_name)
                db.add(new); db.flush(); schema_map[old.id] = new
            source_tables = list(db.scalars(select(DataSourceTable).where(
                DataSourceTable.schema_id.in_(list(schema_map))
            ))) if schema_map else []
            for old in source_tables:
                new = DataSourceTable(
                    schema_id=schema_map[old.schema_id].id, name=old.name,
                    qualified_name=old.qualified_name, comment=old.comment,
                )
                db.add(new); db.flush(); table_map[old.id] = new
            source_columns = list(db.scalars(select(DataSourceColumn).where(
                DataSourceColumn.table_id.in_(list(table_map))
            ))) if table_map else []
            for old in source_columns:
                db.add(DataSourceColumn(
                    table_id=table_map[old.table_id].id, name=old.name,
                    qualified_name=old.qualified_name, data_type=old.data_type,
                    nullable=old.nullable, primary_key=old.primary_key,
                    foreign_key=old.foreign_key, default=old.default,
                    comment=old.comment, sample_values=old.sample_values,
                ))
            for old in db.scalars(select(DataSourceRelation).where(DataSourceRelation.datasource_id == source.id)):
                db.add(DataSourceRelation(
                    datasource_id=datasource.id, source_schema=old.source_schema,
                    source_table=old.source_table, source_columns=old.source_columns,
                    target_schema=old.target_schema, target_table=old.target_table,
                    target_columns=old.target_columns,
                ))
        source_model = db.scalar(select(SemanticModel).where(
            SemanticModel.datasource_id == source.id, SemanticModel.status == "PUBLISHED",
        ).order_by(SemanticModel.created_at))
        if source_model is None:
            raise RuntimeError("No published semantic model is available for the release load tenant")
        model = db.scalar(select(SemanticModel).where(
            SemanticModel.workspace_id == workspace.id, SemanticModel.name == "V2.1 Load Semantic Model",
        ))
        if model is None:
            model = SemanticModel(
                workspace_id=workspace.id, datasource_id=datasource.id,
                name="V2.1 Load Semantic Model", description="Temporary final load isolation model",
                status="PUBLISHED", version=source_model.version,
            )
            db.add(model); db.flush()
            db.add_all([SemanticEntity(
                semantic_model_id=model.id, name=item.name, source_table=item.source_table,
                primary_key=item.primary_key, time_dimension=item.time_dimension,
            ) for item in db.scalars(select(SemanticEntity).where(SemanticEntity.semantic_model_id == source_model.id))])
            db.add_all([Metric(
                semantic_model_id=model.id, name=item.name, label=item.label,
                description=item.description, expression=item.expression,
                aggregation=item.aggregation, filters=item.filters,
            ) for item in db.scalars(select(Metric).where(Metric.semantic_model_id == source_model.id))])
            db.add_all([Dimension(
                semantic_model_id=model.id, name=item.name, label=item.label,
                source_column=item.source_column, type=item.type,
            ) for item in db.scalars(select(Dimension).where(Dimension.semantic_model_id == source_model.id))])
            db.add_all([SemanticRelation(
                semantic_model_id=model.id, left_entity=item.left_entity,
                right_entity=item.right_entity, join_type=item.join_type,
                join_keys=item.join_keys, cardinality=item.cardinality,
            ) for item in db.scalars(select(SemanticRelation).where(SemanticRelation.semantic_model_id == source_model.id))])
            db.add_all([BusinessTerm(
                semantic_model_id=model.id, term=item.term, synonyms=item.synonyms,
                definition=item.definition, mapped_object=item.mapped_object,
            ) for item in db.scalars(select(BusinessTerm).where(BusinessTerm.semantic_model_id == source_model.id))])
        user = db.scalar(select(AppUser).where(AppUser.email == email))
        if user is None:
            user = AppUser(
                workspace_id=workspace.id, email=email, display_name="V2.1 Final Load",
                role="ADMIN", status="ACTIVE",
            )
            db.add(user); db.flush()
        user.password_hash = hash_password(password)
        user.workspace_id = workspace.id
        for resource_type, resource_id in (("DATASOURCE", datasource.id), ("SEMANTIC_MODEL", model.id)):
            grant = db.scalar(select(ResourceGrant).where(
                ResourceGrant.user_id == user.id, ResourceGrant.resource_type == resource_type,
                ResourceGrant.resource_id == resource_id,
            ))
            if grant is None:
                db.add(ResourceGrant(
                    user_id=user.id, resource_type=resource_type, resource_id=resource_id,
                    can_read=True, can_query=True,
                ))
        db.commit()
        seed_v1_runtime(db, workspace.id)
        return Actor(
            label="workspace-b", email=email, password=password,
            datasource_id=datasource.id, semantic_model_id=model.id, workspace_id=workspace.id,
        )


def _cleanup_release_load_tenant(workspace_id: str) -> str | None:
    from app.db.session import SessionLocal
    from app.models import Workspace

    try:
        with SessionLocal() as db:
            workspace = db.get(Workspace, workspace_id)
            if workspace is not None:
                db.delete(workspace); db.commit()
        return None
    except Exception as exc:
        return f"{type(exc).__name__}:{str(exc)[:200]}"


def _memory_mib(value: str) -> float:
    match = re.fullmatch(r"\s*([0-9.]+)\s*([KMG]?i?B)\s*", value, re.IGNORECASE)
    if not match:
        raise ValueError(f"Unsupported docker memory value: {value!r}")
    number, unit = match.groups()
    unit = unit[0].upper() + unit[1:]
    factor = {"B": 1 / 1024 / 1024, "KiB": 1 / 1024, "MiB": 1, "GiB": 1024}.get(unit, 0)
    return float(number) * factor


def _docker_snapshot() -> dict[str, dict[str, float]]:
    completed = subprocess.run(
        ["docker", "stats", "--no-stream", "--format", "{{json .}}"],
        check=True, capture_output=True, text=True, timeout=20,
    )
    result: dict[str, dict[str, float]] = {}
    for line in completed.stdout.splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        name = str(item.get("Name", ""))
        if not name.startswith("chatbi-v2-"):
            continue
        used = str(item.get("MemUsage", "0 B / 0 B")).split("/", 1)[0].strip()
        result[name] = {
            "cpu_percent": float(str(item.get("CPUPerc", "0%")).rstrip("%") or 0),
            "memory_mib": _memory_mib(used),
        }
    return result


def _database_connections(env: dict[str, str]) -> dict[str, int]:
    with connect(env) as conn:
        row = conn.execute(
            "SELECT count(*), count(*) FILTER (WHERE state <> 'idle') "
            "FROM pg_stat_activity WHERE datname=current_database()"
        ).fetchone()
        return {"total": int(row[0]), "active": int(row[1])}


def _find_mapping(value, key: str) -> dict | None:
    if isinstance(value, dict):
        if isinstance(value.get(key), dict):
            return value[key]
        for nested in value.values():
            found = _find_mapping(nested, key)
            if found is not None:
                return found
    elif isinstance(value, list):
        for nested in value:
            found = _find_mapping(nested, key)
            if found is not None:
                return found
    return None


async def _consume_stream(
    actor: Actor, conversation_id: str, route: str, attachment_id: str | None,
    metrics: dict, raw: list[dict], *, slow_client: bool, cache_variant: int,
) -> None:
    assert actor.client is not None
    started = time.perf_counter()
    first_event = None
    event_times: list[float] = []
    completed = False
    accepted = False
    error = None
    payload_result = None
    question = ROUTE_QUESTIONS[route]
    if cache_variant:
        question += f" 分析批次 {cache_variant}。"
    try:
        async with actor.client.stream(
            "POST", "/chat/stream",
            json={
                "conversation_id": conversation_id, "client_message_id": f"load-{uuid4()}",
                "content": question, "route": route,
                "datasource_id": actor.datasource_id, "semantic_model_id": actor.semantic_model_id,
                "attachment_ids": [attachment_id] if attachment_id and route == "FILE_QUERY" else [],
            }, timeout=90.0,
        ) as response:
            if response.status_code != 200:
                error = f"HTTP_{response.status_code}"
                return
            buffer = ""
            async for chunk in response.aiter_text():
                now = time.perf_counter()
                if first_event is None:
                    first_event = now
                buffer += chunk
                blocks = buffer.split("\n\n")
                buffer = blocks.pop()
                for block in blocks:
                    event_line = next((line for line in block.splitlines() if line.startswith("event:")), "")
                    event = event_line.split(":", 1)[1].strip() if event_line else ""
                    if not event:
                        continue
                    event_times.append(now)
                    metrics["events"][event] += 1
                    data_line = next((line for line in block.splitlines() if line.startswith("data:")), "")
                    data = json.loads(data_line.split(":", 1)[1].strip()) if data_line else {}
                    if event == "accepted":
                        accepted = True
                    elif event == "completed":
                        completed = True
                    elif event == "result":
                        payload_result = data
                    if event not in {"progress", "result"}:
                        required = {"trace_id", "sequence", "event", "timestamp", "elapsed_ms", "capability", "message", "data"}
                        missing = sorted(required.difference(data))
                        if missing:
                            metrics["envelope_errors"].append(f"{event}:{','.join(missing)}")
                if slow_client:
                    await asyncio.sleep(0.02)
    except Exception as exc:
        error = type(exc).__name__
    finally:
        finished = time.perf_counter()
        duration_ms = (finished - started) * 1000
        ttfe_ms = (first_event - started) * 1000 if first_event is not None else None
        metrics["requests"] += 1
        metrics["routes"][route] += 1
        metrics["duration_ms"].append(duration_ms)
        metrics["stage_ms"][route.lower()].append(duration_ms)
        if ttfe_ms is not None:
            metrics["ttfe_ms"].append(ttfe_ms)
        if accepted:
            metrics["accepted_requests"] += 1
        if completed:
            metrics["completed_requests"] += 1
        if error or not completed:
            metrics["errors"].append({"route": route, "error": error or "NO_COMPLETED_EVENT"})
        if len(event_times) > 1:
            metrics["max_gaps_ms"].append(max((right - left) * 1000 for left, right in zip(event_times, event_times[1:])))
        if duration_ms > 10_000:
            metrics["over_10s"] += 1
            if len(event_times) > 1 and max((right - left) for left, right in zip(event_times, event_times[1:])) <= 3.0:
                metrics["over_10s_streamed"] += 1
        if payload_result:
            semantic = _find_mapping(payload_result, "semantic_runtime")
            if semantic:
                linking = semantic.get("schema_linking") or {}
                metrics["cache_hits" if linking.get("cache_hit") else "cache_misses"] += 1
                metrics["cache_scopes"][actor.label].add(str(linking.get("cache_scope", "")))
                latency = semantic.get("stage_latency_ms") or {}
                for key in ("openchatbi", "supersonic", "wren"):
                    if latency.get(key) is not None:
                        metrics["stage_ms"][key].append(float(latency[key]))
            execution = _find_mapping(payload_result, "execution")
            if execution and execution.get("duration_ms") is not None:
                metrics["stage_ms"]["sql"].append(float(execution["duration_ms"]))
            query_performance = _find_mapping(payload_result, "query_performance")
            if query_performance and query_performance.get("oracle_ms") is not None:
                metrics["stage_ms"]["oracle"].append(float(query_performance["oracle_ms"]))
        raw.append({
            "timestamp": datetime.now(timezone.utc).isoformat(), "workspace": actor.label,
            "route": route, "status": "PASS" if completed and not error else "FAIL",
            "duration_ms": round(duration_ms, 3),
            "ttfe_ms": round(ttfe_ms, 3) if ttfe_ms is not None else "",
            "slow_client": slow_client, "error": error or "",
        })


async def _dedicated_request(actor: Actor, route: str, metrics: dict, raw: list[dict]) -> None:
    assert actor.client is not None
    started = time.perf_counter()
    error = None
    try:
        if route == "SQL_WORKSPACE":
            response = await actor.client.post("/data-workspace/sql/execute", json={
                "datasource_id": actor.datasource_id,
                "sql": "SELECT order_id, revenue FROM demo_business.orders ORDER BY order_id LIMIT 5",
                "row_limit": 5,
            })
        elif route == "FEEDBACK":
            response = await actor.client.post("/evaluation/feedback/recall", json={
                "question": "按地区统计销售额", "datasource_id": actor.datasource_id,
                "semantic_model_id": actor.semantic_model_id,
            })
        else:
            response = await actor.client.get("/evaluation/dashboard")
        if response.status_code >= 400:
            error = f"HTTP_{response.status_code}"
    except Exception as exc:
        error = type(exc).__name__
    duration_ms = (time.perf_counter() - started) * 1000
    metrics["requests"] += 1
    metrics["routes"][route] += 1
    metrics["duration_ms"].append(duration_ms)
    metrics["stage_ms"][route.lower()].append(duration_ms)
    if error:
        metrics["errors"].append({"route": route, "error": error})
    else:
        metrics["completed_requests"] += 1
    raw.append({
        "timestamp": datetime.now(timezone.utc).isoformat(), "workspace": actor.label,
        "route": route, "status": "FAIL" if error else "PASS",
        "duration_ms": round(duration_ms, 3), "ttfe_ms": "", "slow_client": False,
        "error": error or "",
    })


async def _planned_disconnect(actor: Actor, conversation_id: str, metrics: dict) -> None:
    assert actor.client is not None
    metrics["planned_disconnect_attempts"] += 1
    failure = "NO_ACCEPTED_EVENT"
    for attempt in range(2):
        response = None
        try:
            # Use a disposable connection pool for deliberate disconnects so
            # closing a partial HTTP/1.1 response cannot poison normal load
            # traffic sharing the authenticated actor client.
            async with httpx.AsyncClient(
                base_url=str(actor.client.base_url), cookies=dict(actor.client.cookies),
                timeout=30, trust_env=False,
            ) as probe:
                request = probe.build_request("POST", "/chat/stream", json={
                    "conversation_id": conversation_id, "client_message_id": f"disconnect-{uuid4()}",
                    "content": ROUTE_QUESTIONS["COMPLEX_ANALYSIS"], "route": "COMPLEX_ANALYSIS",
                    "datasource_id": actor.datasource_id, "semantic_model_id": actor.semantic_model_id,
                    "attachment_ids": [],
                })
                response = await probe.send(request, stream=True)
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line.startswith("event: accepted"):
                        metrics["planned_disconnects"] += 1
                        return
        except httpx.HTTPError as exc:
            failure = type(exc).__name__
            if attempt == 0:
                await asyncio.sleep(0.05)
                continue
        finally:
            if response is not None:
                await response.aclose()
        break
    metrics["planned_disconnect_failures"] += 1
    metrics["errors"].append({"route": "PLANNED_DISCONNECT", "error": failure})


async def _verify_cancellation_and_leaks(actor: Actor) -> dict:
    assert actor.client is not None
    response = await actor.client.post("/conversations", json={"title": "v2.1-cancel-check"})
    response.raise_for_status()
    conversation_id = response.json()["id"]
    request = actor.client.build_request("POST", "/chat/stream", json={
        "conversation_id": conversation_id, "client_message_id": f"cancel-{uuid4()}",
        "content": ROUTE_QUESTIONS["COMPLEX_ANALYSIS"], "route": "COMPLEX_ANALYSIS",
        "datasource_id": actor.datasource_id, "semantic_model_id": actor.semantic_model_id,
        "attachment_ids": [],
    })
    response = await actor.client.send(request, stream=True)
    response.raise_for_status()
    async for line in response.aiter_lines():
        if line.startswith("event: accepted"):
            break
    cancelled_at = time.perf_counter()
    await response.aclose()
    snapshot = None
    while time.perf_counter() - cancelled_at < 5.0:
        probe = await actor.client.get("/chat/stream/diagnostics")
        probe.raise_for_status()
        snapshot = probe.json()
        active = sum(int(snapshot.get(key, -1)) for key in (
            "active_connections", "active_tasks", "active_agent_tasks", "active_sandbox_tasks",
        ))
        if active == 0:
            break
        await asyncio.sleep(0.05)
    cleanup_ms = (time.perf_counter() - cancelled_at) * 1000
    await actor.client.delete(f"/conversations/{conversation_id}")
    return {"cleanup_ms": round(cleanup_ms, 3), "diagnostics": snapshot}


async def _sample_runtime(actor: Actor, env: dict[str, str], stop: asyncio.Event, samples: list[dict]) -> None:
    assert actor.client is not None
    while not stop.is_set():
        try:
            diagnostics = (await actor.client.get("/chat/stream/diagnostics")).json()
            samples.append({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "containers": await asyncio.to_thread(_docker_snapshot),
                "db_connections": await asyncio.to_thread(_database_connections, env),
                "diagnostics": diagnostics,
            })
        except Exception as exc:
            samples.append({"timestamp": datetime.now(timezone.utc).isoformat(), "sample_error": type(exc).__name__})
        try:
            await asyncio.wait_for(stop.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            pass


def _new_metrics() -> dict:
    return {
        "requests": 0, "errors": [], "ttfe_ms": [], "duration_ms": [], "max_gaps_ms": [],
        "events": Counter(), "routes": Counter(), "over_10s": 0, "over_10s_streamed": 0,
        "accepted_requests": 0, "completed_requests": 0, "envelope_errors": [],
        "cache_hits": 0, "cache_misses": 0, "cache_scopes": defaultdict(set),
        "stage_ms": defaultdict(list), "planned_disconnect_attempts": 0,
        "planned_disconnects": 0, "planned_disconnect_failures": 0,
    }


async def run_load(base_url: str, env: dict[str, str], concurrency: int, duration_seconds: int) -> tuple[dict, list[dict]]:
    limits = httpx.Limits(max_connections=concurrency + 20, max_keepalive_connections=concurrency + 20)
    metrics = _new_metrics()
    raw: list[dict] = []
    samples: list[dict] = []
    async with httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=10, trust_env=False) as anonymous:
        # Probe authentication with a syntactically valid request. An empty
        # payload tests request validation precedence (422), not whether the
        # protected SSE product path rejects an unauthenticated caller.
        anonymous_401 = (await anonymous.post("/chat/stream", json={
            "conversation_id": "unauthenticated-probe",
            "client_message_id": f"unauthenticated-{uuid4()}",
            "content": "authentication boundary probe",
            "attachment_ids": [],
        })).status_code == 401

    secondary = await asyncio.to_thread(_clone_release_load_tenant)
    tenant_cleanup_error = None
    try:
        async with AsyncExitStack() as stack:
            primary_client = await stack.enter_async_context(httpx.AsyncClient(
                base_url=base_url.rstrip("/"), limits=limits, timeout=90, trust_env=False,
            ))
            login = await primary_client.post("/auth/login", json={
                "email": "admin@chatbi.local", "password": env["CHATBI_BOOTSTRAP_ADMIN_PASSWORD"], "remember": False,
            })
            login.raise_for_status()
            principal = (await primary_client.get("/auth/me")).json()
            datasources = (await primary_client.get("/datasources")).json()
            models = (await primary_client.get("/semantic-models")).json()
            primary_ds = next(item for item in datasources if item["type"] == "postgresql")
            primary_model = next(item for item in models if item["datasource_id"] == primary_ds["id"] and item["status"] == "PUBLISHED")
            primary = Actor(
                label="workspace-a", email="admin@chatbi.local", password="",
                datasource_id=primary_ds["id"], semantic_model_id=primary_model["id"],
                workspace_id=principal["user"]["workspace_id"], client=primary_client,
            )
            secondary_client = await stack.enter_async_context(httpx.AsyncClient(
                base_url=base_url.rstrip("/"), limits=limits, timeout=90, trust_env=False,
            ))
            login = await secondary_client.post("/auth/login", json={
                "email": secondary.email, "password": secondary.password, "remember": False,
            })
            login.raise_for_status()
            secondary.client = secondary_client
            actors = [primary, secondary]

            conversations: list[tuple[Actor, str, str]] = []
            for index in range(concurrency):
                actor = actors[index % len(actors)]
                response = await actor.client.post("/conversations", json={"title": f"v2.1-final-load-{index + 1}"})
                response.raise_for_status()
                conversation_id = response.json()["id"]
                upload = await actor.client.post(
                    "/attachments", data={"conversation_id": conversation_id},
                    files={"file": ("load-regions.csv", b"region,revenue\nEast,270\nSouth,150\n", "text/csv")},
                )
                upload.raise_for_status()
                conversations.append((actor, conversation_id, upload.json()["id"]))

            # Warm every route at target concurrency before taking the memory
            # baseline. This separates stable module/thread/pool high-water
            # allocation from a true 15-minute growth leak.
            warm_metrics = _new_metrics()
            warm_raw: list[dict] = []

            async def warm_worker(index: int) -> None:
                actor, conversation_id, attachment_id = conversations[index]
                route = MIXED_ROUTES[index % len(MIXED_ROUTES)]
                target = primary if route in {"FEEDBACK", "EVALUATION"} else actor
                target_conversation = conversation_id if target is actor else conversations[0][1]
                target_attachment = attachment_id if target is actor else conversations[0][2]
                if route in ROUTE_QUESTIONS:
                    await _consume_stream(
                        target, target_conversation, route, target_attachment,
                        warm_metrics, warm_raw, slow_client=False, cache_variant=index % 7,
                    )
                else:
                    await _dedicated_request(target, route, warm_metrics, warm_raw)

            await asyncio.gather(*(warm_worker(index) for index in range(concurrency)))
            cache_warm_conversations: dict[str, tuple[str, str]] = {}
            for actor in actors:
                response = await actor.client.post("/conversations", json={"title": "v2.1-cache-warm"})
                response.raise_for_status()
                warm_conversation_id = response.json()["id"]
                upload = await actor.client.post(
                    "/attachments", data={"conversation_id": warm_conversation_id},
                    files={"file": ("warm.csv", b"region,revenue\nEast,1\n", "text/csv")},
                )
                upload.raise_for_status()
                cache_warm_conversations[actor.label] = (warm_conversation_id, upload.json()["id"])

            cache_jobs = [
                (actor, route, variant)
                for actor in actors
                for route in ("DATA_QUERY", "HYBRID_ANALYSIS", "COMPLEX_ANALYSIS")
                for variant in range(31)
            ]
            warm_semaphore = asyncio.Semaphore(concurrency)

            async def warm_cache(actor: Actor, route: str, variant: int) -> None:
                async with warm_semaphore:
                    conversation_id, attachment_id = cache_warm_conversations[actor.label]
                    await _consume_stream(
                        actor, conversation_id, route, attachment_id,
                        warm_metrics, warm_raw, slow_client=False, cache_variant=variant,
                    )

            await asyncio.gather(*(warm_cache(*job) for job in cache_jobs))
            for actor in actors:
                await actor.client.delete(f"/conversations/{cache_warm_conversations[actor.label][0]}")
            if warm_metrics["errors"]:
                raise RuntimeError(f"load warm-up failed: {warm_metrics['errors'][:3]}")
            metrics = _new_metrics()
            stop_sampler = asyncio.Event()
            sampler = asyncio.create_task(_sample_runtime(primary, env, stop_sampler, samples))
            await asyncio.sleep(5.2)
            started = time.monotonic()
            deadline = started + duration_seconds

            async def worker(index: int) -> None:
                actor, conversation_id, attachment_id = conversations[index]
                iteration = 0
                while time.monotonic() < deadline:
                    route = MIXED_ROUTES[(index + iteration) % len(MIXED_ROUTES)]
                    target = primary if route in {"FEEDBACK", "EVALUATION"} else actor
                    target_conversation = conversation_id if target is actor else conversations[0][1]
                    target_attachment = attachment_id if target is actor else conversations[0][2]
                    if route in ROUTE_QUESTIONS:
                        await _consume_stream(
                            target, target_conversation, route, target_attachment,
                            metrics, raw, slow_client=index % 7 == 0,
                            cache_variant=0 if iteration % 2 == 0 else iteration % 31,
                        )
                    else:
                        await _dedicated_request(target, route, metrics, raw)
                    iteration += 1
                    if iteration % 25 == 0:
                        await _planned_disconnect(actor, conversation_id, metrics)
                    await asyncio.sleep(0.05)

            await asyncio.gather(*(worker(index) for index in range(concurrency)))
            actual_duration = time.monotonic() - started
            cancellation = await _verify_cancellation_and_leaks(primary)
            for actor, conversation_id, _ in conversations:
                await actor.client.delete(f"/conversations/{conversation_id}")
            await asyncio.sleep(5.2)
            stop_sampler.set(); await sampler
            final_diagnostics = (await primary.client.get("/chat/stream/diagnostics")).json()
    finally:
        tenant_cleanup_error = await asyncio.to_thread(_cleanup_release_load_tenant, secondary.workspace_id)

    valid_samples = [item for item in samples if "sample_error" not in item]
    memory_totals = [sum(container["memory_mib"] for container in item["containers"].values()) for item in valid_samples]
    db_connections = [item["db_connections"] for item in valid_samples]
    db_totals = [item["total"] for item in db_connections]
    db_active = [item["active"] for item in db_connections]
    cpu_values = [container["cpu_percent"] for item in valid_samples for container in item["containers"].values()]
    first_memory = statistics.mean(memory_totals[:2]) if memory_totals else 0
    last_memory = statistics.mean(memory_totals[-2:]) if memory_totals else 0
    memory_growth_mib = last_memory - first_memory
    memory_leak = int(memory_growth_mib > max(64.0, first_memory * 0.25))
    db_baseline = min(db_totals[:2]) if db_totals else -1
    db_final = min(db_totals[-2:]) if db_totals else -1
    db_active_baseline = min(db_active[:2]) if db_active else -1
    db_active_final = min(db_active[-2:]) if db_active else -1
    # Pools deliberately retain authenticated idle connections. A leak is an
    # active query/session that remains after all clients and streams close.
    db_connection_leak = max(0, db_active_final - db_active_baseline) if db_active_baseline >= 0 else -1
    diagnostics_values = [item["diagnostics"] for item in valid_samples]
    active_sse_max = max((int(item.get("active_connections", 0)) for item in diagnostics_values), default=0)
    active_agent_max = max((int(item.get("active_agent_tasks", 0)) for item in diagnostics_values), default=0)
    active_sandbox_max = max((int(item.get("active_sandbox_tasks", 0)) for item in diagnostics_values), default=0)
    requests = metrics["requests"]
    errors = len(metrics["errors"])
    cache_scope_leak = int(any(
        scope and f"workspace:{secondary.workspace_id}" in scope
        for scope in metrics["cache_scopes"]["workspace-a"]
    ) or any(
        scope and f"workspace:{primary.workspace_id}" in scope
        for scope in metrics["cache_scopes"]["workspace-b"]
    ))
    stage_summary = {
        name: {"samples": len(values), "p50_ms": percentile(values, 0.50), "p95_ms": percentile(values, 0.95)}
        for name, values in metrics["stage_ms"].items()
    }
    for public_name, internal_name in {
        "catalog": "openchatbi",
        "schema_linking": "openchatbi",
        "semantic_parse": "supersonic",
        "wren_compile": "wren",
        "rag": "knowledge_query",
        "agent": "complex_analysis",
        "python_file": "file_query",
    }.items():
        if internal_name in stage_summary:
            stage_summary[public_name] = dict(stage_summary[internal_name])
    stage_summary["sse_ttfe"] = {
        "samples": len(metrics["ttfe_ms"]),
        "p50_ms": percentile(metrics["ttfe_ms"], 0.50),
        "p95_ms": percentile(metrics["ttfe_ms"], 0.95),
    }
    active_final = sum(int(final_diagnostics.get(key, 0)) for key in (
        "active_connections", "active_tasks", "active_agent_tasks", "active_sandbox_tasks",
    ))
    stream_requests = sum(metrics["routes"][key] for key in ROUTE_QUESTIONS)
    report = {
        "concurrency": concurrency, "configured_duration_seconds": duration_seconds,
        "actual_duration_seconds": round(actual_duration, 3), "workspace_count": 2,
        "authenticated_user_count": 2, "requests": requests, "successes": requests - errors,
        "errors": errors, "error_rate": round(errors / requests, 6) if requests else 1.0,
        "p50_ms": percentile(metrics["duration_ms"], 0.50),
        "p95_ms": percentile(metrics["duration_ms"], 0.95),
        "p99_ms": percentile(metrics["duration_ms"], 0.99),
        "ttfe_p50_ms": percentile(metrics["ttfe_ms"], 0.50),
        "ttfe_p95_ms": percentile(metrics["ttfe_ms"], 0.95),
        "all_query_sse_rate": round(metrics["accepted_requests"] / stream_requests, 6) if stream_requests else 0,
        "completed_rate": round(metrics["completed_requests"] / requests, 6) if requests else 0,
        "heartbeat_max_gap_ms": round(max(metrics["max_gaps_ms"]), 3) if metrics["max_gaps_ms"] else None,
        "over_10s_requests": metrics["over_10s"],
        "over_10s_streaming_rate": round(metrics["over_10s_streamed"] / metrics["over_10s"], 6) if metrics["over_10s"] else 1.0,
        "routes": dict(metrics["routes"]), "events": dict(metrics["events"]),
        "stage_latency": stage_summary, "cache_hits": metrics["cache_hits"],
        "cache_misses": metrics["cache_misses"],
        "planned_disconnect_attempts": metrics["planned_disconnect_attempts"],
        "planned_disconnects": metrics["planned_disconnects"],
        "planned_disconnect_failures": metrics["planned_disconnect_failures"],
        "unauthenticated_sse_401": anonymous_401, "cancellation": cancellation,
        "cpu_percent_p95": percentile(cpu_values, 0.95),
        "memory_first_mib": round(first_memory, 3), "memory_final_mib": round(last_memory, 3),
        "memory_growth_mib": round(memory_growth_mib, 3), "memory_leak": memory_leak,
        "db_connections_baseline": db_baseline, "db_connections_final": db_final,
        "db_active_baseline": db_active_baseline, "db_active_final": db_active_final,
        "db_connection_leak": db_connection_leak, "active_sse_max": active_sse_max,
        "active_agent_tasks_max": active_agent_max, "active_sandbox_tasks_max": active_sandbox_max,
        "sse_connection_leak": int(final_diagnostics.get("active_connections", -1)),
        "background_task_leak": active_final, "cross_workspace_cache_leak": cache_scope_leak,
        "tenant_cleanup_error": tenant_cleanup_error,
        "envelope_errors": metrics["envelope_errors"][:20], "error_samples": metrics["errors"][:20],
        "resource_samples": samples,
    }
    return report, raw


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=[
            "timestamp", "workspace", "route", "status", "duration_ms", "ttfe_ms", "slow_client", "error",
        ])
        writer.writeheader(); writer.writerows(rows)


def release_gate_failures(report: dict) -> list[str]:
    load = report.get("load") or {}
    database = report.get("database") or {}
    stages = load.get("stage_latency") or {}
    required_routes = {
        "DATA_QUERY", "KNOWLEDGE_QUERY", "HYBRID_ANALYSIS", "COMPLEX_ANALYSIS",
        "FILE_QUERY", "SQL_WORKSPACE", "FEEDBACK", "EVALUATION",
    }
    checks = {
        "concurrency": load.get("concurrency") == 20,
        "duration": float(load.get("actual_duration_seconds") or 0) >= 900,
        "error_rate": float(load.get("error_rate", 1)) < 0.01,
        "ttfe": float(load.get("ttfe_p95_ms") or 999999) <= 1000,
        "heartbeat": float(load.get("heartbeat_max_gap_ms") or 999999) <= 3000,
        "over_10s_streaming": load.get("over_10s_streaming_rate") == 1.0,
        "cancel_cleanup": float((load.get("cancellation") or {}).get("cleanup_ms") or 999999) <= 5000,
        "leaks": all(load.get(key) == 0 for key in (
            "db_connection_leak", "memory_leak", "sse_connection_leak",
            "background_task_leak", "cross_workspace_cache_leak",
        )),
        "database": float((database.get("simple") or {}).get("p95_ms") or 999999) <= 5000
        and float((database.get("standard") or {}).get("p95_ms") or 999999) <= 10000
        and float((database.get("complex") or {}).get("p95_ms") or 999999) <= 30000
        and float((database.get("advanced") or {}).get("p95_ms") or 999999) <= 60000,
        "routes": required_routes.issubset({
            name for name, count in (load.get("routes") or {}).items() if int(count or 0) > 0
        }),
        "scope_and_cache": load.get("workspace_count", 0) >= 2
        and load.get("authenticated_user_count", 0) >= 2
        and load.get("cache_hits", 0) > 0
        and load.get("cache_misses", 0) > 0
        and load.get("planned_disconnects", 0) > 0
        and load.get("planned_disconnect_failures", 1) == 0
        and load.get("unauthenticated_sse_401") is True,
        "protocol": load.get("all_query_sse_rate") == 1.0
        and not load.get("envelope_errors")
        and load.get("tenant_cleanup_error") is None,
        "stages": int((stages.get("catalog") or {}).get("samples") or 0) > 0
        and float((stages.get("catalog") or {}).get("p95_ms") or 999999) <= 1000
        and int((stages.get("semantic_parse") or {}).get("samples") or 0) > 0
        and float((stages.get("semantic_parse") or {}).get("p95_ms") or 999999) <= 1500
        and int((stages.get("wren_compile") or {}).get("samples") or 0) > 0
        and float((stages.get("wren_compile") or {}).get("p95_ms") or 999999) <= 2000
        and int((stages.get("oracle") or {}).get("samples") or 0) > 0,
    }
    return sorted(name for name, passed in checks.items() if not passed)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--schema", default="chatbi_benchmark_v21")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000/api/v1")
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--duration-minutes", type=float, default=15.0)
    parser.add_argument("--db-repeats", type=int, default=20)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--csv-output", type=Path)
    parser.add_argument("--enforce-release-gates", action="store_true")
    args = parser.parse_args()
    schema = validate_schema(args.schema)
    env = load_env(args.env_file)
    _configure_backend_environment(env)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(), "schema": schema,
        "database": run_database_benchmarks(env, schema, args.db_repeats), "load": None,
    }
    raw: list[dict] = []
    if args.base_url:
        report["load"], raw = asyncio.run(run_load(
            args.base_url, env, args.concurrency, round(args.duration_minutes * 60),
        ))
    failures = release_gate_failures(report)
    report["release_gate"] = {
        "enforced": args.enforce_release_gates,
        "pass": not failures,
        "failures": failures,
    }
    atomic_json(args.output, report)
    write_csv(args.csv_output or args.output.with_suffix(".csv"), raw)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 2 if args.enforce_release_gates and failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
