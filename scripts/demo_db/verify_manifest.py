from __future__ import annotations

import argparse
import json
from pathlib import Path

from _common import connect, file_hash, load_env, validate_schema


MINIMUMS = {
    "dim_date": 1_095,
    "dim_region": 50,
    "dim_product": 50_000,
    "dim_customer": 300_000,
    "fact_sales": 10_000_000,
    "fact_payment": 5_000_000,
    "golden_expected_result": 100,
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    schema = validate_schema(manifest["parameters"]["schema"])
    failures = []
    with connect(load_env(args.env_file)) as conn:
        for table, minimum in MINIMUMS.items():
            actual = conn.execute(f'SELECT count(*) FROM "{schema}".{table}').fetchone()[0]
            if actual < minimum:
                failures.append(f"{table}={actual}<{minimum}")
            if manifest["counts"].get(table) != actual:
                failures.append(f"{table} manifest={manifest['counts'].get(table)} database={actual}")
        partition_count = conn.execute(
            "SELECT count(*) FROM pg_inherits i JOIN pg_class c ON c.oid=i.inhparent JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=%s AND c.relname IN ('fact_sales','fact_payment')",
            (schema,),
        ).fetchone()[0]
        if partition_count < 72 or partition_count != manifest.get("partition_count"):
            failures.append(f"partition_count manifest={manifest.get('partition_count')} database={partition_count}")
        index_count = conn.execute("SELECT count(*) FROM pg_indexes WHERE schemaname=%s", (schema,)).fetchone()[0]
        if index_count < 300 or index_count != manifest.get("index_count"):
            failures.append(f"index_count manifest={manifest.get('index_count')} database={index_count}")
        aggregate_count = conn.execute("SELECT count(*) FROM pg_matviews WHERE schemaname=%s", (schema,)).fetchone()[0]
        if aggregate_count != 4:
            failures.append(f"pre_aggregation_count={aggregate_count} expected=4")
        statistics_count = conn.execute("SELECT count(*) FROM pg_statistic_ext s JOIN pg_namespace n ON n.oid=s.stxnamespace WHERE n.nspname=%s", (schema,)).fetchone()[0]
        if statistics_count < 2:
            failures.append(f"extended_statistics_count={statistics_count}<2")
        observed_quality = {
            "duplicate_external_order_rows": conn.execute(f'SELECT count(*) - count(DISTINCT external_order_no) FROM "{schema}".fact_sales').fetchone()[0],
            "zero_net_amount_rows": conn.execute(f'SELECT count(*) FROM "{schema}".fact_sales WHERE net_amount=0').fetchone()[0],
            "extreme_discount_rows": conn.execute(f'SELECT count(*) FROM "{schema}".fact_sales WHERE discount_rate>=0.95').fetchone()[0],
            "null_payment_date_rows": conn.execute(f'SELECT count(*) FROM "{schema}".fact_payment WHERE payment_date IS NULL').fetchone()[0],
        }
        if any(value <= 0 for value in observed_quality.values()):
            failures.append(f"quality boundary missing: {observed_quality}")
        if manifest.get("quality_checks") != observed_quality:
            failures.append(f"quality manifest={manifest.get('quality_checks')} database={observed_quality}")
    file_manifest = manifest.get("file_datasets") or {}
    for name, metadata in (file_manifest.get("files") or {}).items():
        path = args.manifest.parent / "files" / name
        if not path.exists():
            failures.append(f"missing file {name}")
        elif file_hash(path) != metadata["sha256"]:
            failures.append(f"hash mismatch {name}")
    if not (args.manifest.parent / "business_rules.md").exists():
        failures.append("missing generated business_rules.md")
    if failures:
        print(json.dumps({"status": "FAIL", "failures": failures}, ensure_ascii=False, indent=2))
        raise SystemExit(1)
    print(json.dumps({"status": "PASS", "schema": schema, "data_signature": manifest["data_signature"], "counts": manifest["counts"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
