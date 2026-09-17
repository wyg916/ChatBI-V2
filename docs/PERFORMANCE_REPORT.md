# ChatBI V2 V1.1.0 performance report

## Verdict and evidence rule

The pre-freeze formal gate passes on the current release worktree. The authoritative pre-freeze artifact is `artifacts/v2_1/day3/performance/performance-full-15m-v8.json` with its companion CSV. It records `release_gate.enforced=true`, `release_gate.pass=true`, and no failures after a real 20-concurrent, 908.812-second mixed load. This tracked report is not a substitute for the required same-SHA final rerun under `artifacts/v2_1/final/<FINAL_CANDIDATE_SHA>/performance.json`.

## Workload

- Two authenticated users in two independent Workspaces; 20 simultaneous clients.
- Mixed `DATA_QUERY`, `KNOWLEDGE_QUERY`, `HYBRID_ANALYSIS`, `COMPLEX_ANALYSIS`, `FILE_QUERY`, `SQL_WORKSPACE`, `FEEDBACK`, and `EVALUATION` traffic.
- Real SSE, slow readers, 140 deliberate disconnect attempts, cancellation, cache hit/miss, governed RAG, bounded Agent and fixed-operation file analysis.
- The release Backend uses one joined token/user/conversation authorization read, a reusable synchronous SSE queue, six bounded CPU/DB-heavy business workers, 0.5-second idle heartbeat, 30-second HTTP keep-alive, and no authentication-result cache.
- Database microbenchmarks execute against the reproducible local PostgreSQL 10M business dataset; Docker Compose contains no database service or database volume.

## BEFORE / AFTER / DIFF

The initial full v2 load is the load/resource baseline. The first artifact with complete public stage aliases is v3, so stage-level BEFORE values use v3 and are labelled accordingly; they are not presented as if they came from v2.

### Load and lifecycle (v2 → v8)

| Metric | BEFORE v2 | AFTER v8 | DIFF | Gate |
| --- | ---: | ---: | ---: | --- |
| Requests / successes / errors | 4151 / 4151 / 0 | 3763 / 3763 / 0 | -388 requests; errors unchanged | error rate < 0.01 |
| Overall p50 / p95 / p99 (ms) | 3483.653 / 10486.613 / 12675.229 | 4774.865 / 10592.950 / 12163.119 | +1291.212 / +106.337 / -512.110 | recorded, no release threshold |
| TTFE p50 (ms) | 688.673 | 171.932 | -516.741 | recorded |
| TTFE p95 (ms) | 1442.719 | 676.301 | -766.418 (-53.1%) | ≤ 1000: PASS |
| Heartbeat max gap (ms) | 2634.340 | 2056.274 | -578.066 | ≤ 3000: PASS |
| >10s requests / streaming rate | 273 / 1.0 | 289 / 1.0 | +16 / unchanged | 1.0: PASS |
| Cancel cleanup (ms) | 299.338 | 241.300 | -58.038 | ≤ 5000: PASS |
| CPU p95 (%) | 165.090 | 169.700 | +4.610 | recorded; multi-core percentage |
| Backend RSS first / final / growth (MiB) | 698.315 / 877.525 / 179.210 | 476.105 / 498.865 / 22.760 | growth -156.450 | no sustained growth: PASS |
| Memory leak flag | 1 | 0 | fixed | 0: PASS |

Six business workers intentionally trade some aggregate throughput and queued route duration for bounded dual-core CPU contention, fast acknowledgement, reliable heartbeat and stable RSS. Correctness, completion and error gates remain unchanged; no route is disabled or moved to shadow mode.

### Stage p95 (v3 → v8)

| Stage | BEFORE v3 p95 ms | AFTER v8 p95 ms | DIFF ms | Gate/result |
| --- | ---: | ---: | ---: | --- |
| Catalog | 16.228 | 3.569 | -12.659 | ≤1000 PASS |
| Schema Linking | 16.228 | 3.569 | -12.659 | measured |
| Semantic Parse | 0.751 | 0.363 | -0.388 | ≤1500 PASS |
| Wren Compile | 6.399 | 1.246 | -5.153 | ≤2000 PASS |
| SQL | 2246.000 | 962.000 | -1284.000 | measured |
| Oracle | 0.321 | 0.279 | -0.042 | sampled and present |
| RAG route | 7083.955 | 9948.164 | +2864.209 | measured; bounded queue tradeoff |
| Agent route | 14286.857 | 12034.453 | -2252.404 | measured |
| Python/File route | 5501.284 | 9473.329 | +3972.045 | measured; bounded queue tradeoff |
| SSE TTFE | 1375.868 | 676.301 | -699.567 | ≤1000 PASS |

RAG and file route p95 include end-to-end queue and product work, not only the internal retrieval or DataFrame operation. Their increases are reported rather than hidden; every request still completed and long requests retained a 1.0 streaming rate.

### PostgreSQL 10M query tiers (v2 → v8)

| Tier | BEFORE v2 p95 ms | AFTER v8 p50 / p95 / p99 ms | DIFF p95 ms | Gate |
| --- | ---: | ---: | ---: | --- |
| Simple | 0.270 | 0.151 / 0.263 / 0.402 | -0.007 | ≤5000 PASS |
| Standard | 372.550 | 320.322 / 419.760 / 439.330 | +47.210 | ≤10000 PASS |
| Complex | 520.116 | 498.167 / 912.752 / 918.676 | +392.636 | ≤30000 PASS |
| Advanced | 0.453 | 0.282 / 0.519 / 0.529 | +0.066 | ≤60000 PASS |

## Formal v8 results

| Area | Actual result | Verdict |
| --- | --- | --- |
| Duration and concurrency | 20 concurrent; 908.812 seconds | PASS |
| Requests | 3763 success, 0 error; rate 0.0 | PASS |
| SSE protocol | accepted rate 1.0; completed rate 1.0; envelope errors 0 | PASS |
| Routes | 466–474 requests in every required route | PASS |
| Cache | 1414 hits, 4 misses; Workspace-scoped leak 0 | PASS |
| Deliberate disconnect | 140 attempts, 140 accepted disconnects, 0 failures | PASS |
| Cancellation | 241.300ms; active connection/task/Agent/Sandbox counters all 0 | PASS |
| Connection state | DB 26→26, active 1→1; DB leak 0 | PASS |
| Runtime state | active SSE max 20; active Agent max 5; Sandbox observed by total counter; final counters 0 | PASS |
| Resource leaks | memory, DB, SSE, background task and cross-Workspace cache leak flags all 0 | PASS |
| Anonymous boundary | valid anonymous SSE request returned 401 | PASS |

## Iteration record

- v2 failed TTFE and memory growth; v3 removed the leak but still failed TTFE.
- v4 failed TTFE, heartbeat and protocol; v5 reduced latency but still failed TTFE.
- v6 was aborted when Backend and RAG Runtime were externally replaced during the run; no partial result is accepted.
- v7 completed but failed TTFE, heartbeat and >10-second streaming coverage.
- The subsequent async-body worker reductions improved TTFE but did not make heartbeat tail latency repeatable. The final synchronous reusable stream queue, six-worker business pool and 30-second keep-alive produced v8 PASS.

Raw failures and smoke artifacts remain locally under `artifacts/v2_1/day3/performance/`; none is rewritten as PASS. The frozen Final Candidate must rerun the enforced v8 command on the exact pushed SHA.
