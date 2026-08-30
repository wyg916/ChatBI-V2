# ADR-030：受控 RAG 与最小 Multi-Agent 纳入 V1/P0

- 状态：Accepted
- 日期：2026-08-17
- 取代：ADR-029 中“非阻断 P1、默认 shadow/off、Multi-Agent PARTIAL”的产品结论

## 决策

受控专业知识 RAG 和面向复杂 ChatBI 分析的最小 Multi-Agent 均为 V1/P0 发布必选能力。二者必须默认 `on`、通过真实运行时门禁，并继续服从 ChatBI-first 边界；通用 RAG 平台、通用 Agent 平台、动态 Tool/Skill 市场和长期记忆仍属 P2 禁止范围。

四条路由冻结为：

1. `DATA_QUERY` 只进入 ChatBI `QueryPipeline`。
2. `KNOWLEDGE_QUERY` 进入 Live RAG Bridge，并经过 Citation/Answer Guard。
3. `HYBRID_ANALYSIS` 只融合 Result Oracle 已通过的数据证据与 CitationVerifier 已通过的知识证据。
4. `COMPLEX_ANALYSIS` 进入固定五角色、六工具的有限编排。

## RAG 运行边界

- 当前仓库独立实现 RAG Runtime，不复制旧项目二生产源码；旧源码复制数必须为 0。
- Backend 与 Runtime 通过 HMAC 签名传递 Workspace、用户、角色、Trace 和工具范围；服务端再次核验数据库中的用户归属与角色。
- ACL 在引用物化前过滤。引用必须包含 document、version、chunk、source 与 locator。
- 健康检查、超时、最多一次重试、Workspace 回显和失败关闭均为强制门禁。
- 历史 120 条用例只保留来源与哈希，不再分发；当前仓库用独立编写的 Golden 120 对 live bridge 执行 Recall@10、Citation Accuracy 与越权测试。

## Multi-Agent 运行边界

角色固定为 `PlannerAgent`、`DataAnalystAgent`、`KnowledgeAgent`、`VerificationAgent`、`InsightAgent`。工具固定为 `QUERY_DATA`、`RETRIEVE_KNOWLEDGE`、`VERIFY_RESULT`、`VERIFY_CITATION`、`GENERATE_CHART`、`GENERATE_INSIGHT`。

最大步骤 8、工具调用 12、重规划 2、Agent 深度 2，Deterministic/Level0 总超时 30 秒；本机 Auto/Live 三家受控 Provider 的 120 秒有限例外及其绝对 deadline 传播由 ADR-099 约束。禁止动态工具、Agent 直连数据库、绕过 SQL Guard/Result Oracle、文件访问和任意网络工具。只允许发布已验证结果；RAG 不可用时可降级为已验证的数据结论，但必须显式标记 `PARTIAL`，不得伪造引用。

## Prompt 与元数据

V1 固定六个独立编写并版本化的 Prompt：`rag.query_rewrite`、`rag.citation`、`analysis.hybrid`、`agent.planner`、`agent.verification`、`agent.insight`。每个版本保存 source、purpose 和 SHA-256 checksum。

0007 引入的 15 张表全部保留：10 张由知识、ACL、Prompt、Profile 和 Tool Binding 种子使用；5 张 Retrieval/Citation/Orchestration/Step/ToolCall 表只由真实运行写入，不生成虚假证据。0008 仅补充预算、性能、Trace 完整性和 Prompt 来源字段。

## 发布门禁

V1 必须同时通过 Backend、Frontend、串并行 E2E、Golden 50、RAG Golden 120、至少 10 条真实 Complex E2E、PostgreSQL/MySQL、RBAC/审计/迁移/许可证/Secret/UI14、两次冷启动与命名 Provider live smoke。任一项失败时不得提交、合并、推送或打 `chatbi-v2-v1.0.0` 标签。

## 回滚

紧急回滚可临时把两项模式设为 `off` 以阻断新流量，但这会使系统不再满足 V1 完成定义，只能作为事故处置，不是可发布配置。数据回滚先停流量，再按批次删除运行元数据或将 Alembic 降级；现有 QueryRun、Answer、Dashboard 和 Evaluation 数据不得被覆盖。
