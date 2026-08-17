# ChatBI V2 技术架构

## 1. 推荐技术栈

- Web：React、TypeScript、Vite、ECharts。
- API：FastAPI、Pydantic、SQLAlchemy、Alembic。
- Metadata DB：本机 PostgreSQL，数据库 `chatbi_v2`；应用使用项目专用账号，管理员账号只用于首次初始化。
- SQL 解析与方言：SQLGlot 或等价 AST 解析器。
- 模型：通过 `ModelProviderAdapter` 接入本地确定性语义运行时与命名的 OpenAI-compatible 服务；当前包含 Kimi `kimi-k2.6`、MiMo `mimo-v2.5`、DeepSeek `deepseek-v4-flash`，供应商差异封装在 Adapter 内。
- 评测：IBM Text-to-SQL Evaluation Toolkit + 自研 Business Result Oracle。
- 部署：Docker Compose 只承载 Backend/Frontend；开发数据库运行在本机，不创建 Docker 数据库容器或数据卷。CI 执行 Backend、Frontend、E2E、Golden Set。

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

外部模型密钥只允许由 Backend 环境变量提供。`GET /api/v1/model-providers` 只返回 Provider、模型、协议、配置状态与当前路由，不返回密钥；前端不得提供密钥回显或把凭据保存到浏览器。

## 5. Day 2 查询运行时

`app/query/` 保持 ChatBI 自有契约：

- `ContextBuilder` 从 Workspace、Datasource Catalog、Semantic Model、Business Term/Synonym 和 Verified SQL 构建有预算、可截断、可追踪的 `QueryContext`。
- `Nl2SqlRouter` 通过 `ModelProviderAdapter` 选择本地确定性语义运行时或 OpenAI-compatible Provider，输出强校验的 `SQLPlan`。
- `SqlGuard` 在 SQLGlot AST 上执行单语句、SELECT/CTE、Schema/Table/Column allowlist、危险函数与行数上限校验。
- `QueryExecutor` 只使用 Backend 保存的只读账号，按 PostgreSQL/MySQL 设置超时、只读事务、并发上限和结果截断。
- `ResultOracle` 独立校验执行状态、指标/维度、时间、过滤、Join、列集合、空值形状、容差值与顺序无关签名，不比较 SQL 字符串是否相等。
- `QueryRun`、`QueryAuditEvent`、`QueryFeedback` 和保存后的 `VerifiedAnswer` 均位于本机 PostgreSQL 元数据库。

浏览器仍只访问 `/api/v1`；SQL 执行连接、数据库凭据、Guard 与 Oracle 均不下放到前端。

## 6. 受控 RAG 与有限分析编排

`POST /api/v1/analysis` 先由确定性 Question Router 分类：

- `DATA_QUERY`：直接进入既有 `QueryPipeline`，不默认进入 Agent。
- `KNOWLEDGE_QUERY`：按 RAG Feature Flag 调用 `RagAdapter`，随后执行 Citation/Answer Guard；失败可回退 `QueryPipeline`。
- `HYBRID_ANALYSIS`：合并 Oracle 已通过的数据结果与验证过的知识证据；RAG shadow 结果不向用户发布。
- `COMPLEX_ANALYSIS`：仅在路由白名单和 Agent Feature Flag 同时允许时进入有限状态机，否则回退 `DATA_QUERY`。

契约位于根目录 `packages/`，业务代码不引用冻结旧仓库的内部类或绝对路径。每次 Adapter/Tool 调用携带 Workspace、用户、角色、允许的数据源/语义模型/工具、Trace、超时、最大步数与 token 预算。Agent 只能持有 `ToolExecutor`，不能获得数据库连接或 Connector；数据工具仍执行 `Semantic Context → NL2SQL → SQL Guard → Query Executor → Result Oracle`。

旧项目二没有可验证的完整 Multi-Agent Runtime。当前 `agent-orchestrator` 是用于复杂分析的最薄确定性状态机，具备工具白名单、超时、步数和预算边界，不是通用 Agent 平台。旧 Agent HTTP Adapter 因无法注入 ChatBI `ToolExecutor` 而拒绝远程数据执行，直到兼容协议与对应安全测试补齐。
