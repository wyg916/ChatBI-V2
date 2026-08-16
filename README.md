# ChatBI V2

ChatBI V2 是围绕“数据源 → Schema → 语义层 → 问数 → 可验证结果”构建的开源企业级 ChatBI 产品。本仓库当前完成 Day 1 基础能力：模块化单体工程、PostgreSQL/MySQL 数据源、元数据目录、轻量语义层以及 Chat-first 前端骨架。

## 一键启动

前置条件：Windows PowerShell、Python 3.11、本机 PostgreSQL 15+、本机 MySQL 8+、Docker Desktop（仅运行 Backend/Frontend）。

```powershell
git clone https://github.com/wyg916/ChatBI-V2.git
cd "ChatBI-V2"
.\scripts\bootstrap-local-databases.ps1
.\scripts\start.ps1
```

启动完成后访问：

- 前端：<http://localhost:5173>
- API：<http://localhost:8000/api/v1/version>
- Swagger：<http://localhost:8000/docs>
- 健康检查：<http://localhost:8000/health>

```powershell
.\scripts\status.ps1
.\scripts\verify.ps1
.\scripts\stop.ps1
```

首次初始化会安全提示输入本机 PostgreSQL/MySQL 管理员口令；口令仅用于当前进程，不写入文件。脚本在本机 PostgreSQL 创建 ChatBI 元数据库与主模拟业务 Schema，并在本机 MySQL 创建辅助兼容模拟库，同时生成 Git 忽略的项目账号配置。Compose 只运行 Backend/Frontend，数据库服务数和数据库数据卷数均为 0。

仅在需要明确重建项目模拟数据时使用 `-ResetDemoData`；该开关只替换 `demo_business` / `chatbi_demo_business`，不会删除 ChatBI 元数据数据库。

模拟数据依据地区、客户、产品/站点、订单、收入、成本、状态和时间等真实经营关系生成，并实际写入数据库。前端通过 Backend API 调用这些数据，不直连数据库。PostgreSQL 是当前主开发/主测试路径，MySQL 用于辅助兼容验证。

## 工程结构

```text
frontend/     React + TypeScript + Vite
backend/      FastAPI + SQLAlchemy + Alembic
database/     本机 PostgreSQL/MySQL 可复现模拟业务数据
evaluation/   后续评测资产入口
scripts/      Windows 一键启动、停止、状态和验证
docs/         产品、架构、验收、UI 与状态文档
```

后端统一使用 `/api/v1`，语义层业务代码只依赖 ChatBI 自有 `SemanticEngine` 接口。Day 1 使用可运行的 `LocalSemanticEngine`，并保留隔离的 `WrenSemanticAdapter`；Wren runtime 深度集成属于 Day 2。

## 本地验证

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -q

cd ..\frontend
npm ci
npm run typecheck
npm test -- --run
npm run build
npm run e2e
```

完整验收与已知边界见 [`docs/status/DAY1_STATUS.md`](docs/status/DAY1_STATUS.md)。
