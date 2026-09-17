# SSE performance baseline — Day 1 final integration

- Executed at: `2026-08-18T13:52:14.717724+00:00`
- Evidence Git SHA: `57ab853bfa92bab6e76bcd24020b00903409a6bb`
- Strict command: `python scripts/performance/run_v21_performance.py --env-file <local-env> --base-url http://127.0.0.1:8000/api/v1 --concurrency 4 --duration-minutes 0.5 --db-repeats 3`
- Long-request command: same runner with `--concurrency 60 --duration-minutes 0.2 --db-repeats 1`; this is a short non-vacuous Day 1 observation, not the Day 3 15-minute stress gate.
- Raw evidence: `temp/day1/final-performance-strict.json`, `temp/day1/final-performance-over10-c60.json`
- Test count: `106` strict requests plus `26` real requests longer than 10 seconds.

| Metric | Actual | Gate | Result |
|---|---:|---:|---|
| All-query SSE rate | 1.0 | 1.0 | PASS |
| TTFE p50 | 50.573 ms | evidence | PASS |
| TTFE p95 | 213.104 ms | <= 1000 ms | PASS |
| Heartbeat max gap | 2508.131 ms | <= 3000 ms | PASS |
| Cancellation cleanup | 250.802 ms | <= 5000 ms | PASS |
| Over-10s streaming | 1.0 (26 samples) | 1.0, non-empty | PASS |
| Connection / task leak | 0 / 0 | 0 / 0 | PASS |
| Anonymous SSE | 401 | 401 | PASS |

- Failures: `NONE`; blockers: `NONE`.
- Frozen Zone intersections: `.env.example, backend/app/api/routes/analysis.py, backend/app/api/routes/chat.py, backend/app/core/config.py, backend/app/query/oracle.py, backend/app/query/service.py, backend/app/semantic/engine.py, backend/app/services/chat.py, backend/scripts/phase2_runtime_acceptance.py, backend/tests/test_phase2_auth_chat_attachments.py, docker-compose.yml, frontend/e2e/day3-product-loop.spec.ts, frontend/e2e/day5-rag-multiagent.spec.ts, frontend/e2e/global-setup.ts, frontend/src/api/chat.ts, frontend/src/pages/AskExperience.tsx`.
- Migration impact: no new revision; online round trip returned to `20260818_0009`.
- License impact: project-owned SSE implementation.
- Rollback: revert the Day 1 SSE integration commits; no migration is required.
