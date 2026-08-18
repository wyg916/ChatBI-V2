# Day 1 alignment read-only audit

Audit time: 2026-08-18 (Asia/Shanghai)

Audit base: `cceeb1c598f633d68c6428907db82b2f7903b5e2`

Phase 2 protected SHA: `6cdbf12f6c2e8494afe21262fd092795c4f784c3`

Classification: P0 release preparation; read-only inspection of Day 1; **not a Day 1 or product PASS**.

## Executive result

`DAY1_ALIGNMENT_STATUS=IN_PROGRESS_WITH_EVIDENCE_AND_HIGH_CONFLICT_RISK`

No `DAY1_FINAL_SHA` exists. Both observed Day 1 worktrees are based on the Phase 2 SHA and contain uncommitted changes. The audit therefore uses only the allowed states `NOT_STARTED`, `IN_PROGRESS`, `EVIDENCE_PRESENT`, `READY_FOR_FINAL_GATE`, `RISK`, and `UNKNOWN`; it does not claim PASS.

The named v2.1 three-day master-plan document was not present in this checkout or the supplied attachment. Mapping below is based on the task contract, `AGENTS.md`, the Phase 2 frozen baseline, integration policy, repository architecture/acceptance documents, and observable Day 1 files. This missing source is an evidence gap that must be closed before the final alignment gate.

## Git and worktree facts

| Item | Observed fact |
|---|---|
| Final Integration at audit start | `codex/v2.1-final-integration` at `cceeb1c598f633d68c6428907db82b2f7903b5e2`, clean |
| Audit branch/base | `codex/v2.1-day2-readonly-preaudit` / `cceeb1c598f633d68c6428907db82b2f7903b5e2` |
| Day 1 E/data/SSE worktree | `codex/v2.1-data10m-performance`, HEAD `6cdbf12...`, 32 changed/untracked paths, 5 frozen intersections |
| Day 1 A/semantic worktree | `codex/v2.1-semantic-runtime`, HEAD `6cdbf12...`, 22 changed/untracked paths, 7 frozen intersections |
| Dirty worktrees treated as unknown WIP | 2 |
| Stashes | 0 |
| Protection branch | `codex/phase2-pass-6cdbf12` exists and points to `6cdbf12...` |
| Remote main | `23c6be78dd0c83dd81c5b4559ddab9dc77ff6fbd` |

An existing clean C candidate branch (`codex/v2.1-data-workspace` at `9e2525c...`) and an empty D branch based on Phase 2 were observed. Neither is a supplied canonical Day 1 input, neither is merged, and neither is evidence that Day 2 has started correctly.

## Work-package mapping

| Package | Status | Observable evidence | Final-gate gap / risk |
|---|---|---|---|
| D1-0 baseline freeze | `EVIDENCE_PRESENT` | Phase 2 branch/SHA/tree, 106-path frozen manifest, old Final Integration HEAD and clean status are recorded. | No unique Day 1 integration SHA; both Day 1 worktrees are dirty. |
| D1-1 upstream lock | `EVIDENCE_PRESENT` | Untracked `docs/UPSTREAM_LOCK.json` and license draft lock WrenAI, OpenChatBI, SuperSonic, IBM, SQLBot, Chat2DB, DB-GPT and PandasAI; no copied source is claimed. | Files are uncommitted; master-plan source is absent; upstream/license checks must be revalidated on final SHA. |
| D1-2 10M data and file set | `READY_FOR_FINAL_GATE` | Local PostgreSQL manifest records 10,000,000 sales, 5,000,000 payments, 100 Golden rows, deterministic signature; CSV/Parquet/XLSX datasets and hashes exist outside Git. | Rebuild reproducibility and final-SHA manifest verification still required; artifacts are intentionally not repository inputs. |
| D1-3 end-to-end SSE | `EVIDENCE_PRESENT` | 91 requests, 0 errors, all-query SSE rate 1.0, TTFE p95 398.739 ms, heartbeat max gap 2502.979 ms, cancel cleanup 264.684 ms, leak counts 0; protocol/unit-test files exist. | Strict run had zero real >10s requests. Earlier 20-worker run streamed 22/22 long requests but missed TTFE/heartbeat thresholds. Five frozen files are touched. |
| D1-4 WrenAI-compatible runtime | `IN_PROGRESS` | Clean-room MDL, dry-plan and semantic SQL implementation is wired into `QueryPipeline`; trace/audit points and tests exist. | No committed SHA or generated 20-case runtime evidence; `docker-compose.yml`, Query pipeline and UI frozen paths touched. |
| D1-5 OpenChatBI-compatible linking | `IN_PROGRESS` | Clean-room hybrid catalog/schema linker, workspace-scoped cache and trace assets exist. | Runtime call-rate evidence has not been produced on a clean/final SHA. |
| D1-6 SuperSonic-compatible SemanticQuery | `IN_PROGRESS` | Clean-room SemanticQuery parser covers metric/dimension/time/filter/join/comparison concepts and feeds Wren-compatible planning. | Deterministic keyword logic requires A/B result evidence; no final trace/result artifact exists. |
| D1-7 20 questions on 10M A/B | `IN_PROGRESS` | A 20-case runner (including clarification/guard cases) and baseline-vs-Day1 comparison logic exist. | No checked-in or externally located completed 20-case result was found; no single-SHA result signature set exists. |

