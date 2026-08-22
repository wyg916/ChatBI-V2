# Third-Party Notices

## V1.3.0 Phase 2 selected upstream semantic sources

V1.3.0 Phase 2 directly reuses three official upstream projects. Three Python files from OpenChatBI/WrenAI are vendored byte-identically to locked Git blobs; IBM selected source is executed only from an external fixed checkout after commit and per-file SHA-256 verification, and is not copied or distributed by ChatBI.

| Project | Official revision | Selected upstream path | License | Runtime use |
| --- | --- | --- | --- | --- |
| OpenChatBI | `c8786cb180081dbdd18d841efa33b70d77b633e9` | `openchatbi/catalog/catalog_store.py` | MIT | `split_db_table_name` projects authorized catalog tables before ChatBI hybrid ranking; 588 calls in the frozen 70-case A/B |
| WrenAI | `7830cc746c11602d5899d8fdec1e28de4ce11a87` (`wren-v0.13.3`) | `core/wren/src/wren/type_mapping.py` | Apache-2.0 | `parse_types` maps ChatBI dimensions into MDL types |
| WrenAI | same revision | `core/wren/src/wren/mdl/wren_dialect.py` | Apache-2.0 | the Wren SQLGlot dialect parses every selected-source dry semantic SQL; Wren selected-source calls total 140 in the frozen 70-case A/B |
| IBM Text-to-SQL Evaluation Toolkit | `60dd4515236adb335f2053b7c069397d7d88fe0a` | 11 hash-locked files under `evaluation`, `metrics`, `analysis`, `inference`, plus `utils.py`/`logging.py` in an external checkout | Apache-2.0 selected-source path | official `evaluate_prediction` ran 50 times and `get_failed_records` once against executed Golden results; no IBM file is vendored or distributed |

The exact upstream Git blobs, raw/destination SHA-256 values, import closure, modifications, disable switch and rollback are in `backend/app/semantic_runtime/_upstream/provenance.json`; copied license notices are in `backend/app/semantic_runtime/_upstream/NOTICE.md`. No upstream LLM client, Provider key, database connector, executor, UI, logo, documentation or trademark asset is included. `CHATBI_SEMANTIC_UPSTREAM_REUSE_MODE=clean_room` disables the three selected sources for A/B; `CHATBI_SEMANTIC_RUNTIME_MODE=local` bypasses the complete semantic runtime.

SuperSonic remains an independently authored clean-room semantic contract. IBM's package/wheel path remains blocked by Apache-2.0/MIT metadata conflict, while the narrower Apache-2.0 selected-source path above is allowed and independently verified. SQLBot remains **not reused** because of modified GPL branding conditions and a required xpack wheel with no license metadata/file; its official runtime call count and xpack load count are zero. Existing online IBM-compatible evaluation and SQLBot-inspired feedback code continue to identify themselves as `chatbi-clean-room`.

## V1.3.0 Phase 3 selected Agent, File and scanning-PDF runtimes

Phase 3 adds two deliberately narrow direct-runtime boundaries. DB-GPT is installed only from the exact `packages/dbgpt-core` revision and executes AWEL; its application, RAG, datasource, auth, conversation, model-key and skill surfaces are excluded. PandasAI contributes exactly one byte-identical MIT community file, `pandasai/sandbox/sandbox.py`; no root `pandasai` import and no `ee/**` path is packaged.

| Project | Official revision / version | Selected path | License | Runtime boundary |
| --- | --- | --- | --- | --- |
| DB-GPT | `db580e952e544acf9f6c6c153da29dc67e9e40d7` / `0.8.1` | `packages/dbgpt-core`, specifically `DAG`, `MapOperator`, `BaseOperator.call` | MIT | AWEL receives only route, Trace ID and hard budgets, then calls the existing ChatBI five-role/six-tool orchestrator. It never receives SQL, datasource identifiers, model keys, connectors, RAG state or tool results. Exact archive SHA-256: `e225a2e222874adfb504e03f6a2d091729d8ecb2c874783fd4bcbc2c7c8ef31b`. |
| PandasAI | `bbbb771d31062d81f6fa19bafb40620d5cbe48f4` | `pandasai/sandbox/sandbox.py`, Git blob `6f31f9dfd3dbd023c7f82a1533bb3c577efd19fd` | MIT Expat | The inherited upstream `Sandbox.execute` delegates to ChatBI's disposable hardened Docker worker. Selected file SHA-256: `a6d4934cffc70d8a325071d8ab94b12ec0ded9043cdc01e9ba3a4d1f64d210c6`. |
| pypdfium2 | `5.13.0` | published Python package and bundled PDFium binary | BSD-3-Clause / Apache-2.0 plus dependency notices | Bounded scanned-PDF pages are rendered to clean PNG before the existing Vision preprocessing and Model Gateway. |
| Docker SDK for Python | `7.1.0` | published Python package | Apache-2.0 | Host-side control API for creating and synchronously destroying the isolated worker; never installed inside or exposed to the worker. |

