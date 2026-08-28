# V1.3.1 Functional Experience Closure Status

- Task: `CHATBI_V2_V1_3_1_C_DATABASE_PROVISION_AND_FINAL_BROWSER_CONTROL_CLOSURE`
- Date: 2026-08-28
- Status at tracked-document freeze: `FINAL_CERTIFICATION_IN_PROGRESS`
- Base: `8f0326b59759e2549e7f684f0a3e40e3b6faffdf`
- Previous candidate: `fc74c2363440687e19567d95079f99f941b58986`
- Branch: `codex/v1.3.1-functional-experience-closure`
- Scope: P0/V1 ChatBI main-chain functional closure; no P2 platform expansion.

## Independent C-line database

- Provisioned local PostgreSQL database `chatbi_v131_functional`, owned by `chatbi_app`.
- The runtime role remains least-privileged: `CREATEDB=false`, `SUPERUSER=false`.
- C-line Compose is bound only to that metadata database and to its `demo_business` schema; no Docker database container or volume was introduced.
- The formal empty-database migration reaches the single head `20260828_0013` and creates 53 metadata tables.
- The formal PostgreSQL seed creates 9 business tables, including 1,095 orders and 1,825 daily KPI rows. A deterministic long customer name is included for chart truncation/tooltip certification.
- Track A remained healthy during the C-line start, restart, stop, and reset operations. Track B and the main worktree were not changed.

## Browser-discovered closure fixes

- When every external provider is disabled, `DATA_QUERY` now uses the advertised Local Semantic Runtime instead of failing with `No configured model provider is available`; unrelated gateway failures remain fail-closed.
- Provider enable/disable is now a persistence-only control. A paid network probe occurs only through the explicit `测试连接` action, preventing duplicate charges and keeping test-cost behavior observable.
- A first explicit connection check preserves the configured Provider's enabled state instead of creating a disabled runtime row. Health probes cap output at eight tokens, so Kimi is checked within the economy safety budget rather than being rejected before network dispatch.
- Ranking charts use business labels such as `客户收入贡献排名`. Value-axis labels and series tooltips include thousands separators and semantic units, while long category values remain intact for tooltip access and are truncated only on the axis.
- Analyst navigation hides system/user-management entry points. A direct settings URL that receives Backend 403 renders only a permission-denied state and no management controls.

## Validation before final SHA freeze

- Cycle 1 completed isolated start, health, authenticated Chat, persisted settings, RBAC, role change/revert, disable/enable, invitation create/copy/restart/readback/revoke, audit filters/details/pagination/export, member removal, last-administrator protection, and full stop.
- Browser intent separation passed for data, model-status, system-capability, and data follow-up prompts; stale-answer count was zero.
- Settings version 4 persisted query security, workspace, and appearance changes through refresh, PostgreSQL readback, audit, and application restart.
- Backend affected regression passed 127 tests with network disabled.
- Frontend affected regression and TypeScript validation passed; the complete final regression is deliberately executed only after the forward commit freezes the exact SHA.
- Cycle 2 reset recreated the formal migration/seed baseline and restored reset-scoped users/settings while retaining host-level database ownership and least privilege.

## Final evidence boundary

The tracked document cannot contain the hash of the commit that contains itself. Exact-SHA browser control inventory, three-provider live replay, full regression, image/runtime identities, cost ledger, SHA-256 manifest, and final PASS/FAIL are therefore written only under:

`E:/ChatBI_V2_Evidence/PostRelease/Functional_Experience_Closure/`

No merge, tag, release, or pull request is authorized by this status document. A normal non-force branch backup is permitted only if every final gate passes.
