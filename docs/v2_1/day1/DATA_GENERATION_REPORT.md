# Day 1 10M data generation report

- Executed: 2026-08-18T12:57:41.218149+00:00
- Git SHA: `650bb01`
- Scope: isolated local PostgreSQL schema `chatbi_benchmark_v21`; no Docker database container or volume.
- Raw evidence: `artifacts\v2_1_data10m\rebuild\manifest.json`, `artifacts\v2_1_data10m\final\manifest.json`, `artifacts\v2_1_data10m\final\explain_analyze.json`

## Commands

```text
python scripts/demo_db/generate_benchmark.py --scale 10M --seed 20260818 --tenant-count 10 --date-start 2024-01-01 --date-end 2026-12-31 --reset
python scripts/demo_db/migrate_external_order_no.py --sales-count 10000000
python scripts/demo_db/generate_benchmark.py --scale 10M --seed 20260818 --tenant-count 10 --date-start 2024-01-01 --date-end 2026-12-31 --reuse-existing
python scripts/demo_db/verify_manifest.py --manifest <final-manifest>
```

## Actual result

- Rows: dim_date=1096, dim_region=50, dim_product=50000, dim_customer=300000, fact_sales=10000000, fact_payment=5000000, ground_truth=100.
- Partition/index count: 72 / 345.
- Data signature: `34b8ec8023f410ea387003475f84bd63b05743580138ea919880979caf86af4c`; independent rebuild signature: `34b8ec8023f410ea387003475f84bd63b05743580138ea919880979caf86af4c`; stable=true.
- One-time isolated-schema quality migration including full VACUUM: 2952.059 seconds.
- Quality: duplicate external order rows=500000, zero net rows=112998, extreme discount rows=10129, NULL payment dates=294117.
- Pre-aggregations: monthly sales, region-product, customer contribution and receivable aging are materialized and indexed.
- File datasets: 5/5 generated and hash-verified.

## Engineering impact

- Frozen Zone intersection: none for data generator and data evidence files.
- Migration impact: no Alembic revision; reset is restricted to schema names beginning with `chatbi_benchmark`.
- License impact: project-owned generators and synthetic data only.
- Failures: none.
- Blockers: none.
- Rollback: disconnect the benchmark datasource and, only after explicit approval, drop the isolated benchmark schema; user schemas are never targeted.
