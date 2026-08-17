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

## Direct runtime and test dependencies

ChatBI V2 itself is released under Apache License 2.0. Direct dependencies are consumed as published packages; their source is not copied into this repository. Versions are pinned in `backend/requirements.txt` and `frontend/package-lock.json`.

| Component | License |
| --- | --- |
| FastAPI, SQLAlchemy, Alembic, Pydantic, pydantic-settings, PyMySQL, pytest, SQLGlot | MIT |
| Uvicorn, HTTPX | BSD-3-Clause |
| psycopg / psycopg-binary | LGPL-3.0-only |
| cryptography | Apache-2.0 OR BSD-3-Clause |
| React, React DOM, React Router, TanStack Query, Testing Library, jsdom, Vite, Vitest | MIT |
| TypeScript, Playwright, Apache ECharts | Apache-2.0 |

This table covers direct project dependencies used by the released build. Transitive notices remain governed by their package metadata and lockfiles.

## Apache ECharts

- Source repository: `https://github.com/apache/echarts`
- Package version: `echarts==6.1.0` (npm)
- License: Apache-2.0
- Project files: `frontend/package.json`, `frontend/src/charting/EChartsRenderer.tsx`
- Purpose: render the project-owned controlled ChartSpec as KPI, line, bar, grouped/stacked bar, donut, or table-compatible visuals.
- Modification: no ECharts source file was copied or modified. ChatBI only uses the published package through project-owned renderer components.

Day 3 introduced no copied third-party source, logo, brand asset, or restricted UI code. The Chart Engine, Narrative Engine, Answer/Dashboard evidence contracts, and Evaluation runner are project-owned code.

## Legacy project two interoperability

- Source repository: user-controlled frozen repository, audited at commit `b6be894a7153f7ce8d31dfc65da7222bd7af1b5f`.
- Integration: HTTP-only `LegacyRagAdapter` and a disabled-by-default legacy assistant contract adapter; ChatBI does not import the old repository's internal Python classes.
- Copied production source: none.
- Evaluation provenance: `evaluation/legacy-rag/SOURCE.json` records the source commit, blob IDs, case counts and SHA-256 values for two internal 60-case RAG inputs. The payload JSON files are deliberately excluded from the public V1 repository.
- License boundary: the old repository has no root LICENSE/NOTICE. No legacy production source or provenance-pending test payload is redistributed. No old brand, logo, UI, database dump, secret, or credential is included.
- Published dependencies used by the new adapters: `httpx` (BSD-3-Clause), Pydantic (MIT), SQLAlchemy (MIT), and Alembic (MIT). No dependency source was copied or modified.

## External model API integrations

- Services: Moonshot Kimi API, Xiaomi MiMo API, DeepSeek API.
- Interface: OpenAI-compatible Chat Completions over HTTPS through the project-owned `ModelProviderAdapter`.
- Source use: no provider SDK, source code, logo, model weight, or brand asset was copied into the repository.
- Credentials: server-side environment variables only; no credential is present in tracked files or browser responses.
- Terms: operators remain responsible for each provider's current API terms, pricing, data handling policy, and key rotation.
