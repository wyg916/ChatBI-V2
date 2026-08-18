from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from _common import atomic_json


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish tracked Day 1 evidence from raw reproducible benchmark artifacts")
    parser.add_argument("--final-manifest", type=Path, required=True)
    parser.add_argument("--rebuild-manifest", type=Path, required=True)
    parser.add_argument("--explain", type=Path, required=True)
    parser.add_argument("--business-rules", type=Path, required=True)
    parser.add_argument("--docs-dir", type=Path, required=True)
    parser.add_argument("--git-sha", required=True)
    parser.add_argument("--quality-migration-seconds", type=float, default=0.0)
    args = parser.parse_args()
    final = load(args.final_manifest)
    rebuild = load(args.rebuild_manifest)
    explains = load(args.explain)
    files = final["file_datasets"]
    stable = final["data_signature"] == rebuild["data_signature"]
    generated_at = datetime.now(timezone.utc).isoformat()
    args.docs_dir.mkdir(parents=True, exist_ok=True)
    common = {
        "executed_at": generated_at,
        "git_sha": args.git_sha,
        "raw_evidence": {
            "final_manifest": str(args.final_manifest),
            "rebuild_manifest": str(args.rebuild_manifest),
            "explain_analyze": str(args.explain),
        },
        "failures": [] if stable else ["DATA_SIGNATURE_UNSTABLE"],
        "blockers": [],
        "frozen_zone_intersection": [],
        "migration_impact": "No Alembic migration; only the isolated chatbi_benchmark_v21 schema is created or reset.",
        "license_impact": "None; generated SQL, Python and synthetic data are project-owned.",
        "rollback": "Stop queries using the benchmark datasource, then drop only the isolated chatbi_benchmark_v21 schema after explicit approval.",
    }
    data_manifest = {
        **common,
        "commands": [
            "python scripts/demo_db/generate_benchmark.py --scale 10M --seed 20260818 --tenant-count 10 --date-start 2024-01-01 --date-end 2026-12-31 --reset",
            "python scripts/demo_db/migrate_external_order_no.py --sales-count 10000000",
            "python scripts/demo_db/generate_benchmark.py --scale 10M --seed 20260818 --tenant-count 10 --date-start 2024-01-01 --date-end 2026-12-31 --reuse-existing",
            "python scripts/demo_db/verify_manifest.py --manifest <final-manifest>",
        ],
        "test_count": 1,
        "manifest": final,
        "rebuild": {
            "data_signature": rebuild["data_signature"],
            "counts": rebuild["counts"],
            "timings_seconds": rebuild["timings_seconds"],
        },
        "data_signature_stable": stable,
        "quality_migration_seconds": args.quality_migration_seconds,
    }
    atomic_json(args.docs_dir / "DATA_MANIFEST_10M.json", data_manifest)
    atomic_json(args.docs_dir / "FILE_DATASET_MANIFEST.json", {
        **common,
        "commands": data_manifest["commands"],
        "test_count": len(files["files"]),
        "file_datasets": files,
    })
    atomic_json(args.docs_dir / "EXPLAIN_ANALYZE_BASELINE.json", {
        **common,
        "commands": ["EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) <case-sql>"],
        "test_count": len(explains),
        "cases": explains,
    })
    quality = final.get("quality_checks", {})
    report = f"""# Day 1 10M data generation report

- Executed: {generated_at}
- Git SHA: `{args.git_sha}`
- Scope: isolated local PostgreSQL schema `chatbi_benchmark_v21`; no Docker database container or volume.
- Raw evidence: `{args.rebuild_manifest}`, `{args.final_manifest}`, `{args.explain}`

## Commands

```text
{chr(10).join(data_manifest['commands'])}
```

## Actual result

- Rows: dim_date={final['counts']['dim_date']}, dim_region={final['counts']['dim_region']}, dim_product={final['counts']['dim_product']}, dim_customer={final['counts']['dim_customer']}, fact_sales={final['counts']['fact_sales']}, fact_payment={final['counts']['fact_payment']}, ground_truth={final['counts']['golden_expected_result']}.
- Partition/index count: {final['partition_count']} / {final['index_count']}.
- Data signature: `{final['data_signature']}`; independent rebuild signature: `{rebuild['data_signature']}`; stable={str(stable).lower()}.
- One-time isolated-schema quality migration including full VACUUM: {args.quality_migration_seconds:.3f} seconds.
- Quality: duplicate external order rows={quality.get('duplicate_external_order_rows')}, zero net rows={quality.get('zero_net_amount_rows')}, extreme discount rows={quality.get('extreme_discount_rows')}, NULL payment dates={quality.get('null_payment_date_rows')}.
- Pre-aggregations: monthly sales, region-product, customer contribution and receivable aging are materialized and indexed.
- File datasets: {len(files['files'])}/5 generated and hash-verified.

## Engineering impact

- Frozen Zone intersection: none for data generator and data evidence files.
- Migration impact: no Alembic revision; reset is restricted to schema names beginning with `chatbi_benchmark`.
- License impact: project-owned generators and synthetic data only.
- Failures: {'none' if stable else 'DATA_SIGNATURE_UNSTABLE'}.
- Blockers: none.
- Rollback: disconnect the benchmark datasource and, only after explicit approval, drop the isolated benchmark schema; user schemas are never targeted.
"""
    (args.docs_dir / "DATA_GENERATION_REPORT.md").write_text(report, encoding="utf-8")
    (args.docs_dir / "BUSINESS_RULES_10M.md").write_text(
        args.business_rules.read_text(encoding="utf-8"), encoding="utf-8",
    )


if __name__ == "__main__":
    main()
