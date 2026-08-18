# Third-Party Notices

## v2.1 Day 1 semantic design provenance

No source, UI, logo, trademark asset or binary from the following projects is copied or packaged. ChatBI uses project-owned clean-room adapters behind its own contracts; the references below document design provenance and the exact upstream state reviewed on 2026-08-18.

| Project | Locked revision | Reviewed license scope | ChatBI integration |
| --- | --- | --- | --- |
| WrenAI | `7830cc746c11602d5899d8fdec1e28de4ce11a87` (`wren-v0.13.3`) | `core/**` and `sdk/**`: Apache-2.0; `docs/**`: CC-BY-4.0; trademarks excluded | Public MDL concepts only; `backend/app/semantic_runtime/wren.py` is independently implemented |
| OpenChatBI | `c8786cb180081dbdd18d841efa33b70d77b633e9` (`1.0.0b1`) | MIT | Public catalog, hybrid retrieval and workflow concepts only; independently implemented |
| SuperSonic | `af08d869c4609bf8d48d64e78c61427fe93f7489` | Apache-2.0 with an additional derivative-distribution condition | Public semantic-pipeline concepts only; no source-derived distributed work |

The complete eight-project path-level draft and license checksums are in `docs/UPSTREAM_LOCK.json` and `docs/OPEN_SOURCE_LICENSE_AUDIT_DRAFT.md` after Day 1 integration.

## SQLGlot

- Source repository: `https://github.com/tobymao/sqlglot`
- Pinned source revision: `9a8129b6f2667673f24713f4b49162ebae1f699d` (`v30.17.0`)
- Package version: `sqlglot==30.17.0`
- License: MIT
- Project files: `backend/requirements.txt`, `backend/app/query/sql_guard.py`
- Purpose: parse PostgreSQL/MySQL SQL into an AST, reject unsafe statements and unauthorized objects, normalize SQL, and enforce a row limit.
- Modification: no SQLGlot source file was copied or modified. ChatBI uses the published package only through the project-owned `SqlGuard` boundary.

Other pre-existing runtime packages remain pinned in the relevant package manifests. No third-party logo, brand asset, UI source, or restricted project source was introduced in Day 2.

## IBM Text-to-SQL Evaluation Toolkit design reference

- Source repository: `https://github.com/IBM/text2sql-eval-toolkit`
- Audited upstream revision: `60dd4515236adb335f2053b7c069397d7d88fe0a`
- License: Apache-2.0
- Project boundary: `backend/app/evaluation/ibm_adapter.py`
- Purpose: adapter-level execution result comparison, multiple accepted ground truths, error analysis and release-gate reporting.
- Modification/source use: no IBM source file, package, benchmark result bundle, logo or asset is copied or imported. The ChatBI adapter is independently authored behind the project-owned `EvaluationAdapter` boundary and operates only on results already produced by the guarded ChatBI QueryPipeline.

## SQLBot product-flow reference

- Source repository: `https://github.com/dataease/SQLBot`
- Audited upstream revision: `0c885d5a677ed3f6551645a4c5a630ee4c4eb437`
- License boundary: modified GPLv3 with additional logo/copyright conditions; reference-only.
- Purpose: terminology, SQL-example and feedback-loop product concepts.
- Source use: no SQLBot source, UI, logo, prompt, text or asset is copied. ChatBI's feedback workflow is independently implemented with existing project-owned `QueryFeedback`, `VerifiedAnswer`, `AnswerVersion`, SQL Guard and Result Oracle contracts.

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
- Integration: independently authored `LiveRagAdapter`, RAG Runtime, contracts and bounded five-role orchestrator; ChatBI does not import or copy the old repository's internal Python classes.
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
