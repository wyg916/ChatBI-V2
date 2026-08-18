# SSE performance baseline — Day 1

- Executed: 2026-08-18 18:31:20 +08:00
- Base SHA: `6cdbf12f6c2e8494afe21262fd092795c4f784c3` plus the E worktree changes under test
- Profile: four authenticated workers, all four question routes, 30 seconds, real Docker Backend API
- Raw evidence: `artifacts/v2_1_data10m/day1_sse_baseline.json`

| Metric | Actual | Gate | Result |
|---|---:|---:|---|
| Requests / errors | 91 / 0 | errors = 0 | PASS |
| All-query SSE rate | 1.0 | 1.0 | PASS |
| TTFE p50 | 35.325 ms | evidence | PASS |
| TTFE p95 | 398.739 ms | <= 1000 ms | PASS |
| Heartbeat max gap | 2502.979 ms | <= 3000 ms | PASS |
| Cancellation cleanup | 264.684 ms | <= 5000 ms | PASS |
| Connection leak | 0 | 0 | PASS |
| Task leak | 0 | 0 | PASS |
| Anonymous SSE | 401 | 401 | PASS |
| Envelope errors | 0 | 0 | PASS |

This acceptance profile did not naturally contain a request longer than ten seconds. The over-10-second rate is therefore not claimed from this run; a separate contention profile must contain at least one real >10s request on the final integration SHA before the final Gate can pass.

Database performance from the same command: simple p95 0.294 ms, standard p95 298.972 ms, complex p95 505.687 ms, advanced/pre-aggregated receivable p95 0.541 ms.

Known warning: the earlier 20-worker stress observation had TTFE p95 and heartbeat gaps above the Day 1 acceptance thresholds. It remains stress evidence only and is not used as the acceptance profile. The final SHA must rerun both the strict acceptance profile and a separate long-request streaming observation.
