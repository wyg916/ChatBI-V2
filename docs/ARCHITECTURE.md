# ChatBI V2 技术架构

## 1. 推荐技术栈

- Web：React、TypeScript、Vite、ECharts。
- API：FastAPI、Pydantic、SQLAlchemy、Alembic。
- Metadata DB：本机 PostgreSQL，数据库 `chatbi_v2`；应用使用项目专用账号，管理员账号只用于首次初始化。
- SQL 解析与方言：SQLGlot 或等价 AST 解析器。
- 模型：通过 ModelGatewayAdapter 接入 OpenAI 兼容服务、本地或第三方模型。
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
