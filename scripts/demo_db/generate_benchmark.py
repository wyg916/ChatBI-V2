from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from time import perf_counter

from _common import IDENTIFIER, atomic_json, canonical_hash, connect, load_env, render_template, validate_schema
from generate_ground_truth import build_cases


SCALES = {
    "100K": {"sales": 100_000, "payments": 50_000, "products": 5_000, "customers": 30_000},
    "1M": {"sales": 1_000_000, "payments": 500_000, "products": 50_000, "customers": 300_000},
    "10M": {"sales": 10_000_000, "payments": 5_000_000, "products": 50_000, "customers": 300_000},
}


def month_starts(start: date, end: date):
    current = date(start.year, start.month, 1)
    boundary = date(end.year + (end.month == 12), 1 if end.month == 12 else end.month + 1, 1)
    while current < boundary:
        following = date(current.year + (current.month == 12), 1 if current.month == 12 else current.month + 1, 1)
        yield current, following
        current = following


def run_stage(conn, name: str, sql: str, timings: dict[str, float]) -> None:
    started = perf_counter()
    conn.execute(sql)
    conn.commit()
    timings[name] = round(perf_counter() - started, 3)
    print(f"{name}=PASS elapsed_s={timings[name]}", flush=True)


def counts(conn, schema: str) -> dict[str, int]:
    names = ("dim_date", "dim_region", "dim_product", "dim_customer", "fact_sales", "fact_payment", "golden_expected_result")
    return {name: conn.execute(f'SELECT count(*) FROM "{schema}".{name}').fetchone()[0] for name in names}


def data_signature(conn, schema: str, parameters: dict) -> tuple[str, dict]:
    sales = conn.execute(
        f'''SELECT count(*), min(order_date), max(order_date), count(DISTINCT tenant_id),
                   round(sum(net_amount)::numeric, 2), round(sum(refund_amount)::numeric, 2)
            FROM "{schema}".fact_sales'''
    ).fetchone()
    payments = conn.execute(
        f'''SELECT count(*), min(invoice_date), max(invoice_date),
                   round(sum(receivable_amount)::numeric, 2), round(sum(outstanding_amount)::numeric, 2)
            FROM "{schema}".fact_payment'''
    ).fetchone()
    facts = {"parameters": parameters, "sales": list(sales), "payments": list(payments)}
    return canonical_hash(facts), facts


def quality_checks(conn, schema: str) -> dict[str, int]:
    row = conn.execute(
        f'''SELECT
              count(*) - count(DISTINCT external_order_no) AS duplicate_external_order_rows,
              count(*) FILTER (WHERE net_amount = 0) AS zero_net_amount_rows,
              count(*) FILTER (WHERE discount_rate >= 0.95) AS extreme_discount_rows
            FROM "{schema}".fact_sales'''
    ).fetchone()
    null_payment_dates = conn.execute(
        f'SELECT count(*) FROM "{schema}".fact_payment WHERE payment_date IS NULL'
    ).fetchone()[0]
    return {
        "duplicate_external_order_rows": row[0],
        "zero_net_amount_rows": row[1],
        "extreme_discount_rows": row[2],
        "null_payment_date_rows": null_payment_dates,
    }


