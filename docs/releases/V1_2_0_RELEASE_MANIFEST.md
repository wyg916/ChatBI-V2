# ChatBI V2 V1.2.0 Release Manifest

## Identity

| Field | Value |
| --- | --- |
| VERSION | `V1.2.0` |
| TAG | `chatbi-v2-v1.2.0` |
| RELEASE_SHA | resolved by `git rev-parse chatbi-v2-v1.2.0^{}` |
| MAIN_SHA | must equal `RELEASE_SHA` after push |
| PRE_RELEASE_MAIN_SHA | `094c81aaaba44ced62fec7f0b97cc73f217d5975` |
| INTEGRATION_SHA | `5303bdb687ffe4c3896292b333edb58ed4003d6c` |
| MERGE_MODE | `FAST_FORWARD_ONLY` |
| RELEASE_TIME | `2026-08-20T16:00:41+08:00` |
| EVIDENCE_PATH | `artifacts/chat-ui-optimization-20260819/final-integration/` and `docs/releases/V1_2_0_EVIDENCE_MANIFEST.json` |

The tracked manifest cannot contain the hash of the commit that contains itself. The annotated Tag peeled SHA is the authoritative immutable release identity; the delivery record must prove `local main = tracking main = ls-remote main = tag peeled SHA`.

## Release gates

| Gate | Required and frozen result |
| --- | --- |
| BUILD_RESULT | `PASS` — Frontend production build, 741 modules |
| TEST_RESULT | `PASS` — Frontend 50/50 and Backend 223/223 |
| PLAYWRIGHT_RESULT | `PASS` — 82/82, one worker, retries disabled as a substitute for correctness |
| BACKEND_RESULT | `PASS` — 223/223 plus Python compile check |
| FRONTEND_RESULT | `PASS` — typecheck, 13/13 files and 50/50 Vitest, production build |
| DOCKER_RESULT | `PASS` — stopped-state official stack start and three services healthy |
| BROWSER_RESULT | `PASS` — console/page/request/unexpected blocking 4xx/5xx all 0 |
| SECRET_SCAN | `PASS` — no high-confidence secret, Cookie, trace or auth payload in release tree |
| WORKTREE | `clean`, stash `0`, main ahead/behind `0/0` after push |

Any mismatch between these frozen results and the final release run blocks Tag creation or requires a new release commit followed by a complete retest.

## Runtime and data boundary

- Frontend, Backend and RAG Runtime are the only Compose services.
- Metadata and primary demonstration data remain in user-local PostgreSQL; MySQL remains the compatibility data source.
- Frontend uses Backend API only. Database and model credentials remain outside Git and browser storage.
- No V1.2.0 database migration is introduced; Alembic remains at the existing single head.

## Included release evidence

- `docs/releases/V1_2_0_RELEASE_NOTES.md`
- `docs/releases/V1_2_0_ROLLBACK_MANIFEST.md`
- `docs/releases/V1_2_0_EVIDENCE_MANIFEST.json`
- `docs/releases/V1_2_0_FINAL_RELEASE_REPORT.md`
- `docs/sbom/V1_2_0.cdx.json`
- `docs/sbom/V1_2_0.spdx.json`
- `artifacts/chat-ui-optimization-20260819/final-integration/`
- `docs/chat-ui-optimization-20260819/FINAL_INTEGRATION_REPORT.md`
