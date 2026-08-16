# ChatBI V2 Open Source Reference Manifest

## 1. Phase 0 scope

- Phase: `PHASE_0_PROJECT_BOOTSTRAP`
- Generated: `2026-08-16` (Asia/Shanghai)
- Formal repository: `E:\ChatBI V2 项目`
- External reference root: `E:\ChatBI V2 开源参考项目`
- Trust classification: every downloaded repository is `UNTRUSTED_EXTERNAL_SOURCE`.
- Acquisition policy: shallow Git repository (`depth=1`); no dependency installation, migration, database connection, Docker resource, model download, or service startup.
- This is a static license and source-layout review, not legal advice. Package dependencies, bundled assets, trademarks, and notices still require a release-time audit before any code enters ChatBI V2.

## 2. Frozen repositories

| Project | Local path | GitHub | Branch | HEAD | License | Phase 1 purpose | Usage mode |
| --- | --- | --- | --- | --- | --- | --- | --- |
| WrenAI | `E:\ChatBI V2 开源参考项目\WrenAI` | https://github.com/Canner/WrenAI | `main` | `7f7370e4e9b05a51dbde918cd5c9ecbedafe3d20` | Path-based: Apache-2.0 for `core/`, `sdk/`, `skills/`, `examples/`, and root files; CC-BY-4.0 for `docs/`; the included AGPL-3.0 text is reserved for possible future modules and the current root map assigns none | Semantic Layer, MDL, Metric, Dimension, Relationship, Context Layer, Semantic SQL | `RUNTIME_CANDIDATE` |
| OpenChatBI | `E:\ChatBI V2 开源参考项目\OpenChatBI` | https://github.com/zhongyu09/openchatbi | `main` | `c8786cb180081dbdd18d841efa33b70d77b633e9` | MIT | Schema Linking, catalog retrieval, table selection, NL2SQL graph and analysis flow | `SELECTIVE_CODE_REFERENCE` |
| IBM Text-to-SQL Evaluation Toolkit | `E:\ChatBI V2 开源参考项目\text2sql-eval-toolkit` | https://github.com/IBM/text2sql-eval-toolkit | `main` | `60dd4515236adb335f2053b7c069397d7d88fe0a` | Apache-2.0 | Execution-based evaluation, result comparison, Golden SQL, error analysis, release gate | `EVALUATION_TOOL` |
| SQLBot | `E:\ChatBI V2 开源参考项目\SQLBot` | https://github.com/dataease/SQLBot | `main` | `0c885d5a677ed3f6551645a4c5a630ee4c4eb437` | Modified GPLv3 with additional logo/copyright conditions | ChatBI product flow, terminology, SQL examples, prompts, feedback patterns, recommended questions | `PRODUCT_REFERENCE` |
| SuperSonic | `E:\ChatBI V2 开源参考项目\SuperSonic` | https://github.com/tencentmusic/supersonic | `master` | `af08d869c4609bf8d48d64e78c61427fe93f7489` | Apache-2.0 plus additional commercial derivative-work restrictions | Semantic model, metric/dimension/entity/relation, schema mapping, parser and translator architecture | `ARCHITECTURE_REFERENCE` |
| Chat2DB | `E:\ChatBI V2 开源参考项目\Chat2DB` | https://github.com/OtterMind/Chat2DB | `main` | `f85ae9e0ccc7a883aae94a3261ac5cfbd566d46a` | `LicenseRef-Chat2DB`, a modified Apache-2.0 license for Community 5.3.0+ with external-product, object-distribution, managed-delivery, embedded-use, and branding restrictions | Datasource UI, Schema/table browser, SQL workspace, query result and history interaction | `UI_UX_REFERENCE` |
| DB-GPT | Not downloaded | https://github.com/eosphoros-ai/DB-GPT | Not frozen | Not frozen | Not audited in Phase 0 | Agentic Data Analysis, SQL + Python, advanced analysis | `PHASE_2_ONLY` |
| PandasAI | Not downloaded | https://github.com/sinaptik-ai/pandas-ai | Not frozen | Not frozen | Not audited in Phase 0 | CSV, Excel and DataFrame natural-language analysis | `PHASE_2_ONLY` |

## 3. License decision matrix

Classification legend:

- `A`: may be considered as a direct dependency after package-level and transitive-license audit.
- `B`: source may be selectively reused or reimplemented with license obligations and provenance.
- `C`: architecture only; do not copy implementation into the formal repository.
- `D`: UI/product logic only; do not copy source, branding, or protected visual assets.
- `E`: defer all adoption decisions to Phase 2.

