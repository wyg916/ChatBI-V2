# Day 1 current baseline

- Captured: 2026-08-18 17:20–18:45 +08:00
- Classification: P0 data, streaming and semantic-runtime hardening
- Repository: `https://github.com/wyg916/ChatBI-V2.git`

## Git facts before Day 1 edits

```text
LOCAL_MAIN_HEAD=6cdbf12f6c2e8494afe21262fd092795c4f784c3
REMOTE_MAIN_HEAD=23c6be78dd0c83dd81c5b4559ddab9dc77ff6fbd
PHASE2_SHA_EXISTS=YES
PHASE2_PROTECTION_BRANCH_EXISTS=YES
PHASE2_PROTECTION_BRANCH=codex/phase2-pass-6cdbf12
FINAL_INTEGRATION_BRANCH_EXISTS=YES
FINAL_INTEGRATION_HEAD=cceeb1c598f633d68c6428907db82b2f7903b5e2
FINAL_INTEGRATION_WORKTREE_CLEAN=YES
UNKNOWN_UNCOMMITTED_WIP_COUNT=0
STASH_COUNT=0
LATEST_RELEASE_TAG=chatbi-v2-v1.0.1
MAIN_PUSHED_BY_DAY1=NO
FINAL_TAG_CREATED_BY_DAY1=NO
```

The protection branch resolves exactly to the Phase 2 SHA. The integration worktree contains only the two governance commits `768f780` and `cceeb1c` above Phase 2. A separate committed and clean Day 2 data-workspace input exists locally at `9e2525c`; it is not merged by Day 1. B remains the supplied remote canonical input `5690d9d0ec04be0b21dfd642e0d8802ae1d5142a` and is not merged.

Worktrees observed:

```text
<project-root>                             6cdbf12 main
<worktree-root>/eval-feedback              39b689c codex/v2.1-eval-golden-feedback
<worktree-root>/final-integration          cceeb1c codex/v2.1-final-integration
<worktree-root>/data-workspace             9e2525c codex/v2.1-data-workspace
<worktree-root>/data10m-performance        6cdbf12 codex/v2.1-data10m-performance
<worktree-root>/rag-agent-file             6cdbf12 codex/v2.1-rag-agent-file
<worktree-root>/semantic                   6cdbf12 codex/v2.1-semantic-runtime
```

Commands executed and retained in the task log:

```powershell
git status --short --branch
git branch -avv
git rev-parse HEAD
git rev-parse 6cdbf12f6c2e8494afe21262fd092795c4f784c3
git remote -v
git log --oneline --decorate --graph -40
git tag --list
git worktree list
git diff
git diff --stat
git stash list
git ls-remote origin main
git ls-remote --heads origin
```

The first remote query confirmed `origin/main`; a later repeat suffered a transport reset and is recorded as a transient network warning, not an authorization failure.

## Product and test baseline

```text
MIGRATION_HEAD=20260818_0009 (single head; database current)
BACKEND_TEST=PASS 134/134 at Phase 2 freeze
FRONTEND_TYPECHECK=PASS at Phase 2 freeze
FRONTEND_TEST=PASS 29/29 at Phase 2 freeze
FRONTEND_BUILD=PASS at Phase 2 freeze
E2E=PASS 55/55 at Phase 2 freeze
DOCKER_SERVICES=3/3 healthy (backend, rag-runtime, frontend)
DOCKER_DATABASE_SERVICES=0
DOCKER_DATABASE_VOLUMES=0
AUTHENTICATION=PASS (anonymous 401, cross-workspace 403, valid login/logout, bypass 0)
CONVERSATION_MEMORY=PASS (persistence, refresh/history recovery, follow-up context, isolation)
FILE_DOCUMENT_IMAGE=PASS (CSV/XLS/XLSX/Parquet/PDF/DOCX/image and multimodal Phase 2 evidence)
OPEN_ENDED_CHAT=PASS 60/60 at Phase 2 freeze
```

The metadata and benchmark data are in local PostgreSQL; MySQL remains the compatibility database. Frontend access is Backend-API-only. No database container or Docker volume is used.

## Data and streaming baseline

At Day 1 start the isolated `chatbi_benchmark_v21` schema had already been generated once with fixed seed `20260818`: 10,000,000 sales rows, 5,000,000 payment rows, 50,000 products, 300,000 customers and 100 ground-truth cases. Its first signature was `34b8ec8023f410ea387003475f84bd63b05743580138ea919880979caf86af4c`.

Phase 2 had authenticated chat and analysis SSE endpoints, but it did not yet guarantee the complete Day 1 envelope/event vocabulary, lifecycle diagnostics, <=3s heartbeat, or measured cancellation cleanup. The previous high-contention observation (20 workers, 15 minutes) produced 4,546 requests with 0 errors and 22/22 real >10s requests streamed, but TTFE p95 1929.861 ms and heartbeat max gap 3162.007 ms exceeded the new Day 1 acceptance thresholds. It is stress evidence only, not a PASS baseline.

## Warnings and license state

- Existing non-blocking warning: the lazy ECharts chunk is 555.48 kB; the frozen conflict policy explicitly prohibits unrelated refactoring for this warning.
- No secret value was printed or committed. `.env` stays ignored.
- Existing third-party notice coverage includes SQLGlot and direct dependencies. Day 1 adds an exact eight-project lock and draft path-level audit; no third-party source, UI or brand asset is copied.
- Frozen Zone has 106 files. E and A intersections are classified HIGH_CONFLICT even when Git merges automatically; the final report must list and semantically review them.