def explain_cases(conn, schema: str) -> list[dict]:
    queries = [
        ("simple_monthly", f'SELECT net_sales FROM "{schema}".agg_monthly_sales WHERE tenant_id=1 AND month_start=date \'2025-07-01\''),
        ("standard_region", f'''SELECT region_id, round(sum(net_amount-refund_amount)::numeric,2) AS value
            FROM "{schema}".fact_sales WHERE tenant_id=1 AND order_date>=date '2025-01-01' AND order_date<date '2026-01-01'
            GROUP BY region_id ORDER BY value DESC LIMIT 10'''),
        ("complex_product", f'''SELECT p.category, round(sum(f.net_amount-f.refund_amount)::numeric,2) AS value
            FROM "{schema}".fact_sales f JOIN "{schema}".dim_product p ON p.product_id=f.product_id
            WHERE f.tenant_id=1 AND f.order_date>=date '2025-01-01' AND f.order_date<date '2026-01-01'
            GROUP BY p.category ORDER BY value DESC'''),
        ("receivable_aging", f'''SELECT aging_bucket, sum(outstanding_amount) FROM "{schema}".agg_receivable_aging
            WHERE tenant_id=1 GROUP BY aging_bucket ORDER BY aging_bucket'''),
    ]
    results = []
    for name, query in queries:
        plan = conn.execute("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + query).fetchone()[0][0]
        results.append({"name": name, "query": query, "plan": plan})
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Build deterministic local PostgreSQL benchmark data without Docker volumes")
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--schema", default="chatbi_benchmark_v21")
    parser.add_argument("--scale", choices=tuple(SCALES), default="10M")
    parser.add_argument("--seed", type=int, default=20260818)
    parser.add_argument("--tenant-count", type=int, default=10)
    parser.add_argument("--reader-role", default="chatbi_reader")
    parser.add_argument("--date-start", type=date.fromisoformat, default=date(2024, 1, 1))
    parser.add_argument("--date-end", type=date.fromisoformat, default=date(2026, 12, 31))
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/v2_1_data10m"))
    parser.add_argument("--reset", action="store_true")
    parser.add_argument("--reuse-existing", action="store_true", help="Validate and finalize an already generated isolated benchmark schema")
    parser.add_argument("--skip-files", action="store_true")
    args = parser.parse_args()

    schema = validate_schema(args.schema)
    if not IDENTIFIER.fullmatch(args.reader_role):
        raise SystemExit("reader role must be a lowercase PostgreSQL identifier")
    scale = SCALES[args.scale]
    root = Path(__file__).resolve().parent
    args.output_dir.mkdir(parents=True, exist_ok=True)
    env = load_env(args.env_file)
    timings: dict[str, float] = {}
    parameters = {
        "schema": schema, "scale": args.scale, "seed": args.seed, "tenant_count": args.tenant_count,
        "date_start": args.date_start.isoformat(), "date_end": args.date_end.isoformat(), **scale,
    }
    values = {
        "schema": schema, "seed": args.seed, "tenant_count": args.tenant_count,
        "date_start": args.date_start.isoformat(), "date_end": args.date_end.isoformat(),
        "sales_count": scale["sales"], "payment_count": scale["payments"],
        "product_count": scale["products"], "customer_count": scale["customers"],
    }

    with connect(env) as conn:
        conn.execute("SET statement_timeout=0")
        conn.execute("SET lock_timeout='5s'")
        existing = conn.execute("SELECT to_regnamespace(%s)", (schema,)).fetchone()[0]
        if existing and not args.reset and not args.reuse_existing:
            raise SystemExit(f"Schema {schema} already exists. Use --reset only when replacing this isolated benchmark schema is intended.")
        if existing and args.reuse_existing:
            actual = counts(conn, schema)
            expected = {"fact_sales": scale["sales"], "fact_payment": scale["payments"], "dim_product": scale["products"], "dim_customer": scale["customers"]}
            mismatches = {name: {"expected": value, "actual": actual.get(name)} for name, value in expected.items() if actual.get(name) != value}
            if mismatches:
                raise SystemExit(f"Existing benchmark schema does not match requested parameters: {json.dumps(mismatches)}")
            timings["reuse_existing_validation"] = 0.0
            print("reuse_existing_validation=PASS", flush=True)
        else:
            if existing:
                run_stage(conn, "reset", render_template(root / "reset.sql", schema=schema), timings)
            run_stage(conn, "create_schema", render_template(root / "create_schema.sql", **values), timings)
            partition_sql = []
            for start, end in month_starts(args.date_start, args.date_end):
                suffix = start.strftime("%Y%m")
                partition_sql.append(
                    f'CREATE TABLE IF NOT EXISTS "{schema}".fact_sales_{suffix} PARTITION OF "{schema}".fact_sales '
                    f"FOR VALUES FROM ('{start.isoformat()}') TO ('{end.isoformat()}');"
                )
                partition_sql.append(
                    f'CREATE TABLE IF NOT EXISTS "{schema}".fact_payment_{suffix} PARTITION OF "{schema}".fact_payment '
                    f"FOR VALUES FROM ('{start.isoformat()}') TO ('{end.isoformat()}');"
                )
            run_stage(conn, "create_partitions", "\n".join(partition_sql), timings)
            run_stage(conn, "generate_dimensions", render_template(root / "generate_dimensions.sql", **values), timings)
            run_stage(conn, "generate_fact_sales", render_template(root / "generate_fact_sales.sql", **values), timings)
            run_stage(conn, "generate_fact_payment", render_template(root / "generate_fact_payment.sql", **values), timings)
            run_stage(conn, "create_indexes", render_template(root / "create_indexes.sql", **values), timings)
            run_stage(conn, "create_aggregates", render_template(root / "create_aggregates.sql", **values), timings)
            run_stage(conn, "analyze", render_template(root / "analyze.sql", **values), timings)
        signature, signature_facts = data_signature(conn, schema, parameters)
        cases = build_cases(conn, schema, signature, 100)
        conn.commit()
        run_stage(conn, "grant_readonly", render_template(root / "grant_readonly.sql", schema=schema, reader_role=args.reader_role), timings)
        actual_counts = counts(conn, schema)
        partitions = conn.execute(
            "SELECT count(*) FROM pg_inherits i JOIN pg_class c ON c.oid=i.inhparent JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=%s AND c.relname IN ('fact_sales','fact_payment')",
            (schema,),
        ).fetchone()[0]
        indexes = conn.execute("SELECT count(*) FROM pg_indexes WHERE schemaname=%s", (schema,)).fetchone()[0]
        explains = explain_cases(conn, schema)
        quality = quality_checks(conn, schema)

    atomic_json(args.output_dir / "ground_truth.json", {"count": len(cases), "data_signature": signature, "cases": cases})
    atomic_json(args.output_dir / "explain_analyze.json", explains)
    subprocess.run(
        [sys.executable, str(root / "generate_business_knowledge.py"),
         "--output", str(args.output_dir / "business_rules.md"), "--schema", schema,
         "--seed", str(args.seed), "--tenant-count", str(args.tenant_count),
         "--date-start", args.date_start.isoformat(), "--date-end", args.date_end.isoformat()],
        check=True,
    )
    file_manifest = None
    if not args.skip_files:
        subprocess.run(
            [sys.executable, str(root / "export_file_datasets.py"), "--env-file", str(args.env_file), "--schema", schema,
             "--output-dir", str(args.output_dir / "files"), "--data-signature", signature],
            check=True,
        )
        file_manifest = json.loads((args.output_dir / "files" / "file_datasets_manifest.json").read_text(encoding="utf-8"))

    manifest = {
        "manifest_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "parameters": parameters,
        "counts": actual_counts,
        "partition_count": partitions,
        "index_count": indexes,
        "data_signature": signature,
        "signature_facts": signature_facts,
        "ground_truth_count": len(cases),
        "quality_checks": quality,
        "timings_seconds": timings,
        "explain_cases": [{"name": item["name"], "execution_time_ms": item["plan"].get("Execution Time"), "planning_time_ms": item["plan"].get("Planning Time")} for item in explains],
        "file_datasets": file_manifest,
    }
    atomic_json(args.output_dir / "manifest.json", manifest)
    print(json.dumps({"status": "PASS", "counts": actual_counts, "data_signature": signature, "manifest": str(args.output_dir / "manifest.json")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
