# ChatBI V2 Open Source Capability Map

## 1. Mapping rule

Every entry follows:

`ChatBI V2 module -> reference project -> verified directory/file -> learning/reuse target -> whether code may enter the formal repository`

The paths below were checked in the frozen Phase 0 worktrees. A path appearing here does not authorize copying it. ChatBI V2 remains ChatBI-first, and all third-party integrations must sit behind a replaceable Adapter.

## 2. Phase 1 capability mapping

| ChatBI V2 module | Reference project | Verified directory / file | What we learn or reuse | May code enter the formal repository? |
| --- | --- | --- | --- | --- |
| Semantic Core: model/metric/dimension/relationship schema | WrenAI | `core/wren-mdl/mdl.schema.json`; `core/wren-core-base/src/mdl/` | MDL shape, manifest/model builder patterns, relationship and semantic-definition validation | Conditional: only audited Apache-2.0 paths, preferably as an Adapter/package dependency; record exact files and obligations first |
| Semantic SQL / Context Layer | WrenAI | `core/wren-core/`; `core/wren-core-py/src/context.rs`; `docs/core/concepts/what_is_context.md`; `docs/core/reference/mdl.md` | Semantic-to-SQL planning boundaries, context representation, Python integration surface | Conditional: Adapter/dependency candidate only; CC-BY documentation is for attributed study, not source copying |
| Schema Linking and table selection | OpenChatBI | `openchatbi/text2sql/schema_linking.py`; `openchatbi/catalog/schema_retrival.py`; `openchatbi/catalog/retrival_helper.py`; `openchatbi/catalog/catalog_store.py` | Metadata retrieval, candidate schema reduction, table/column selection inputs | Yes, selectively and with MIT notice/provenance; prefer reimplementation inside ChatBI interfaces rather than copying the project |
| NL2SQL orchestration | OpenChatBI | `openchatbi/text2sql/sql_graph.py`; `openchatbi/text2sql/generate_sql.py`; `openchatbi/prompts/schema_linking_prompt.md`; `openchatbi/prompts/text2sql_prompt.md` | Graph-stage boundaries, schema-linking handoff, generation and confidence workflow | Yes, selectively under MIT obligations; no whole-project migration and no dependency on internal directory structure |
| Evaluation Adapter and Result Oracle support | IBM Text-to-SQL Evaluation Toolkit | `src/text2sql_eval_toolkit/evaluation/`; `src/text2sql_eval_toolkit/execution/`; `scripts/evaluation/`; `scripts/execution/`; `scripts/analysis/` | Execution-based accuracy, result comparison, multiple ground truths, error classification and summary reporting | Prefer no source copy: use as an external test/evaluation dependency behind `EvaluationAdapter`; Apache-2.0 reuse remains possible after notice audit |
| Golden Set and release gate | IBM Text-to-SQL Evaluation Toolkit | `data/benchmarks.json`; `data/test-benchmarks.json`; `tests/`; `src/text2sql_eval_toolkit/profiling/` | Benchmark registration, small CI fixtures, evaluation/profile outputs for release gating | Test-only integration; never download the optional multi-GB result bundle during Phase 0 |
| Business terminology | SQLBot | `backend/apps/terminology/`; `backend/alembic/versions/039_create_terminology.py`; `backend/alembic/versions/069_term_custom_prompt.py` | Business-term lifecycle and the product relationship between terms and custom prompts | No. Product/data-flow study only because the root license adds GPL and branding conditions |
| Prompt/SQL-example product flow | SQLBot | `backend/templates/sql_examples/`; `backend/apps/template/generate_sql/generator.py`; `frontend/src/views/chat/execution-component/LogSQLSample.vue`; `frontend/src/views/chat/execution-component/LogCustomPrompt.vue` | How users inspect SQL examples and prompt evidence without exposing hidden model reasoning | No. Recreate independently against the approved ChatBI UI references |
| Recommended questions and feedback loop | SQLBot | `backend/apps/template/generate_guess_question/generator.py`; `backend/apps/datasource/crud/recommended_problem.py`; `frontend/src/views/chat/RecommendQuestion.vue`; `frontend/src/views/chat/RecommendQuestionQuick.vue` | Follow-up question generation, datasource-level recommendation configuration and chat placement | No. Product-reference only |
| Semantic model architecture | SuperSonic | `headless/api/src/main/java/com/tencent/supersonic/headless/api/pojo/SemanticSchema.java`; `headless/server/src/main/resources/mapper/custom/MetricDOCustomMapper.xml`; `DimensionDOCustomMapper.xml`; `ModelDOCustomMapper.xml` | Separation of semantic API objects, model/metric/dimension persistence and server services | No. Architecture reference only due additional derivative-work restriction |
| Semantic parser / translator / schema mapper | SuperSonic | `headless/chat/src/main/java/com/tencent/supersonic/headless/chat/parser/SemanticParser.java`; `headless/core/src/main/java/com/tencent/supersonic/headless/core/translator/SemanticTranslator.java`; `headless/core/src/main/java/com/tencent/supersonic/headless/core/utils/SchemaMatchHelper.java` | Parser-to-translator contracts, schema matching stages and semantic query decomposition | No. Reimplement concepts independently behind ChatBI interfaces |
| Datasource connection UI | Chat2DB | `chat2db-community-client/src/blocks/CreateConnection/`; `chat2db-community-client/src/components/ConnectionEdit/`; `chat2db-community-client/src/service/connection.ts` | Connection form grouping, edit/test interaction, datasource-type configuration | No. UI/UX study only; do not copy code, assets, branding, or layouts pixel-for-pixel |
| Schema/table browser | Chat2DB | `chat2db-community-client/src/blocks/NewTree/`; `chat2db-community-client/src/store/tree/`; `chat2db-community-client/src/database/action/datasourceTree.ts`; `chat2db-community-client/src/components/ViewTable/` | Lazy metadata tree, refresh/search state and table-detail interaction | No. UI/UX study only |
| SQL workspace, results and query history | Chat2DB | `chat2db-community-client/src/pages/main/workspace/`; `chat2db-community-client/src/pages/main/workspace/components/SQLExecute/`; `chat2db-community-client/src/components/SQLEditor/`; `chat2db-community-client/src/service/history.ts` | Workspace layout, tab lifecycle, execution-result presentation and history retrieval | No. UI/UX study only; the ChatBI product must remain chat-first rather than SQL-workbench-first |

