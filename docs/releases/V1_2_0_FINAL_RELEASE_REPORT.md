# ChatBI V2 V1.2.0 Final Release Report

## Outcome

- Release status: `FROZEN` after all main-SHA gates and remote checks pass.
- Version: `V1.2.0`.
- Annotated Tag: `chatbi-v2-v1.2.0`.
- Pre-release main: `094c81aaaba44ced62fec7f0b97cc73f217d5975`.
- Integration input: `5303bdb687ffe4c3896292b333edb58ed4003d6c`.
- Promotion: `FAST_FORWARD_ONLY`; no force push, rebase or history rewrite.
- Final release SHA: resolve from `git rev-parse chatbi-v2-v1.2.0^{}` and verify against local/tracking/`ls-remote main` in the delivery output.

## Frozen release gate

- Frontend typecheck: PASS.
- Frontend Vitest: 13/13 files, 50/50 tests PASS.
- Frontend production build: PASS, 741 modules; the 555.48 kB ECharts warning remains non-blocking P2.
- Backend pytest: 225/225 PASS; Python compile check PASS.
- Playwright serial release gate: 82/82 PASS, one worker.
- Docker official stopped-state start: PASS; Backend, RAG Runtime and Frontend healthy.
- Browser smoke: Console Error 0, Page Error 0, unexpected Request Failure 0, unexpected blocking 4xx/5xx 0.
- Secret/release-tree scan: PASS; no raw Playwright HTML/trace/storageState/auth payload is shipped.

## Product verification

ChatGPT-style layout, purple brand, hidden evidence Drawer, single-render user turns, simplified Assistant shell, real Streaming, stop/cancel, ordering/persistence, complete Composer interactions and all five result semantics pass. NL2SQL, RAG, bounded Multi-Agent, File/Image QA, RBAC and Workspace Isolation remain available and verified.

The main-SHA release gate exposed a race where browser disconnect alone could arrive after a fast analysis had committed. V1.2.0 therefore sends an authenticated, conversation-scoped explicit cancellation before aborting the SSE reader, and removes only the messages bound to that client message ID. The two real cancellation flows passed five consecutive repetitions each before the complete release gate was rerun.

## One-click startup

- Windows double-click entry: repository root `一键启动-ChatBI-V2.cmd`.
- Command-line entry: `scripts/start.ps1`.
- Automated no-browser entry: `scripts/launch.ps1 -NoOpen`.
- Frontend after startup: `http://localhost:5173`.

The launcher starts only Backend, RAG Runtime and Frontend through Docker Compose and reuses user-local PostgreSQL/MySQL. It does not reset Git, auto-login, expose credentials, or create Docker database volumes.

## Freeze and branch policy

After the Tag and remote SHAs are verified, V1.2.0 is immutable. The fully merged Source task branch may be deleted locally and remotely; `codex/v2.1-final-integration` remains preserved. New functionality must start from a new development branch.
