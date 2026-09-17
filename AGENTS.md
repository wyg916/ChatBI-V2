# ChatBI Studio 开发规则

项目是独立 ChatBI 产品。所有变更必须服务数据连接、语义建模、安全问数、结果验证、图表、答案、看板与评测。

- React / TypeScript / Vite 前端只访问 Backend API；图表使用 ECharts。
- Python / FastAPI 后端使用 PostgreSQL 元数据、SQLAlchemy 与 Alembic。
- 数据源账号最小权限；SQL 仅允许单条 SELECT 或 WITH SELECT，并执行权限、超时、行限与审计。
- RAG 与有限编排必须保持 Workspace/ACL、引用验证、固定角色、工具白名单与硬预算。
- 第三方代码经 Adapter 接入，保留来源、版本、校验和、许可证和修改说明。
- 变更前检查 Git 状态及部署依赖；变更后执行源码检查和前端构建，如实报告未验证项。
- 不提交凭据、本机数据、个人材料、构建产物或运行日志。