| Project | Class | LICENSE_TYPE | LICENSE_FILE | COMMERCIAL_RESTRICTION | COPYRIGHT_REQUIREMENT | DERIVATIVE_WORK_RESTRICTION | SAFE_USAGE_MODE |
| --- | --- | --- | --- | --- | --- | --- | --- |
| WrenAI | A (Apache paths only) | Multi-license by path | `LICENSE`, `LICENSE-APACHE-2.0`, `LICENSE-CC-BY-4.0`, `LICENSE-AGPL-3.0` | No additional commercial restriction identified for currently mapped Apache-2.0 paths; Wren/WrenAI names and logos are excluded trademarks | Preserve applicable copyright, license, and notice obligations; attribute CC-BY-4.0 documentation | Respect the path map and published-package manifest if it differs; do not assume all future modules remain Apache-2.0 | Prefer an Adapter or audited package dependency limited to Apache-2.0 paths; never copy branding |
| OpenChatBI | B | MIT | `LICENSE` | None stated in the root license | Include copyright and permission notice in copies or substantial portions | MIT permits modification and redistribution subject to notice retention | Selective implementation reference only; no whole-project import; exclude its forecasting, memory, and general-agent capabilities from ChatBI Core |
| IBM Text-to-SQL Evaluation Toolkit | A (test/evaluation scope) | Apache-2.0 | `LICENSE` | None stated in the root license | Preserve license and notices; mark modified files when distributing changes | Apache-2.0 conditions, including notice/patent provisions, apply | Prefer an external evaluation dependency behind `EvaluationAdapter`; keep it out of the ChatBI runtime |
| SQLBot | D | Modified GPLv3 with extra conditions | `LICENSE` | Frontend logo and copyright information may not be removed or modified | Retain logo/copyright as required by the additional condition, plus GPL obligations | GPLv3 copyleft plus project-specific added conditions; unsuitable as the independent ChatBI V2 source base | Study product flow only; no source, logo, or pixel-level UI copying |
| SuperSonic | C | Apache-2.0 plus additional conditions | `LICENSE` | Unmodified-source/logo commercial service use is described as allowed; derivative development and distribution requires a commercial license from the author | Preserve license and copyright notices | Commercially distributed derivative work requires separate authorization | Architecture and data-model study only; no code enters ChatBI V2 |
| Chat2DB | D | `LicenseRef-Chat2DB` modified Apache-2.0 (Community 5.3.0+) | `LICENSE` | External product/service, managed delivery, embedded use, specified object-form distribution, white-label/OEM use require written commercial authorization | Retain license, attribution, trademark, copyright, and modification notices | Source redistribution is conditional; external-operable or object-form product use is restricted; branding cannot be removed from official frontend/distribution | UI/UX interaction study only; no source, assets, branding, or derivative implementation enters ChatBI V2 |
| DB-GPT | E | Not audited | Not downloaded | Unknown | Unknown | Unknown | Phase 2 evaluation only after the V1 main path is complete |
| PandasAI | E | Not audited | Not downloaded | Unknown | Unknown | Unknown | Phase 2 evaluation only after the V1 main path is complete |

## 4. Acquisition and freeze evidence

For each downloaded repository, Phase 0 verified:

- `git remote get-url origin`
- `git branch --show-current`
- `git rev-parse HEAD`
- `git rev-parse --is-shallow-repository` = `true`
- `git status --short` = empty
- root `README*`, `LICENSE*`, and existing build/package descriptors were inspected statically only.

IBM checkout note: the initial ordinary HTTPS object transfer stalled. The same `depth=1` `main` commit was fetched with Git protocol v2 and `--filter=blob:none`; the worktree was hydrated from GitHub's archive for the exact frozen SHA and then checked against the Git index. No benchmark-result fetch command was run.

## 5. Disk usage

- `REFERENCE_SIZE_BEFORE_BYTES=0`
- Final per-repository and total sizes are recorded from recursive file-length sums, including each shallow `.git` directory, after all worktrees pass their clean-status check.

| Repository | Size (MB, bytes / 1,000,000) |
| --- | ---: |
| WrenAI | `24.18` (`24,180,849` bytes) |
| OpenChatBI | `21.88` (`21,877,767` bytes) |
| IBM Text-to-SQL Evaluation Toolkit | `407.57` (`407,566,940` bytes) |
| SQLBot | `56.68` (`56,684,091` bytes) |
| SuperSonic | `31.44` (`31,440,383` bytes) |
| Chat2DB | `71.64` (`71,635,527` bytes) |
| Total reference root | `613.39` (`613,385,557` bytes) |

## 6. Mandatory boundaries for future phases

1. No third-party source may enter the formal repository until its exact files, dependency tree, license, copyright/notice requirements, upstream version, commit SHA, and local modifications are recorded in `THIRD_PARTY_NOTICES.md`.
2. `SemanticEngineAdapter`, `NL2SQLEngineAdapter`, and `EvaluationAdapter` remain the only allowed integration boundaries for WrenAI, OpenChatBI-derived implementation ideas, and IBM evaluation tooling.
3. SQLBot, SuperSonic, and Chat2DB are reference-only. They are not product bases or runtime dependencies.
4. DB-GPT and PandasAI remain `PHASE_2_ONLY`; they must not block or expand the V1 ChatBI main path.
5. Static review does not authorize executing any downloaded script or connecting a reference project to a real database or credential.
