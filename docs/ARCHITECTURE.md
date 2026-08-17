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
