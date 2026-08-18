from __future__ import annotations

import argparse
import asyncio
import json
import math
import statistics
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import httpx

import sys

DEMO_DB = Path(__file__).resolve().parents[1] / "demo_db"
sys.path.insert(0, str(DEMO_DB))
from _common import atomic_json, connect, load_env, validate_schema  # noqa: E402


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
            "runs": len(values),
            "p50_ms": percentile(values, 0.50),
            "p95_ms": percentile(values, 0.95),
            "max_ms": round(max(values), 3),
        }
        for name, values in samples.items()
    }


ROUTE_QUESTIONS = {
    "DATA_QUERY": "今年华东区销售额是多少？",
    "KNOWLEDGE_QUERY": "有效订单的业务定义是什么？",
    "HYBRID_ANALYSIS": "为什么本月销售额发生变化？请结合业务规则说明。",
    "COMPLEX_ANALYSIS": "请按区域和产品分解今年销售额并给出有证据的建议。",
}


async def consume_stream(client: httpx.AsyncClient, conversation_id: str, route: str, metrics: dict) -> None:
    started = time.perf_counter()
    first_event = None
    event_times: list[float] = []
    completed = False
    accepted = False
    envelope_errors: list[str] = []
    try:
        async with client.stream(
            "POST",
            "/chat/stream",
            json={
                "conversation_id": conversation_id,
                "client_message_id": f"load-{uuid4()}",
                "content": ROUTE_QUESTIONS[route],
                "route": route,
                "attachment_ids": [],
            },
            timeout=75.0,
        ) as response:
            if response.status_code != 200:
                metrics["errors"].append({"route": route, "status": response.status_code})
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
                    if event:
                        event_times.append(now)
                        metrics["events"][event] += 1
                        if event == "accepted":
                            accepted = True
                        data_line = next((line for line in block.splitlines() if line.startswith("data:")), "")
                        if event not in {"progress", "result"} and data_line:
                            payload = json.loads(data_line.split(":", 1)[1].strip())
                            required = {"trace_id", "sequence", "event", "timestamp", "elapsed_ms", "capability", "message", "data"}
                            missing = sorted(required.difference(payload))
                            if missing:
                                envelope_errors.append(f"{event}:{','.join(missing)}")
                    if event == "completed":
                        completed = True
            if not completed:
                metrics["errors"].append({"route": route, "status": "NO_COMPLETED_EVENT"})
    except Exception as exc:
        metrics["errors"].append({"route": route, "status": type(exc).__name__})
    finally:
        finished = time.perf_counter()
        metrics["requests"] += 1
        metrics["routes"][route] += 1
        if first_event is not None:
            metrics["ttfe_ms"].append((first_event - started) * 1000)
        if accepted:
            metrics["accepted_requests"] += 1
        if completed:
            metrics["completed_requests"] += 1
        metrics["envelope_errors"].extend(envelope_errors)
        metrics["duration_ms"].append((finished - started) * 1000)
        if len(event_times) > 1:
            metrics["max_gaps_ms"].append(max((right - left) * 1000 for left, right in zip(event_times, event_times[1:])))
        if finished - started > 10:
            metrics["over_10s"] += 1
            if len(event_times) > 1 and max((right - left) for left, right in zip(event_times, event_times[1:])) <= 3.5:
                metrics["over_10s_streamed"] += 1


async def verify_cancellation_and_leaks(client: httpx.AsyncClient) -> dict:
    response = await client.post("/conversations", json={"title": "v2.1-cancel-check"})
    response.raise_for_status()
    conversation_id = response.json()["id"]
    request = client.build_request(
        "POST",
        "/chat/stream",
        json={
            "conversation_id": conversation_id,
            "client_message_id": f"cancel-{uuid4()}",
            "content": ROUTE_QUESTIONS["COMPLEX_ANALYSIS"],
            "route": "COMPLEX_ANALYSIS",
            "attachment_ids": [],
        },
    )
    response = await client.send(request, stream=True)
    response.raise_for_status()
    async for line in response.aiter_lines():
        if line.startswith("event: accepted"):
            break
    cancelled_at = time.perf_counter()
    await response.aclose()
    snapshot = None
    while time.perf_counter() - cancelled_at < 5.0:
        snapshot_response = await client.get("/chat/stream/diagnostics")
        snapshot_response.raise_for_status()
        snapshot = snapshot_response.json()
        if snapshot.get("active_connections") == 0 and snapshot.get("active_tasks") == 0:
            break
        await asyncio.sleep(0.05)
    cleanup_ms = (time.perf_counter() - cancelled_at) * 1000
    await client.delete(f"/conversations/{conversation_id}")
    return {
        "cleanup_ms": round(cleanup_ms, 3),
        "connection_leak_count": int((snapshot or {}).get("active_connections", -1)),
        "task_leak_count": int((snapshot or {}).get("active_tasks", -1)),
        "diagnostics": snapshot,
    }


