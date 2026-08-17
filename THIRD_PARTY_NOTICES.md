# Third-Party Notices

## SQLGlot

- Source repository: `https://github.com/tobymao/sqlglot`
- Pinned source revision: `9a8129b6f2667673f24713f4b49162ebae1f699d` (`v30.17.0`)
- Package version: `sqlglot==30.17.0`
- License: MIT
- Project files: `backend/requirements.txt`, `backend/app/query/sql_guard.py`
- Purpose: parse PostgreSQL/MySQL SQL into an AST, reject unsafe statements and unauthorized objects, normalize SQL, and enforce a row limit.
- Modification: no SQLGlot source file was copied or modified. ChatBI uses the published package only through the project-owned `SqlGuard` boundary.

Other pre-existing runtime packages remain pinned in the relevant package manifests. No third-party logo, brand asset, UI source, or restricted project source was introduced in Day 2.

## Apache ECharts

- Source repository: `https://github.com/apache/echarts`
- Package version: `echarts==6.1.0` (npm)
- License: Apache-2.0
- Project files: `frontend/package.json`, `frontend/src/charting/EChartsRenderer.tsx`
- Purpose: render the project-owned controlled ChartSpec as KPI, line, bar, grouped/stacked bar, donut, or table-compatible visuals.
- Modification: no ECharts source file was copied or modified. ChatBI only uses the published package through project-owned renderer components.

Day 3 introduced no copied third-party source, logo, brand asset, or restricted UI code. The Chart Engine, Narrative Engine, Answer/Dashboard evidence contracts, and Evaluation runner are project-owned code.

## External model API integrations

- Services: Moonshot Kimi API, Xiaomi MiMo API, DeepSeek API.
- Interface: OpenAI-compatible Chat Completions over HTTPS through the project-owned `ModelProviderAdapter`.
- Source use: no provider SDK, source code, logo, model weight, or brand asset was copied into the repository.
- Credentials: server-side environment variables only; no credential is present in tracked files or browser responses.
- Terms: operators remain responsible for each provider's current API terms, pricing, data handling policy, and key rotation.
