# Reproducible 10M demonstration data

V1.1.0 validates the product against a business-shaped, deterministic local PostgreSQL dataset. It is synthetic demonstration data, not enterprise data; product screens use neutral wording and obtain every value through the Backend API.

| Property | Value |
| --- | --- |
| Primary source | local PostgreSQL |
| Compatibility source | local MySQL |
| PostgreSQL schema | `chatbi_benchmark_v21` |
| Fixed seed | `20260818` |
| Main fact rows | `fact_sales = 10,000,000` |
| Secondary fact rows | `fact_payment = 5,000,000` |
| Time partitioning | 72 partitions |
| Indexes | 345 |
| Pre-aggregations | 4 |
| Frozen data signature | `34b8ec8023f410ea387003475f84bd63b05743580138ea919880979caf86af4c` |
| Manifest | `docs/v2_1/day1/DATA_MANIFEST_10M.json` |

The generator models tenants, dates, regions, customers, products, channels, orders, gross/net/profit/refund amounts, payment timing, status, and deterministic edge cases. Frozen Golden expected values and result signatures are independent evaluation assets; runtime NL2SQL never reads them.

## Rebuild and verify

Use the repository's local-database bootstrap flow. Database administrator credentials are requested interactively for setup only and are not written, displayed, copied, or committed. Reset is explicit and limited to demonstration schemas:

```powershell
.\scripts\bootstrap-local-databases.ps1 -ResetDemoData
```

Do not use this option to reset the ChatBI metadata database. Docker Compose does not create database containers or database volumes.

The release gate verifies the manifest/signature, Golden 50 guarded execution and values, four query-latency tiers, read-only credentials, and a before/after business-table signature around the active attack set. HTTP 200 or executable SQL alone is not accepted as correctness evidence.
