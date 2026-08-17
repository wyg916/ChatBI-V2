# ChatBI V2

ChatBI V2 是围绕“数据源 → Schema → 语义层 → 问数 → 可验证结果 → 图表与洞察 → 答案 → 看板 → 评测”构建的开源企业级 ChatBI 产品。V1 RC 候选已实现完整的真实产品闭环；当前发布 Gate 与未完成项以 [`docs/status/DAY3_STATUS.md`](docs/status/DAY3_STATUS.md) 为准。

## 一键启动

前置条件：Windows PowerShell、Python 3.11、本机 PostgreSQL 15+、本机 MySQL 8+、Docker Desktop（仅运行 Backend/Frontend）。

完成首次数据库初始化后，直接双击仓库根目录的 `一键启动-ChatBI-V2.cmd`。它会检查 Docker Desktop、构建并启动 Backend/Frontend、验证 PostgreSQL/MySQL 数据源，然后自动打开 <http://localhost:5173>。启动失败时窗口会保留错误提示，不会 reset、提交或修改当前 Git 工作树。

```powershell
git clone https://github.com/wyg916/ChatBI-V2.git
cd "ChatBI-V2"
.\scripts\bootstrap-local-databases.ps1
.\一键启动-ChatBI-V2.cmd
```

命令行启动仍可使用 `.\scripts\start.ps1`；自动化检查可使用 `.\scripts\launch.ps1 -NoOpen`，已确认镜像无需重建时可再加 `-SkipBuild`。

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
  evaluation/   冻结 Golden Set 与评测资产
scripts/      Windows 一键启动、停止、状态和验证
docs/         产品、架构、验收、UI 与状态文档
```

后端统一使用 `/api/v1`，语义层业务代码只依赖 ChatBI 自有 `SemanticEngine` 接口。当前使用可运行的 `LocalSemanticEngine`，并保留隔离且如实报告不可用的 `WrenSemanticAdapter` seam；Day 2 主链路不依赖未配置的 Wren runtime。

## V1 RC 产品闭环

```text
自然语言问题
→ Schema Linking / QueryContext
→ Nl2SqlRouter / SQLPlan
→ SQLGlot AST Guard
→ PostgreSQL/MySQL 只读执行
→ Result Oracle
→ 受控 ChartSpec / ECharts
→ 证据绑定 Narrative / 推荐追问
→ Verified Answer / AnswerVersion
→ Dashboard Card
→ Golden Evaluation / Case Detail
```

默认 `CHATBI_MODEL_PROVIDER=deterministic` 使用基于语义对象与通用分析意图的本地运行时，不使用“完整问题 → 固定 SQL”字典。可选 OpenAI-compatible Provider 仅通过环境变量配置：

```text
CHATBI_MODEL_PROVIDER=openai-compatible
CHATBI_MODEL_BASE_URL=https://provider.example/v1
CHATBI_MODEL_API_KEY=<LOCAL_SECRET_ONLY>
CHATBI_MODEL_NAME=<MODEL_NAME>
```

API Key 不得写入仓库。没有配置外部模型时，本地运行时仍可完成完整真实查询链路。

核心 API：

- `POST /api/v1/ask`
- `GET /api/v1/queries/{id}`
- `POST /api/v1/queries/{id}/verify`
- `POST /api/v1/queries/{id}/feedback`
- `POST /api/v1/queries/{id}/save`
- `GET /api/v1/answers/{id}`
- `POST /api/v1/answers/{id}/reuse`
- `POST /api/v1/dashboards/{id}/cards`
- `POST /api/v1/evaluation/runs`
- `GET /api/v1/evaluation/cases/{case_id}`
- `GET /api/v1/query-capabilities`

## 本地验证

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts\run_day3_golden.py

cd ..\frontend
npm ci
npm run typecheck
npm test -- --run
npm run build
npm run e2e
```

Golden 20 冻结清单位于 [`evaluation/golden/day2-golden-20.json`](evaluation/golden/day2-golden-20.json)，V1 RC 候选验收结果见 [`docs/status/DAY3_STATUS.md`](docs/status/DAY3_STATUS.md)，15 分钟演示见 [`DEMO.md`](DEMO.md)，完整安装说明见 [`INSTALL.md`](INSTALL.md)。
