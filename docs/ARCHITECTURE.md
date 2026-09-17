# 技术架构

主链路：连接数据源 → 同步 Schema → 建立语义模型 → 自然语言问数 → SQL 校验与只读执行 → Result Oracle → 图表与结论 → 答案与看板。

前端为 React / TypeScript / Vite，图表使用 ECharts。FastAPI 后端通过 SQLAlchemy / Alembic 管理 PostgreSQL 元数据；前端只访问 Backend API。业务数据通过最小权限连接器读取，SQL Guard 执行 AST 校验、字段访问控制、超时和行数约束。

DATA_QUERY 经过确定性 QueryPipeline。KNOWLEDGE_QUERY 经过受控检索与 Citation Guard；HYBRID_ANALYSIS 融合已验证证据；COMPLEX_ANALYSIS 使用固定五角色、六工具的有限编排。模型调用集中于统一网关。

初始化只创建身份、工作区、工具绑定和系统提示模板。业务数据源、语义模型、知识内容和评测数据集由部署者配置。看板卡片绑定已验证答案和查询结果；刷新仍执行权限检查与结果验证。

Compose 管理 Backend、Frontend、RAG Runtime、Sandbox Controller 和 Sandbox Proxy。数据库独立部署，连接凭据仅在服务端使用。

第三方代码的版本、校验和、许可证和适配边界见 [第三方声明](../THIRD_PARTY_NOTICES.md)。
