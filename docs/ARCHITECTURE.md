# ChatBI V2 技术架构

## V1.3.0 Phase 2 default semantic runtime

`DATA_QUERY` remains deterministic, read-only and Oracle-verified, but semantic preparation is now an explicit replaceable chain:

`OpenChatBI selected source + ChatBI hybrid catalog linking → SuperSonic-compatible clean-room SemanticQuery → WrenAI selected source + ChatBI MDL/dry-plan bridge → SQLGlot AST Guard → EXPLAIN Cost Guard → QueryExecutor → ResultOracle → critical Verification Query`.

OpenChatBI `catalog_store.py` and WrenAI `type_mapping.py`/`wren_dialect.py` are exact pinned upstream files behind a ChatBI-owned bridge. Hybrid ranking, SuperSonic-compatible SemanticQuery, final SQL generation, Router, Model Gateway, permissions, execution, Oracle, Trace and SSE remain ChatBI-owned. Runtime evidence persists adapter, official commit, source SHA and actual call count in `QueryRun.context_payload.semantic_runtime`. Cache keys include Workspace, permission, semantic/data/knowledge/input versions and A/B mode. `CHATBI_SEMANTIC_UPSTREAM_REUSE_MODE=clean_room` retains the previous A/B path; `CHATBI_SEMANTIC_RUNTIME_MODE=local` remains the full rollback.

The controlled V1.3.0 mapping of the governing V1.2.0 Runtime Architecture, IBM GitHub-hosted self-contained Gate and SQLBot requirement exception is defined in [`docs/runtime/V1_3_RUNTIME_ARCHITECTURE_REQUIREMENT_DELTA.md`](runtime/V1_3_RUNTIME_ARCHITECTURE_REQUIREMENT_DELTA.md). The IBM job creates only an ephemeral PostgreSQL database and per-run principals, applies repository migrations and a fixed demo seed, starts the Backend on localhost, invokes the pinned selected-source evaluator, and uploads checksummed evidence. It has no production database, Provider-key, external `api_base` or long-lived repository-secret dependency.

## 1. 推荐技术栈

- Web：React、TypeScript、Vite、ECharts。
- API：FastAPI、Pydantic、SQLAlchemy、Alembic。
- Metadata DB：本机 PostgreSQL，数据库 `chatbi_v2`；应用使用项目专用账号，管理员账号只用于首次初始化。
- SQL 解析与方言：SQLGlot 或等价 AST 解析器。
- 模型：通过 `ModelProviderAdapter` 接入本地确定性语义运行时与命名的 OpenAI-compatible 服务；当前包含 Kimi `kimi-k2.6`、MiMo `mimo-v2.5`、DeepSeek `deepseek-v4-flash`，供应商差异封装在 Adapter 内。
- 评测：ChatBI 在线 clean-room comparator + Business Result Oracle；离线/CI 可从外部固定 checkout 的隔离 Python 调用 IBM 官方 Apache-2.0 selected source。GitHub Runner 仅创建一次性 PostgreSQL/认证环境并向 IBM 传递已执行结果，不向 IBM 提供数据库连接。IBM package/wheel 路径仍因 Apache/MIT metadata 冲突阻断，官方工具不得进入在线问数路径。
- 部署：Docker Compose 承载 Backend、独立 RAG Runtime 与 Frontend；开发数据库运行在本机，不创建 Docker 数据库容器或数据卷。CI 执行 Backend、Frontend、E2E、Golden Set。

## 2. 数据运行基线

- PostgreSQL 是 Day 1 以后主开发、主测试和元数据数据库；模拟经营数据位于 `chatbi_v2.demo_business`。
- MySQL 是辅助兼容数据库；同构模拟数据位于 `chatbi_demo_business`。
- 没有真实企业数据时，`database/` 中的脚本按地区、客户、产品/站点、订单、收入、成本、状态和时间生成至少 12 个月模拟数据，并实际写入本机数据库。
- 数据访问链固定为 `Frontend → Backend API → Connector → Local Database`。禁止浏览器直连 PostgreSQL/MySQL，禁止向前端下发数据库密码。
- Backend 保存的业务数据源账号必须是 `chatbi_reader` 等只读最小权限账号；本机管理员账号不得写入仓库、`.env`、日志或应用元数据库。

## 3. 核心模块

- Datasource Registry
- Metadata Catalog
- Semantic Core
- Context Builder
- NL2SQL Router
- SQL Guard
- Query Executor
- Result Oracle
- Chart Planner
- Insight Generator
- Verified Answer Library
- Dashboard
- Evaluation Center

## 4. 适配器

- SemanticEngineAdapter
- ModelProviderAdapter
- DataSourceAdapter
- NL2SQLEngineAdapter
- ChartEngineAdapter
- EvaluationAdapter
- RagAdapter / EmbeddingProvider / RerankProvider / CitationVerifier
- AgentOrchestratorAdapter / ToolExecutor
- PromptRegistry

