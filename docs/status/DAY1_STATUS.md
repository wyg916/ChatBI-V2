# ChatBI V2 Day 1 Status

```text
VERIFIED_IMPLEMENTATION_HEAD=47161b7b59a56dfbf53a8cf054078393a473a7d8
DELIVERY_BRANCH=codex/day1-foundation-semantic-core
DELIVERY_TAG=chatbi-v2-day1-foundation-pass (created after merge gate)
DAY_1_GATE=PASS
```

## 完成模块

- FastAPI/SQLAlchemy/Alembic 模块化单体、React/TypeScript/Vite App Shell。
- PostgreSQL/MySQL Connector、只读连接测试、Schema/Table/Column/Relationship 同步。
- Semantic Model、Entity、Metric、Dimension、Relationship、Business Term、发布快照。
- LocalSemanticEngine 与隔离的 WrenSemanticAdapter seam。
- 14/14 UI 路由；问数据空态、数据源列表/详情、语义模型列表/编辑器 5/5 核心页面。

## API 与数据库

- OpenAPI：22 paths；`/health` 与 `/api/v1/version` HTTP 200。
- 元数据实体：13；Alembic 单一 head `20260816_0001`。
- 本机 PostgreSQL 为主开发/主测试数据库；本机 MySQL 为辅助兼容数据库。
- 两库模拟业务数据：各 9 表、56 字段、12 外键关系、1,095 订单、1,825 日 KPI。
- Docker 数据库服务：0；Docker 数据库卷：0。
- 前端数据链：Frontend → Backend API → Connector → Local Database。

## 语义模型

`新能源经营分析`：3 Entity、3 Metric、5 Dimension、2 Relationship、5 Business Term/Synonym；Draft 保存和 Publish 均通过真实 API 验证。

## 测试证据

- Backend Pytest：14/14 PASS；`pip check` PASS。
- Frontend TypeScript：PASS；Vitest：2 files / 5 tests PASS。
- Frontend production build：96 modules，JS 310.30 kB / gzip 99.12 kB；npm audit：0 vulnerabilities。
- Migration：本机 PostgreSQL 上 `upgrade → base → upgrade` PASS，1 head。
- Connector/Sync：PostgreSQL PASS，MySQL PASS；每源同步 9 表 / 56 字段 / 12 关系。
- Playwright：2/2 PASS；核心流程和 14 路由均实际访问。
- Viewport：1366×768、1440×900、1920×1080 无页面级横向裁切。
- 一键启动：最终镜像从停止状态连续两次 PASS；Frontend/Backend HTTP 200，两种本机数据库 READY。

## Known Gaps / Day 2 Input

- Wren runtime 尚未嵌入，Adapter 如实报告 `runtime_available=false`。
- 完整 Schema Linking、NL2SQL Router、SQL Guard、Query Executor、Result Oracle、Golden Set 属于 Day 2。
- 衍生指标依赖、复合键、MDL 跨对象校验和第二方言深化进入 Day 2。
- Day 1 未提前实现 Agent、RAG、长期 Memory、复杂 Dashboard Builder 或企业 SSO。