The retained license and provenance records live in `packages/dbgpt-runtime-adapter/` and `packages/pandasai-selected-runtime/`. The worker runs non-root with no host mount, no database/model credential, no external network, a read-only root filesystem, dropped capabilities, no-new-privileges, bounded tmpfs, CPU/RAM/PID/time/file/output limits, and mandatory synchronous removal. Missing dependency, wrong provenance or unavailable Docker fails closed and produces zero verified runtime calls.

## v2.1 Day 1 semantic design provenance

No source, UI, logo, trademark asset or binary from the following projects is copied or packaged. ChatBI uses project-owned clean-room adapters behind its own contracts; the references below document design provenance and the exact upstream state reviewed on 2026-08-18.

| Project | Locked revision | Reviewed license scope | ChatBI integration |
| --- | --- | --- | --- |
| WrenAI | `7830cc746c11602d5899d8fdec1e28de4ce11a87` (`wren-v0.13.3`) | `core/**` and `sdk/**`: Apache-2.0; `docs/**`: CC-BY-4.0; trademarks excluded | Public MDL concepts only; `backend/app/semantic_runtime/wren.py` is independently implemented |
| OpenChatBI | `c8786cb180081dbdd18d841efa33b70d77b633e9` (`1.0.0b1`) | MIT | Public catalog, hybrid retrieval and workflow concepts only; independently implemented |
| SuperSonic | `af08d869c4609bf8d48d64e78c61427fe93f7489` | Apache-2.0 with an additional derivative-distribution condition | Public semantic-pipeline concepts only; no source-derived distributed work |

The final eight-project path-level decisions and license checksums are in `docs/UPSTREAM_LOCK.json` and `docs/OPEN_SOURCE_LICENSE_AUDIT.md`; the Day 1 draft remains only as historical evidence.

## SQLGlot

- Source repository: `https://github.com/tobymao/sqlglot`
- Pinned source revision: `9a8129b6f2667673f24713f4b49162ebae1f699d` (`v30.17.0`)
- Package version: `sqlglot==30.17.0`
- License: MIT
- Project files: `backend/requirements.txt`, `backend/app/query/sql_guard.py`
- Purpose: parse PostgreSQL/MySQL SQL into an AST, reject unsafe statements and unauthorized objects, normalize SQL, and enforce a row limit.
- Modification: no SQLGlot source file was copied or modified. ChatBI uses the published package only through the project-owned `SqlGuard` boundary.

Other pre-existing runtime packages remain pinned in the relevant package manifests. No third-party logo, brand asset, UI source, or restricted project source was introduced in Day 2.

## v2.1 Day 2 clean-room product references

- Chat2DB: reviewed at `5372213f267a087c232cb86cae4b200e00c3389f`; its current custom license is incompatible with the intended product embedding/distribution pattern. The Data Workspace is independently authored and copies or runs no Chat2DB source, UI, service, container, logo or brand asset.
- DB-GPT historical Day 2 status: at that checkpoint its MIT concepts were design provenance only. This is superseded only for the exact Phase 3 `dbgpt-core/AWEL` boundary above; all embedded skill, app, RAG, auth and datasource surfaces remain excluded.
- PandasAI historical Day 2 status: at that checkpoint it was not imported. This is superseded only for the exact Phase 3 community `pandasai/sandbox/sandbox.py` file above; `ee/**` remains excluded and deterministic file questions still execute no generated Python.

These Day 2 paths add no third-party runtime dependency. Exact selected paths, license boundaries, checksums, forbidden paths and rollback decisions are recorded in `docs/UPSTREAM_LOCK.json` and the final `docs/OPEN_SOURCE_LICENSE_AUDIT.md`.

## IBM Text-to-SQL Evaluation Toolkit selected-source evaluation

