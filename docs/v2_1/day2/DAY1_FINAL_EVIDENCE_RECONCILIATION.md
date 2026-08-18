# Day 1 final evidence reconciliation

## Decision

`DAY1_FINAL_SHA=0e3ee1102eb50659011a3de725820bc437a5d461` is verified locally and on `origin/codex/v2.1-final-integration`. The Day 1 final gate was reproduced without changing runtime code.

```text
DAY1_FINAL_SHA_VERIFIED=YES
DAY1_FINAL_GATE_REPRODUCED=PASS
DAY1_EVIDENCE_SHA_ALIGNED=PASS
DAY1_RUNTIME_CODE_CHANGED=NO
DAY1_REGRESSION=0
```

The machine-readable seal is `artifacts/v2_1/day1-final-seal/0e3ee1102eb50659011a3de725820bc437a5d461/DAY1_FINAL_ATTESTATION.json`.

## Why the historical and final SHAs differ

The tracked `docs/v2_1/day1/DAY1_REPORT.md` identifies `57ab853bfa92bab6e76bcd24020b00903409a6bb` as its evidence SHA. Three later commits lead to the reported final SHA:

1. `0fdde57af73931eab0ab8d7cdbd2c914aa3a675d` integrated the generated Day 1 evidence and governance records.
2. `cef6fe9b13066dace6677d2995eaf8a879af9b23` corrected the Backend count from 173 to 174 in evidence and its publisher.
3. `0e3ee1102eb50659011a3de725820bc437a5d461` changed `backend/app/api/routes/analysis.py` and `backend/app/api/routes/chat.py` so each SSE stream emits exactly one terminal event.

The final commit is a runtime behavior change. Therefore the earlier report's performance values cannot be presented as if they were measured on `0e3ee110...`.

## Final-SHA evidence

The ignored raw evidence already present in the integration worktree identifies the final SHA and was hash-verified during D2-0. The final values are:

| Gate | Final-SHA actual | Result |
|---|---:|---|
| Semantic cases | 20/20 coverage; 20/20 Golden; 20/20 exactly one terminal event | PASS |
| Strict SSE | 138 requests; 0 errors; 138 completed terminal events | PASS |
| TTFE P95 | 266.015 ms | PASS |
| Heartbeat maximum gap | 963.485 ms | PASS |
| Cancel cleanup | 362.430 ms; connection/task leaks 0/0 | PASS |
| Non-vacuous long streaming | 34 real requests over 10 seconds; streaming rate 1.0 | PASS |
| Cold start | 57.8 seconds; isolated metadata cleanup PASS | PASS |
| Backend | 174/174, including migration round trip | PASS |
| Frontend | 29/29; TypeScript PASS; build 734 modules | PASS |
| Browser E2E | 55/55, single worker | PASS |
| Phase 2 runtime | route/trace 60/60; follow-up 10/10; citation accuracy 1.0 | PASS |
| Migration | single head `20260818_0009`; upgrade -> base -> upgrade | PASS |

The strict and long profiles are intentionally separate: the strict profile proves the latency/heartbeat thresholds, while the 60-concurrency profile supplies 34 real requests over 10 seconds. The latter is not used to claim the strict TTFE threshold.

## Reverification observations

Running Backend and Frontend tests concurrently caused five Frontend 5-second timeouts and one event-input assertion failure. The unchanged tree passed Frontend 29/29 when rerun alone, so the failed parallel attempt is retained as a transient resource-contention observation rather than hidden.

The first current Phase 2 acceptance run occurred after the Backend migration suite had left `rag-runtime` in `Created` state. It correctly degraded five knowledge/hybrid requests to PARTIAL with zero citations. Starting the declared Compose services and rerunning the same unchanged SHA restored citation accuracy to 1.0 and cited count to 7. This confirms both fail-closed behavior and the required fully running release topology.

## Day 1 A/B limitation

`docs/v2_1/day1/DAY1_AB_RESULT.json` reports `baseline_sql_executable_rate=0.0` because all 20 baseline cases were rejected with `TABLE_NOT_AUTHORIZED`. That comparison is useful evidence that the new 10M dataset became authorized and reachable, but it is not a valid same-authorization, same-data business-accuracy A/B.

Day 3 must repeat the A/B with the same authorized datasource, semantic model, dataset and question set. The historical baseline result must not be relabeled as that future comparison.

## Scope and rollback

D2-0 changed evidence only. No tracked Backend, Frontend, migration, runtime configuration or test code was modified. If the seal is rejected, remove the Day 2 evidence commit only; do not move the Phase 2 protection branch or rewrite Day 1 history.