## 3. Explicit exclusions

| Reference area | Reason excluded from current ChatBI V2 scope |
| --- | --- |
| `OpenChatBI/timeseries_forecasting/` and `openchatbi/tool/timeseries_forecast.py` | Prediction is P2 and must not expand the ChatBI V1 main path |
| `openchatbi/tool/memory.py`, `openchatbi/memory_*`, and general agent/tool orchestration | Complex memory and general Agent platform capabilities are P2/out of scope |
| SQLBot source, logos, and frontend visual assets | Additional GPL/branding conditions; product-reference only |
| SuperSonic implementation code | Additional commercial derivative-work restriction; architecture-reference only |
| Chat2DB implementation code and visual assets | `LicenseRef-Chat2DB` external-product/object-distribution/embedded-use and branding restrictions; UI/UX-reference only |
| DB-GPT | `PHASE_2_ONLY`; evaluate only after V1 main-path completion |
| PandasAI | `PHASE_2_ONLY`; evaluate only after V1 main-path completion |

## 4. Required integration gates

Before any allowed third-party capability can enter ChatBI V2:

1. Verify the exact upstream commit and file/package license again because upstream license terms may change after this frozen SHA.
2. Audit transitive dependencies and bundled assets, not only the root `LICENSE`.
3. Update `THIRD_PARTY_NOTICES.md` with repository, version/SHA, license, file scope, modifications, copyright and notice obligations.
4. Put runtime integration behind the appropriate `SemanticEngineAdapter`, `NL2SQLEngineAdapter`, or `EvaluationAdapter`.
5. Add correctness, security, replacement/removal and license-compliance tests before enabling it.
6. Keep SQLBot, SuperSonic, and Chat2DB code outside the formal repository regardless of technical attractiveness.