- Source repository: `https://github.com/IBM/text2sql-eval-toolkit`
- Audited upstream revision: `60dd4515236adb335f2053b7c069397d7d88fe0a`
- License: Apache-2.0
- Project boundary: `backend/app/evaluation/ibm_official/`
- Purpose: adapter-level execution result comparison, multiple accepted ground truths, error analysis and release-gate reporting.
- Modification/source use: no IBM source file, package, benchmark result bundle, logo or asset is copied into ChatBI. The offline runner verifies the fixed checkout commit and 11 source hashes, then invokes official functions in that checkout's isolated environment. Package/wheel use remains blocked; the online adapter stays independently authored and only the offline/CI gate counts official calls.

## SQLBot product-flow reference

- Source repository: `https://github.com/dataease/SQLBot`
- Audited upstream revision: `2a86aa926c4a22400a4ab4506c3ec384f7855a9d`
- License boundary: modified GPLv3 with additional logo/copyright conditions; reference-only.
- Purpose: terminology, SQL-example and feedback-loop product concepts.
- Source use: no SQLBot source, UI, logo, prompt, text or asset is copied. ChatBI's feedback workflow is independently implemented with existing project-owned `QueryFeedback`, `VerifiedAnswer`, `AnswerVersion`, SQL Guard and Result Oracle contracts.

## Chat2DB design audit (reference only)

- Current official repository: `https://github.com/OtterMind/Chat2DB`
- Audited revision: `5372213f267a087c232cb86cae4b200e00c3389f`
- Current license: `LicenseRef-Chat2DB`; Community 5.3.0+ adds source-available restrictions to Apache-2.0.
- Use in ChatBI: behavioral reference only for the database tree, SQL workspace, formatting, history, and result-view concepts.
- Copied source, UI, brand asset, logo, package, service, container, or binary: none.
- Implementation: independently authored against ChatBI's existing FastAPI/React contracts and its SQLGlot Guard, resource authorization, read-only Query Executor, Result Oracle, RBAC, audit, and Workspace isolation.
- Detailed lock, selected reference paths, hashes, and rollback boundary: `docs/v2_1/audits/C_CHAT2DB_AUDIT.md`.

Chat2DB is not a runtime or build dependency. The C workflow adds no third-party package and does not redistribute Chat2DB. The historical `v0.3.7` tag remains Apache-2.0 according to the current upstream license text, but no historical source was copied either.

## Direct runtime and test dependencies

ChatBI V2 itself is released under Apache License 2.0. Direct dependencies are consumed as published packages; their source is not copied into this repository. Versions are pinned in `backend/requirements.txt` and `frontend/package-lock.json`.

| Component | License |
| --- | --- |
| FastAPI, SQLAlchemy, Alembic, Pydantic, pydantic-settings, PyMySQL, pytest, SQLGlot | MIT |
| Starlette, Uvicorn, HTTPX | BSD-3-Clause |
| psycopg / psycopg-binary | LGPL-3.0-only |
| cryptography | Apache-2.0 OR BSD-3-Clause |
| pandas | BSD-3-Clause |
| openpyxl, python-docx | MIT |
| xlrd, xlwt | BSD-3-Clause |
| PyArrow, python-multipart | Apache-2.0 |
| pypdf | BSD-3-Clause |
| Pillow | MIT-CMU |
| React, React DOM, React Router, TanStack Query, Testing Library, jsdom, Vite, Vitest | MIT |
| TypeScript, Playwright, Apache ECharts | Apache-2.0 |
| pip-audit (release audit tooling only) | Apache-2.0 |

This table covers direct project dependencies used by the released build. Transitive notices remain governed by their package metadata and lockfiles.

## Apache ECharts

- Source repository: `https://github.com/apache/echarts`
- Package version: `echarts@6.1.0` (npm)
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
- Interface: OpenAI-compatible Chat Completions over HTTPS through the project-owned V1.3 `ModelGateway` and provider adapters.
- Source use: no provider SDK, source code, logo, model weight, or brand asset was copied into the repository.
- V1.3 source reuse: no external open-source control-plane code was copied or imported; routing, cost, budget, circuit-breaker, fallback and trace logic are independently authored ChatBI code. The only runtime HTTP implementation is the existing pinned `httpx` dependency.
- Credentials: server-side environment variables only; no credential is present in tracked files or browser responses.
- Terms: operators remain responsible for each provider's current API terms, pricing, data handling policy, and key rotation.
