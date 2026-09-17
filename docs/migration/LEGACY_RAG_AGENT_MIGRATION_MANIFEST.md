# 旧项目二 RAG 与有限编排迁移 Manifest

## 决策摘要

| capability | disposition | source | target | reason |
|---|---|---|---|---|
| RAG runtime | INDEPENDENT_REIMPLEMENTATION | 旧资产只作行为审计参考 | `app/rag_runtime` + `LiveRagAdapter` | 许可证不明，生产源码复制 0；当前仓库通过真实 HTTP Bridge 闭环 |
| RAG contracts | REIMPLEMENT_AS_OWN_CONTRACT | legacy DTO behavior | `packages/rag-contracts` | 消除旧 ORM/身份/场景耦合 |
| Composite orchestration | INDEPENDENT_BOUNDED_REIMPLEMENTATION | 旧资产只作边界参考 | `packages/agent-orchestrator` | 固定五角色、六工具和硬预算，不复制旧实现 |
| Legacy agent HTTP | ADAPTER_FAIL_CLOSED | `/api/v1/assistant/query` | `LegacyAgentOrchestratorAdapter` | 端点不能接受 ChatBI V2 ToolExecutor callback；在兼容协议出现前始终拒绝远程执行 |
| Tool/Skill runtime | SELECTIVE_CONTRACT_REUSE | `SkillExecutor`, registries | `ToolExecutor`, `tool_binding` | 只保留白名单、运行/步骤、审计，不迁行业 Skill |
| Model Gateway | DESIGN_REUSE | `backend/app/ai/model_gateway/` | 现有 ModelProvider Adapter | ChatBI 已有命名 Provider，不复制第二套网关 |
| RBAC/Audit | FIELD/POLICY_MAPPING | legacy authorization/audit | `core/access.py`, new run tables | 以 ChatBI workspace/grant 为权威 |
| Prompt | SIX_INDEPENDENT_VERSIONED_PROMPTS | 旧 Prompt 不复制 | `packages/prompt-registry`, prompt tables | 保存 source、purpose、version、checksum，不做市场 |
| Golden fixtures | PROVENANCE_ONLY_NOT_DISTRIBUTED | 60+60 JSON | `evaluation/legacy-rag/SOURCE.json` | 仅保留 source commit/blob/hash/count；许可证补证前不公开 payload |
| Legacy database | SNAPSHOT_ONLY | selected listed tables | new local PostgreSQL | 不连、不写、不搬全库 |

## 路由与开关

| route | primary path | shadow behavior | fallback |
|---|---|---|---|
| DATA_QUERY | existing `QueryPipeline` | none | n/a |
| KNOWLEDGE_QUERY | Live `RagAdapter` + Citation/Answer Guard | optional diagnostic modes only, not release default | fail closed without authorized evidence |
| HYBRID_ANALYSIS | `QueryPipeline` + verified RAG evidence merger | optional diagnostic modes only, not release default | retain only Oracle-passed data evidence as explicit partial result |
| COMPLEX_ANALYSIS | five roles + six-tool `ToolExecutor` | optional diagnostic modes only, not release default | publish only verified data fallback as explicit partial result |

V1 release defaults: `CHATBI_RAG_MODE=on`, `CHATBI_AGENT_MODE=on`, `CHATBI_AGENT_ALLOWED_ROUTES=COMPLEX_ANALYSIS`. `DATA_QUERY` never enters Agent.

## Security context contract

Every Adapter/tool request carries `workspace_id`, `user_id`, `roles`, `allowed_datasources`, `allowed_semantic_models`, `allowed_tools`, `trace_id`, `timeout`, step/tool/replan/depth budgets and token budget. RAG Bridge identity is HMAC-signed and checked against metadata DB ownership. Empty allowlists fail closed. Agent code receives no connection URL or connector object. Data tools accept an `AskRequest` and invoke the existing `QueryPipeline`; successful tool results must show SQL Guard allowed, Result Oracle passed and a result signature before evidence can be merged.

## Data migration

Only these target tables are allowed: `knowledge_source`, `knowledge_document`, `knowledge_document_version`, `knowledge_chunk`, `knowledge_acl`, `knowledge_ingestion_run`, `knowledge_retrieval_run`, `citation`, `orchestration_profile`, `orchestration_run`, `orchestration_step`, `tool_binding`, `tool_call`, `prompt_template`, `prompt_version`.

Migration input is an offline sanitized JSON snapshot with `source_commit` and `migration_batch_id`; the script defaults to dry-run and never accepts an old database URL. Apply writes only the new metadata database. Rollback deletes one named batch from the new tables in reverse dependency order. No existing ChatBI core table is overwritten.

## History and source extraction

The bridge contains no copied legacy production source, so no source-history rewrite is required for the first stage. Golden fixture payloads are not distributed; only their source commit, blob IDs, case counts and SHA-256 provenance are retained. A later source extraction may use a temporary clone plus `git filter-repo --path backend/app/knowledge` or a subtree-split branch only after (1) bridge validation, (2) ownership/license proof, and (3) dependency-cut analysis. It must never mutate the frozen source repository or introduce a submodule/absolute-path dependency.

## License gate

The old repository has no root LICENSE or `THIRD_PARTY_NOTICES.md`. Direct legacy source extraction is therefore blocked for open-source release until ownership/provenance is documented. HTTP interoperability and independently authored ChatBI contracts do not copy old source. Third-party Python dependencies retain their upstream licenses and are listed in ChatBI `THIRD_PARTY_NOTICES.md`; no old brand, logo, UI, database dump or external credential is migrated.

## Rollback

1. In an incident only, set both modes to `off` and restart Backend; this state no longer satisfies V1 release gates.
2. Verify `/api/v1/query-capabilities` reports both paths disabled before destructive metadata rollback.
3. Run the snapshot migration script with `--rollback-batch <id>` if imported records exist.
4. Alembic downgrade the dedicated integration revision only after backing up imported optional metadata.
5. Existing P0 QueryRun/Answer/Dashboard/Evaluation records remain intact.

## Acceptance truth

The historical 120-case payload remains provenance-only and is not redistributed. Current acceptance uses the independently authored live Golden 120 plus at least 10 real Complex E2E cases. Multi-Agent PASS refers to ChatBI V1's independently implemented fixed five-role runtime, not reuse of an old complete runtime. Release requires all security counters and unauthorized access to remain 0.
