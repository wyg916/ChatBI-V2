# ChatBI V2 UI14 Integration Closure

```text
SCOPE=P0_UI_BASELINE_INTEGRATION
BASE_HEAD=2199c1707fc33bd6b100afabc91c90509c0a9ffa
DELIVERY_BRANCH=codex/ui-14page-integration
UI_PAGE_COUNT=14
UI_ROUTE_COUNT=14
```

## Route and component inventory

| # | Approved page | Direct route | React component | Shell |
|---|---|---|---|---|
| 01 | 登录页 | `/login` | `LoginPage` | standalone login |
| 02 | 问数据 - 空状态 | `/` | `AskPage` / `EmptyAskPage` | `AppShell` |
| 03 | 问数据 - 分析结果 | `/ask/results` | `AskPage` / `ResultAskPage` | `AppShell` |
| 04 | 数据源列表 | `/datasources` | `DatasourcesPage` | `AppShell` |
| 05 | 数据源详情与 Schema 管理 | `/datasources/:id` | `DatasourceDetailPage` | `AppShell` |
| 06 | 语义模型列表 | `/semantic-models` | `SemanticModelsPage` | `AppShell` |
| 07 | 语义模型编辑器 | `/semantic-models/:id` | `SemanticEditorPage` | `AppShell` |
| 08 | 答案库 | `/answers` | `AnswerLibraryPage` | `AppShell` |
| 09 | 看板列表 | `/dashboards` | `DashboardListPage` | `AppShell` |
| 10 | 经营看板详情 | `/dashboards/:id` | `DashboardDetailPage` | `AppShell` |
| 11 | 评测中心总览 | `/evaluation` | `EvaluationOverviewPage` | `AppShell` |
| 12 | 评测用例详情 | `/evaluation/:id` | `EvaluationDetailPage` | `AppShell` |
| 13 | 系统设置与模型服务 | `/settings/models` | `SettingsModelsPage` | `AppShell`, secondary management entry |
| 14 | 用户角色与审计 | `/settings/security` | `SecurityAuditPage` | `AppShell`, secondary management entry |

All 14 targets are React Router routes. No screenshot, Figma iframe or standalone static HTML is used as a page implementation. The primary navigation remains exactly: 问数据、数据源、语义模型、答案库、看板、评测中心. System settings remains a secondary management entry.

## Integration changes

- Added one UI14 Playwright spec that validates all 14 pages at all three approved viewports and retains 42 generated screenshot captures outside Git.
- Strengthened the Vitest route contract from a partial title check to the exact approved 14-route manifest.
- Redirected the prior Day 2 visual screenshot output to ignored Playwright artifacts so regression tests no longer mutate a tracked PNG.
- Enabled Playwright output retention for local acceptance evidence.
- Removed `SecondaryPages.tsx`, a fully unreferenced legacy placeholder that duplicated superseded answer, dashboard, evaluation, settings and security page shells. No routed page or business component was removed.
- Added this status and evidence record; no production page, style, asset, router, App Shell, API, package manifest or Backend code was redesigned or changed.

## Gate results

- `npm ci`: PASS, 204 packages installed, 0 vulnerabilities.
- TypeScript: PASS.
- Vitest: 10/10 files, 26/26 tests PASS.
- Production build: PASS, 728 modules. The pre-existing single chunk size warning remains non-blocking.
- Backend regression: 66/66 Pytest PASS (no Backend code changed by this task).
- Playwright: 15/15 PASS; the UI14 subset is 3/3 with 42/42 route-viewport checks.
- Viewports: 1440x900 PASS; 1366x768 PASS; 1920x1080 PASS.
- Console error: 0; page error: 0; blocking request failure: 0.
- Route white screen: 0; page-level horizontal clipping: 0; critical control clipping/obstruction: 0.
- Day 1 datasource, Schema and semantic-model browser flow: PASS. Frontend data access remains Backend API only.

## Scope and asset audit

At task start the worktree was clean. `2199c17` already contained the prior login/UI and Day 2 commits; those pre-existing Backend/NL2SQL changes are outside this task diff and were not modified. The task diff contains only UI integration tests, test-artifact hygiene, removal of the unreferenced UI placeholder and acceptance documentation.

No base64 image, duplicate font, frontend asset over 1 MiB, tracked `node_modules`, tracked `dist`, Figma embed, temporary HTML or third-party brand asset was found. The approved local SVG/PNG assets are small and referenced by the routed React UI.
