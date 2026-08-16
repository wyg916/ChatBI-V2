# ChatBI V2 技术架构

## 1. 推荐技术栈

- Web：React、TypeScript、Vite、ECharts。
- API：FastAPI、Pydantic、SQLAlchemy、Alembic。
- Metadata DB：PostgreSQL。
- SQL 解析与方言：SQLGlot 或等价 AST 解析器。
- 模型：通过 ModelGatewayAdapter 接入 OpenAI 兼容服务、本地或第三方模型。
- 评测：IBM Text-to-SQL Evaluation Toolkit + 自研 Business Result Oracle。
- 部署：Docker Compose；CI 执行 Backend、Frontend、E2E、Golden Set。

## 2. 核心模块

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

## 3. 适配器

- SemanticEngineAdapter
- ModelProviderAdapter
- DataSourceAdapter
- NL2SQLEngineAdapter
- ChartEngineAdapter
- EvaluationAdapter

任何第三方组件只能位于适配器之后。