## Scope, frozen-zone and contract impact

### E/data/SSE worktree

Frozen intersections (5):

- `backend/app/api/routes/analysis.py`
- `backend/app/api/routes/chat.py`
- `backend/app/services/chat.py`
- `backend/tests/test_phase2_auth_chat_attachments.py`
- `frontend/src/api/chat.ts`

The change affects authenticated chat/analysis SSE envelopes and therefore can regress Conversation, Memory, Attachment, Multimodal, Auth, Workspace isolation and the Chat UI even if Git reports no textual conflict. No Alembic file is changed.

### A/semantic worktree

Frozen intersections (7):

- `.env.example`
- `backend/app/core/config.py`
- `backend/app/query/oracle.py`
- `backend/app/query/service.py`
- `backend/app/semantic/engine.py`
- `docker-compose.yml`
- `frontend/src/pages/AskExperience.tsx`

The change replaces the default DATA_QUERY semantic planning route with a three-adapter clean-room chain and retains `local` only as explicit rollback. It affects API response trace payloads, Oracle behavior, Compose configuration and the Chat result UI. No Alembic file is changed.

## Mock, demo, shadow and runtime-path audit

- The 10M schema is a real local PostgreSQL schema with a deterministic manifest; `scripts/demo_db` is a directory name, not evidence of browser-mocked data.
- WrenAI/OpenChatBI/SuperSonic are compatibility adapters independently authored in ChatBI; no upstream runtime or source is packaged. The audit must describe them as `*-compatible clean-room`, not as upstream products running live.
- The semantic chain is coded as the default runtime, not a shadow-only path. However, without final execution evidence this remains `IN_PROGRESS`.
- No fixed full-question-to-answer or full-question-to-SQL mapping was found in the inspected Day 1 assets. The 20-case runner is evaluation code, not a runtime lookup table.

## Main risks

1. **Different-SHA stitched PASS:** data/SSE evidence was produced from dirty E changes, while semantic code is in a separate dirty worktree and B/C are separate commits. Combining those results would not prove one deployable tree.
2. **Frozen behavior regression:** 12 frozen paths are touched across the two Day 1 worktrees, including Authenticated Chat/SSE, QueryPipeline, ResultOracle, Compose and Ask UI.
3. **Long-request SSE gap:** the strict profile passes latency and heartbeat but contains no >10s request; the long-request profile passes streaming rate but misses strict TTFE/heartbeat limits.
4. **Semantic evidence gap:** source/tests exist, but the 20-case A/B runner has no located output and no final runtime call-rate/result-signature evidence.
5. **License wording:** SuperSonic and WrenAI have path-sensitive or additional terms. Only clean-room concepts are currently supportable; copying or ambiguous branding remains blocked.

## Required Day 1 final gate

Day 1 may advance only after a clean, unique `DAY1_FINAL_SHA` contains the intended E+A changes and is tested as one tree. At minimum: exact changed-file/frozen intersection refresh; migration single-head check; 20-case 10M A/B with result signatures and runtime call rates; strict SSE plus a real >10s streaming run; Phase 2 Backend/Frontend/E2E/Auth/Memory/Attachment regressions; license/secret scan; and clean worktree/remote ref verification.

`DAY1_PASS_CLAIMED=NO`
