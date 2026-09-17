# ADR-029：受控复用旧项目二 RAG 与有限编排资产

- 状态：Superseded by ADR-030
- 日期：2026-08-17
- 决策范围：P0 已通过后的非阻断 P1 增强
- 事实基线：旧仓库 `codex/integration-4.1-full`；产品冻结提交 `b6be894a7153f7ce8d31dfc65da7222bd7af1b5f`；审计提交 `ce0764be9c92c7433fae54a62e247736708ea7e5`；RAG 基线 `81f0adadc992ae8be7897c491bc243131e52e610`

> 2026-08-17 最终产品决策已由 ADR-030 覆盖本文件中的“非阻断 P1、默认 shadow/off、Multi-Agent PARTIAL”结论。本文件只保留早期审计历史，不能作为当前 V1 配置或验收依据。

## 背景

ChatBI V2 的 P0 主链路已经有确定性的 NL2SQL、SQL AST Guard、只读执行和 Result Oracle。旧项目二则存在经过固定评测的专业知识 RAG、确定性复合查询编排、Skill Runtime、Model Gateway、RBAC 和 Audit。继续把所有 RAG/Agent 一概视为 P2，会阻止低风险复用；把旧项目整体迁入又会破坏 ChatBI-first 产品边界。

现场 Git 核验确认三项给定提交均存在且被 `codex/integration-4.1-full` 包含。该分支当前 HEAD 已前移到最终冻结提交 `b2573a9dc1881a54581c5c556fb4a8c34046f9c3`，但本 ADR 的代码与测试溯源仍固定在已审计产品提交 `b6be894...`，后续提交只用于读取最终 RC 证据。

## 决策

1. 允许专业业务知识的受控 RAG，且 ACL 必须在候选内容物化前执行，检索结果必须经过 Rerank、CitationVerifier 与 Answer Guard。
2. 允许面向复杂 ChatBI 分析的有限编排。编排只能调用显式白名单工具，必须有超时、步数和 token 预算；不得形成开放式自治 Agent 平台。
3. 普通 `DATA_QUERY` 永远优先走 ChatBI V2 自有 `Semantic Context → NL2SQL → SQL Guard → Query Executor → Result Oracle`。
4. Agent 不持有数据源连接。所有数据工具调用 ChatBI V2 的 `QueryPipeline`；所有知识工具调用 `RagAdapter`。
5. 旧运行时只通过 `LegacyRagAdapter` 或 `LegacyAgentOrchestratorAdapter` 的 HTTP 契约访问。业务代码不得 import 旧仓库内部类，也不得依赖旧仓库绝对路径或 Git Submodule。
6. 初始开关为 `CHATBI_RAG_MODE=shadow`、`CHATBI_AGENT_MODE=off`。Canary 使用稳定 trace 哈希，失败按配置回退普通问数。
7. 当前旧项目不存在完整多 Agent Runtime：没有多个自治 Agent、通用 Graph/State Machine 或可由 ChatBI 注入的 Tool Executor。因此只复用其确定性 Composite Orchestrator、Skill、Model Gateway、RBAC/Audit 的设计和契约资产，并补充最薄受控状态机；不得宣称完整 Multi-Agent 复用通过。
8. RAG/Agent 均不得成为 P0 发布门禁阻断项；开关关闭时 ChatBI V2 必须独立构建、启动、测试和发布。

## 安全不变量

- `AGENT_DIRECT_DB_ACCESS=0`
- `AGENT_SQL_GUARD_BYPASS=0`
- `AGENT_RESULT_ORACLE_BYPASS=0`
- `UNAUTHORIZED_TOOL_CALL=0`
- `CROSS_WORKSPACE_LEAK=0`
- SQL 只允许单条 `SELECT` 或 `WITH ... SELECT`，并继续受数据源/语义模型授权约束。
- 旧运行时凭据只来自 Backend 环境变量，禁止进入浏览器、日志、迁移快照或仓库。

## 范围边界

允许：Adapter、Feature Flag、Shadow、Canary、RAG 固定评测、有限状态机、必要迁移表与审计。

仍禁止：通用知识库平台、通用 Agent 管理平台、Skills 市场、复杂长期记忆与遗忘平台、跨行业 Agent、旧项目整仓复制、直接迁移旧数据库或把 RAG/Agent 设为 P0 必需依赖。

## 回滚

配置层把两项模式恢复为 `CHATBI_RAG_MODE=off`、`CHATBI_AGENT_MODE=off` 即停止新路径；数据库迁移可按 Alembic downgrade 删除本 ADR 新增的独立表，不修改现有 QueryRun、Answer、Dashboard 或评测数据。删除 Adapter 前必须先确认没有启用中的 `on/canary` 配置。

## 后果

- 正向：复用已有 RAG 质量和治理证据，同时保持 ChatBI V2 的安全、独立发布与普通问数稳定性。
- 代价：旧运行时 HTTP 契约、身份映射和许可证来源需要单独验证；完整多 Agent 能力保持 `PARTIAL/BLOCKED`，直到出现可注入 ChatBI 工具且可验证状态/步骤边界的旧运行时。
