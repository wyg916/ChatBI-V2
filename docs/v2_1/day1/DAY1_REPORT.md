# ChatBI V2 v2.1 Day 1 final report

## Result

- Executed at: `2026-08-18T13:52:14.717724+00:00`
- Evidence Git SHA: `57ab853bfa92bab6e76bcd24020b00903409a6bb`
- Scope: Day 1 E + A only; B was not merged, and Day 2/3 were not executed.
- Status: `PASS`
- Failures: `NONE`; blockers: `NONE`.

## Gates

| Gate | Actual | Result |
|---|---|---|
| 10M data | sales 10,000,000; payment 5,000,000; product 50,000; customer 300,000; Golden 100; signature `34b8ec8023f410ea387003475f84bd63b05743580138ea919880979caf86af4c` | PASS |
| Streaming | SSE 1.0; TTFE p95 213.104 ms; heartbeat 2508.131 ms; cancel 250.802 ms; >10s 1.0 on 26 samples; leak 0 | PASS |
| Wren runtime | call 1.0; mapping 1.0; Golden 1.0 | PASS |
| OpenChatBI linking | call 1.0; Recall@5 1.0; p95 7.476 ms; cross-workspace/unauthorized recall 0/0 | PASS |
| SuperSonic pipeline | call 1.0; metric/dimension/time/filter 1.0/1.0/1.0/1.0; invalid relation 1.0 | PASS |
| No regression | Backend 174; Frontend 29; E2E 55; Phase 2 runtime 60; console/page/blocking request 0/0/0 | PASS |

## Execution evidence

- Commands and test counts: `docs/v2_1/day1/DAY1_TEST_SUMMARY.json`.
- Raw evidence paths: `temp/day1/final-performance-strict.json, temp/day1/final-performance-over10-c60.json, temp/day1/final-semantic-cases.json, temp/day1/phase2-runtime-acceptance.json, temp/day1/cold-start.json`.
- Semantic cases: 20/20 coverage, 20/20 Golden, and 20/20 cases with complete real SSE event captures.
- Docker: image build PASS; two consecutive starts from stopped state PASS; no database container or Docker database volume.
- Migration: single head `20260818_0009`; upgrade -> rollback -> upgrade PASS.
- Cold start: PASS in 76.8 seconds; temporary metadata schema cleanup PASS.
- One-click start: PASS; protected API anonymous checks 5/5 returned 401.
- Upstream/license: eight pinned projects in `docs/UPSTREAM_LOCK.json`; draft audit present; semantic adapters are clean-room and copy no upstream source or brand assets.
- Secret scan: no tracked `.env`, private-key file, provider token pattern, or literal credential assignment was found.

## Frozen Zone

- Intersection count: 16.
- Files: `.env.example, backend/app/api/routes/analysis.py, backend/app/api/routes/chat.py, backend/app/core/config.py, backend/app/query/oracle.py, backend/app/query/service.py, backend/app/semantic/engine.py, backend/app/services/chat.py, backend/scripts/phase2_runtime_acceptance.py, backend/tests/test_phase2_auth_chat_attachments.py, docker-compose.yml, frontend/e2e/day3-product-loop.spec.ts, frontend/e2e/day5-rag-multiagent.spec.ts, frontend/e2e/global-setup.ts, frontend/src/api/chat.ts, frontend/src/pages/AskExperience.tsx`.
- Reason: minimal SSE lifecycle integration, default semantic chain, Result Oracle time binding, evidence CLI, deterministic multi-datasource E2E fixture selection, and UI query evidence.
- Merge method: both feature branches were based on Phase 2 and merged by commit chain; no `checkout --theirs`, bulk incoming replacement, or frozen blob overwrite was used.
- Frozen blob overwrite count: `0`.

## Rollback and deferral

- Semantic rollback: set `CHATBI_SEMANTIC_RUNTIME_MODE=local` and restart Backend.
- SSE/data rollback: revert only the Day 1 integration commits; no Alembic downgrade is required. The isolated benchmark schema can be removed only after explicit approval.
- Deferred by scope: B integration and all Day 2 work; Day 3 final 20-concurrent/15-minute stress, full attack set, Final Manifest, release and Tag.