async def run_load(base_url: str, env: dict[str, str], concurrency: int, duration_seconds: int) -> dict:
    limits = httpx.Limits(max_connections=concurrency + 5, max_keepalive_connections=concurrency + 5)
    metrics = {
        "requests": 0,
        "errors": [],
        "ttfe_ms": [],
        "duration_ms": [],
        "max_gaps_ms": [],
        "events": Counter(),
        "routes": Counter(),
        "over_10s": 0,
        "over_10s_streamed": 0,
        "accepted_requests": 0,
        "completed_requests": 0,
        "envelope_errors": [],
    }
    unauthenticated_401 = False
    async with httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=10.0, trust_env=False) as anonymous:
        response = await anonymous.post("/chat/stream", json={})
        unauthenticated_401 = response.status_code == 401
    async with httpx.AsyncClient(base_url=base_url.rstrip("/"), limits=limits, timeout=75.0, trust_env=False) as client:
        login = await client.post("/auth/login", json={"email": "admin@chatbi.local", "password": env["CHATBI_BOOTSTRAP_ADMIN_PASSWORD"], "remember": False})
        login.raise_for_status()
        conversations = []
        for index in range(concurrency):
            response = await client.post("/conversations", json={"title": f"v2.1-load-{index + 1}"})
            response.raise_for_status()
            conversations.append(response.json()["id"])
        deadline = time.monotonic() + duration_seconds

        async def worker(index: int) -> None:
            route_names = tuple(ROUTE_QUESTIONS)
            iteration = 0
            while time.monotonic() < deadline:
                route = route_names[(index + iteration) % len(route_names)]
                await consume_stream(client, conversations[index], route, metrics)
                iteration += 1
                await asyncio.sleep(0.2)

        await asyncio.gather(*(worker(index) for index in range(concurrency)))
        for conversation_id in conversations:
            await client.delete(f"/conversations/{conversation_id}")
        cancellation = await verify_cancellation_and_leaks(client)

    requests = metrics["requests"]
    errors = len(metrics["errors"])
    return {
        "concurrency": concurrency,
        "duration_seconds": duration_seconds,
        "requests": requests,
        "errors": errors,
        "error_rate": round(errors / requests, 6) if requests else 1.0,
        "all_query_sse_rate": round(metrics["accepted_requests"] / requests, 6) if requests else 0.0,
        "completed_rate": round(metrics["completed_requests"] / requests, 6) if requests else 0.0,
        "ttfe_p50_ms": percentile(metrics["ttfe_ms"], 0.50),
        "ttfe_p95_ms": percentile(metrics["ttfe_ms"], 0.95),
        "request_p95_ms": percentile(metrics["duration_ms"], 0.95),
        "heartbeat_max_gap_ms": round(max(metrics["max_gaps_ms"]), 3) if metrics["max_gaps_ms"] else None,
        "over_10s_requests": metrics["over_10s"],
        "over_10s_streaming_rate": round(metrics["over_10s_streamed"] / metrics["over_10s"], 6) if metrics["over_10s"] else 1.0,
        "events": dict(metrics["events"]),
        "routes": dict(metrics["routes"]),
        "envelope_errors": metrics["envelope_errors"][:20],
        "unauthenticated_sse_401": unauthenticated_401,
        "cancellation": cancellation,
        "sse_leak_count": cancellation["connection_leak_count"] + cancellation["task_leak_count"],
        "error_samples": metrics["errors"][:20],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--schema", default="chatbi_benchmark_v21")
    parser.add_argument("--base-url", default="")
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--duration-minutes", type=float, default=15.0)
    parser.add_argument("--db-repeats", type=int, default=20)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    schema = validate_schema(args.schema)
    env = load_env(args.env_file)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "schema": schema,
        "database": run_database_benchmarks(env, schema, args.db_repeats),
        "load": None,
    }
    if args.base_url:
        report["load"] = asyncio.run(run_load(args.base_url, env, args.concurrency, round(args.duration_minutes * 60)))
    atomic_json(args.output, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
