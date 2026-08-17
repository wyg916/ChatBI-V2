# 旧项目二 RAG 与有限编排迁移 Manifest

## 决策摘要

| capability | disposition | source | target | reason |
|---|---|---|---|---|
| RAG runtime | REUSE_BY_HTTP | `b6be894:backend/app/knowledge/` | `LegacyRagAdapter` | 已有 120 条固定评测；先桥接避免重写 |
| RAG contracts | REIMPLEMENT_AS_OWN_CONTRACT | legacy DTO behavior | `packages/rag-contracts` | 消除旧 ORM/身份/场景耦合 |
| Composite orchestration | REUSE_DESIGN_AND_CONTRACT | `CompositeQueryOrchestrator` | `packages/agent-orchestrator` | 旧实现不是多 Agent 且直接耦合旧 ChatBI |
| Legacy agent HTTP | ADAPTER_FAIL_CLOSED | `/api/v1/assistant/query` | `LegacyAgentOrchestratorAdapter` | 端点不能接受 ChatBI V2 ToolExecutor callback；在兼容协议出现前始终拒绝远程执行 |
| Tool/Skill runtime | SELECTIVE_CONTRACT_REUSE | `SkillExecutor`, registries | `ToolExecutor`, `tool_binding` | 只保留白名单、运行/步骤、审计，不迁行业 Skill |
| Model Gateway | DESIGN_REUSE | `backend/app/ai/model_gateway/` | 现有 ModelProvider Adapter | ChatBI 已有命名 Provider，不复制第二套网关 |
| RBAC/Audit | FIELD/POLICY_MAPPING | legacy authorization/audit | `core/access.py`, new run tables | 以 ChatBI workspace/grant 为权威 |
| Prompt | MINIMAL_VERSIONED_REGISTRY | dispersed legacy prompts | `packages/prompt-registry`, prompt tables | 只建设 ChatBI 所需版本解析，不做市场 |
| Golden fixtures | PROVENANCE_ONLY_NOT_DISTRIBUTED | 60+60 JSON | `evaluation/legacy-rag/SOURCE.json` | 仅保留 source commit/blob/hash/count；许可证补证前不公开 payload |
| Legacy database | SNAPSHOT_ONLY | selected listed tables | new local PostgreSQL | 不连、不写、不搬全库 |

## 路由与开关

| route | primary path | shadow behavior | fallback |
|---|---|---|---|
| DATA_QUERY | existing `QueryPipeline` | none | n/a |
| KNOWLEDGE_QUERY | `LegacyRagAdapter.retrieve` when selected by flag | execute and audit without publishing RAG answer | existing `QueryPipeline` when enabled |
| HYBRID_ANALYSIS | `QueryPipeline` + RAG + Evidence Merger | RAG evidence is non-user-visible | retain Oracle-passed data result |
| COMPLEX_ANALYSIS | bounded state machine + allowlisted `ToolExecutor` | audit candidate only | DATA_QUERY |

Defaults: `CHATBI_RAG_MODE=shadow`, `CHATBI_AGENT_MODE=off`, both fallbacks enabled. `DATA_QUERY` never routes to Agent unless a caller explicitly requests another route and the route is allowed.

## Security context contract

Every Adapter/tool request carries `workspace_id`, `user_id`, `roles`, `allowed_datasources`, `allowed_semantic_models`, `allowed_tools`, `trace_id`, `timeout`, `max_steps`, and `token_budget`. Empty allowlists fail closed. Agent code receives no connection URL or connector object. Data tools accept an `AskRequest` and invoke the existing `QueryPipeline`; successful tool results must show SQL Guard allowed and Result Oracle passed before evidence can be merged.

## Data migration

Only these target tables are allowed: `knowledge_source`, `knowledge_document`, `knowledge_document_version`, `knowledge_chunk`, `knowledge_acl`, `knowledge_ingestion_run`, `knowledge_retrieval_run`, `citation`, `orchestration_profile`, `orchestration_run`, `orchestration_step`, `tool_binding`, `tool_call`, `prompt_template`, `prompt_version`.

Migration input is an offline sanitized JSON snapshot with `source_commit` and `migration_batch_id`; the script defaults to dry-run and never accepts an old database URL. Apply writes only the new metadata database. Rollback deletes one named batch from the new tables in reverse dependency order. No existing ChatBI core table is overwritten.

## History and source extraction

The bridge contains no copied legacy production source, so no source-history rewrite is required for the first stage. Golden fixture payloads are not distributed; only their source commit, blob IDs, case counts and SHA-256 provenance are retained. A later source extraction may use a temporary clone plus `git filter-repo --path backend/app/knowledge` or a subtree-split branch only after (1) bridge validation, (2) ownership/license proof, and (3) dependency-cut analysis. It must never mutate the frozen source repository or introduce a submodule/absolute-path dependency.

## License gate

The old repository has no root LICENSE or `THIRD_PARTY_NOTICES.md`. Direct legacy source extraction is therefore blocked for open-source release until ownership/provenance is documented. HTTP interoperability and independently authored ChatBI contracts do not copy old source. Third-party Python dependencies retain their upstream licenses and are listed in ChatBI `THIRD_PARTY_NOTICES.md`; no old brand, logo, UI, database dump or external credential is migrated.

## Rollback

1. Set both modes to `off` and restart Backend.
2. Verify `/api/v1/query-capabilities` reports both optional routes disabled.
3. Run the snapshot migration script with `--rollback-batch <id>` if imported records exist.
4. Alembic downgrade the dedicated integration revision only after backing up imported optional metadata.
5. Existing P0 QueryRun/Answer/Dashboard/Evaluation records remain intact.

## Acceptance truth

The public bridge can pass only after current contract/security tests pass and the provenance gate proves the 120 internal cases are not redistributed. The historical 120-case result remains reference-only until ownership/license evidence permits a reproducible public fixture. Multi-Agent reuse cannot pass from the current asset set; the highest honest status is PARTIAL because the old runtime is a deterministic composite orchestrator without a compatible injected-tool protocol, general graph, loop guard, or multi-agent tests.
