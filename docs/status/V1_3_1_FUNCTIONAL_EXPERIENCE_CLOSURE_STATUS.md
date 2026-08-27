# V1.3.1 Functional Experience Closure Status

- Task: `CHATBI_V2_V1_3_1_FUNCTIONAL_EXPERIENCE_MODEL_ADMIN_AND_ALL_CONTROLS_CLOSURE`
- Date: 2026-08-28
- Status: `PARTIAL_BLOCKED_C_DATABASE_PROVISIONING`
- Base: `8f0326b59759e2549e7f684f0a3e40e3b6faffdf`
- Last implementation commit: `ad8372037278d74fd11b0a8ad4c996f1ba4d89db`
- Provider-certified implementation commit: `65c5271`
- Scope: P0/V1 ChatBI main-chain functional closure; no P2 platform expansion.

## Delivered implementation

- Closed deterministic chat intents for data follow-up, model status, system capability, and administrator queries without leaking stale data slots into non-data answers.
- Added answer identity, semantic labels, stable high-cardinality chart behavior, and one-time answer-start scrolling with a recovery control.
- Replaced model, system, workspace, user, role, invitation, audit, and security UI shells with persistent Backend API workflows and RBAC/last-administrator safeguards.
- Applied workspace query limits, timeout, schema allow/block policy, strict/standard wildcard policy, default datasource/model routing, invitation lifecycle, and paged audit export.
- Added truthful build metadata and Compose variables for independent C-line metadata and demo databases/schemas.

## Validation completed

- Backend focused regression: `51 passed`.
- Backend broad regression: `681 passed, 7 skipped`, with the two Git-introspection cases re-run `2/2 passed` against a read-only exact repository object database. The first broad container command could not resolve the Windows worktree `.git` indirection; this is reported as a two-command composite result rather than a single-command PASS.
- Frontend focused regression: `25/25 passed`.
- Frontend full regression: `60/60 passed` across 15 files.
- TypeScript `tsc --noEmit`: PASS.
- Vite production build: PASS, 991 modules.
- Real provider smoke through the production `ModelGateway` and persistent `ModelInvocation` ledger: MiMo, DeepSeek, and Kimi each PASS; 3 transport attempts, no retry/fallback, total estimated cost CNY `0.0005425`; no keys or authorization headers in evidence.

## Fail-closed blocker

The application role `chatbi_app` has no `CREATEDB` privilege and database `chatbi_v131_functional` does not exist. A local no-password PostgreSQL administrator connection was rejected. Starting Compose with the available shared metadata database would violate the task's C-line isolation requirement and could migrate Track A state, so startup was intentionally refused.

Required owner/DBA action before certification resumes:

1. Create an independent PostgreSQL database such as `chatbi_v131_functional`, owned by or fully granted to the existing application role.
2. Provision/grant the isolated demo schema/database named by `CHATBI_DEMO_POSTGRES_SCHEMA` and, when MySQL compatibility smoke is required, `CHATBI_DEMO_MYSQL_DATABASE`.
3. Supply the independent `CHATBI_DATABASE_URL` through process environment or a local secret file; do not paste credentials into source, evidence, or chat.

## Gates not executed

- C-line Compose start/stop cycles: `0/2`, blocked before startup.
- Browser login/chat/settings/RBAC and all-controls certification: not executed.
- Database restart persistence and UI refresh control counts: not measured.
- Remote push: not attempted because all release gates did not pass.

The main worktree and Track A services were not changed. The exact browser/control evidence must be generated only after independent database provisioning.
