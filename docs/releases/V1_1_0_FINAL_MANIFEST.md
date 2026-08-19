# ChatBI V2 V1.1.0 final candidate manifest

## Identity and release rule

| Field | Value |
| --- | --- |
| Product | ChatBI V2 / ChatBI Core |
| Version | `1.1.0` |
| Integration branch | `codex/v2.1-final-integration` |
| Day 2 baseline | `e26dae042fecdf45f704c3975d5f2b96ef8bd3b8` |
| Final Candidate SHA | resolved by `git rev-parse HEAD` after this manifest is committed |
| Raw evidence root | `artifacts/v2_1/final/<FINAL_CANDIDATE_SHA>/` |
| Main/tag authority | not granted by this manifest; requires explicit owner authorization after all final gates pass |
| Intended tag | `chatbi-v2-v1.1.0` pointing exactly at the Final Candidate SHA |

The tracked manifest deliberately does not predeclare a SHA that includes itself. After all tracked code, migrations, configuration and documents are committed and pushed, the SHA is frozen; no tracked file may change. `FINAL_EVIDENCE_MANIFEST.json` then records the tested SHA, remote SHA, commands, timestamps, counts, metrics, hashes, failures and blockers. A different-SHA or missing final retest blocks release.

## Runtime manifest

| Runtime | Deployment | Required release state |
| --- | --- | --- |
| Frontend | `frontend` container | healthy; protected routes require login |
| Backend | `backend` container | healthy; migration head applied |
| RAG Runtime | `rag-runtime` container | healthy; HMAC/ACL/citation path active |
| Agent Runtime | in-process bounded Backend runtime | active for allowed complex routes; five roles/six tools/hard budgets |
| File Sandbox | in-process non-executable fixed-operation runtime | active; no shell/code/network/secret surface |
| Metadata/primary business DB | user-local PostgreSQL | no Docker database container/volume |
| Compatibility DB | user-local MySQL | no Docker database container/volume |

## Shipped capability and data assets

- Unified 12-route Chat runtime, persistent conversations, bounded short-term memory, full-chain SSE/cancellation, authentication/RBAC/ACL/audit, attachment/document/image/multimodal analysis.
- Default semantic path: OpenChatBI-compatible → SuperSonic-compatible → Wren-compatible → SQLGlot → read-only executor → Result Oracle → IBM-compatible evidence.
- Governed Live RAG and bounded five-role/six-tool analysis; Data Workspace; Feedback/Verified SQL; Evaluation Center.
- Fixed-seed `20260818` PostgreSQL dataset with 10M `fact_sales` rows and frozen signature `34b8ec8023f410ea387003475f84bd63b05743580138ea919880979caf86af4c`.
- Final Open Question 100, Memory 30×5, Golden 50, Knowledge 20, Agent 15, File 10, 56 dangerous-SQL cases, 50+ product E2E.

## Required tracked evidence

- `docs/v2_1/day3/V2_1_FINAL_CAPABILITY_AUDIT.md`
- `docs/v2_1/day3/V2_1_FINAL_CAPABILITY_MATRIX.json`
- `docs/CAPABILITY_EVIDENCE_MANIFEST.json`
- `docs/PERFORMANCE_REPORT.md`
- `docs/SECURITY_REPORT.md`
- `docs/OPEN_SOURCE_LICENSE_AUDIT.md`
- `docs/sbom/V1_1_0.cdx.json`
- `docs/sbom/V1_1_0.spdx.json`
- `docs/releases/V1_1_0_RELEASE_NOTES.md`
- `docs/releases/V1_1_0_ROLLBACK.md`

## Final gate commands

The final-SHA runner records exact commands and exit codes; the required scope includes full Backend pytest, frontend typecheck/Vitest/build, all Playwright E2E, Golden/runtime acceptance, security attacks, migration head and upgrade/rollback/upgrade, 20×15-minute load, two stopped-state Compose starts, clean worktree and three-way local/origin/ls-remote equality.

`HTTP 200`, code presence, historical PASS, demo/shadow/unit-only evidence, and separately tested SHAs never satisfy this manifest.