任何第三方组件只能位于适配器之后。

外部模型密钥只允许由 Backend 环境变量提供。V1.3.0 的 `app/model_gateway/` 是 Provider Chat Completions 的唯一网络边界；General、Intent、Vision 与 NL2SQL 都必须通过同一 `RequestContext → RouterDecision → ModelRequest → ModelGateway → ModelResponse` 契约。`GET /api/v1/query-capabilities` 只返回安全的 Provider 健康、路由/预算摘要和价格版本，不返回密钥；前端不得提供密钥回显或把凭据保存到浏览器。完整约束见 [`docs/runtime/MODEL_CONTROL_PLANE.md`](runtime/MODEL_CONTROL_PLANE.md)。

MiMo 是 Balanced 普通请求的低成本默认 Provider，DeepSeek 是 NL2SQL/Structured 默认 Provider；Kimi 仅在 Quality 预算且复杂度或显式 Premium Trigger 满足时升级，Vision 可在 MiMo 失败后受控回退到 Kimi。所有价格均配置化并记录官方来源与生效日期，Provider 返回 usage 时才形成真实 Token/成本。重试、熔断、回退和取消均在 Gateway 内执行，模型思考字段不持久化。

## 5. Day 2 查询运行时

`app/query/` 保持 ChatBI 自有契约：

- `ContextBuilder` 从 Workspace、Datasource Catalog、Semantic Model、Business Term/Synonym 和 Verified SQL 构建有预算、可截断、可追踪的 `QueryContext`。
- `Nl2SqlRouter` 通过 `ModelProviderAdapter` 选择本地确定性语义运行时或 OpenAI-compatible Provider，输出强校验的 `SQLPlan`。
- `SqlGuard` 在 SQLGlot AST 上执行单语句、SELECT/CTE、Schema/Table/Column allowlist、危险函数与行数上限校验。
- `QueryExecutor` 只使用 Backend 保存的只读账号，按 PostgreSQL/MySQL 设置超时、只读事务、并发上限和结果截断。
- `ResultOracle` 独立校验执行状态、指标/维度、时间、过滤、Join、列集合、空值形状、容差值与顺序无关签名，不比较 SQL 字符串是否相等。
- `QueryRun`、`QueryAuditEvent`、`QueryFeedback` 和保存后的 `VerifiedAnswer` 均位于本机 PostgreSQL 元数据库。

浏览器仍只访问 `/api/v1`；SQL 执行连接、数据库凭据、Guard 与 Oracle 均不下放到前端。

## 6. V1 受控 RAG 与最小 Multi-Agent

`POST /api/v1/analysis` 先由确定性 Question Router 分类：

- `DATA_QUERY`：直接进入既有 `QueryPipeline`，不默认进入 Agent。
- `KNOWLEDGE_QUERY`：调用 Live `RagAdapter`，随后执行 Citation/Answer Guard；没有授权证据时失败关闭。
- `HYBRID_ANALYSIS`：只合并 Oracle 已通过的数据结果与 CitationVerifier 已通过的知识证据。
- `COMPLEX_ANALYSIS`：进入固定五角色编排；任何验证失败均不得发布未验证结论。

RAG Runtime 是当前仓库独立编写的 FastAPI 服务，通过 HMAC 签名的 Workspace、用户、角色和 Trace 身份调用。Runtime 先验证用户与 Workspace 归属，再按 `knowledge_acl` 过滤文档版本，随后召回并返回带 document/version/chunk 身份的引用；超时、签名错误、身份不一致、无授权证据均失败关闭。旧仓库生产源码复制数为 0。

契约位于根目录 `packages/`。Multi-Agent 固定为 `PlannerAgent`、`DataAnalystAgent`、`KnowledgeAgent`、`VerificationAgent`、`InsightAgent`；统一 `ToolExecutor` 只暴露 `QUERY_DATA`、`RETRIEVE_KNOWLEDGE`、`VERIFY_RESULT`、`VERIFY_CITATION`、`GENERATE_CHART`、`GENERATE_INSIGHT`。最大步骤 8、工具调用 12、重规划 2、深度 2、总超时 30 秒。Agent 不能获得数据库连接、Connector、文件、任意 URL 或动态工具；`QUERY_DATA` 始终执行 `Semantic Context → NL2SQL → SQL Guard → Query Executor → Result Oracle`。

`POST /api/v1/analysis/stream` 只流式输出 `UNDERSTANDING`、`QUERYING_DATA`、`RETRIEVING_KNOWLEDGE`、`VERIFYING`、`GENERATING_INSIGHT`、`COMPLETED` 及耗时，不输出模型思维过程。运行记录保存 TTFT、总耗时、工具耗时、角色、步骤、工具、结果签名、引用与验证状态。
