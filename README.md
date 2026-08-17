# ChatBI V2

ChatBI V2 是围绕“数据源 → Schema → 语义层 → 问数 → 可验证结果 → 图表与洞察 → 答案 → 看板 → 评测”构建的开源企业级 ChatBI 产品。V1.0.0 已实现完整、可验证的产品闭环；最终发布 Gate 以 [`docs/status/DAY5_STATUS.md`](docs/status/DAY5_STATUS.md) 为准。

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
packages/     RAG、有限编排与 Prompt 的独立契约/Adapter 包
database/     本机 PostgreSQL/MySQL 可复现模拟业务数据
evaluation/   冻结 Golden Set 与评测资产
scripts/      Windows 一键启动、停止、状态和验证
docs/         产品、架构、验收、UI 与状态文档
```

后端统一使用 `/api/v1`，语义层业务代码只依赖 ChatBI 自有 `SemanticEngine` 接口。当前使用可运行的 `LocalSemanticEngine`，并保留隔离且如实报告不可用的 `WrenSemanticAdapter` seam；Day 2 主链路不依赖未配置的 Wren runtime。

## V1 产品闭环

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
- `POST /api/v1/analysis`
- `POST /api/v1/analysis/stream`

## V1 受控 RAG 与最小 Multi-Agent

普通问数继续使用现有确定性 NL2SQL 主链路。专业知识检索通过 HMAC 签名的 Live RAG Bridge、Workspace ACL、Citation/Answer Guard；复杂分析使用固定五角色和六工具的有界编排。Agent 不持有数据源连接，数据工具仍必须经过 SQL Guard、Query Executor 和 Result Oracle。

```text
CHATBI_RAG_MODE=on
CHATBI_AGENT_MODE=on
CHATBI_AGENT_ALLOWED_ROUTES=COMPLEX_ANALYSIS
CHATBI_RAG_FALLBACK_ENABLED=true
CHATBI_AGENT_FALLBACK_ENABLED=true
```

模式仍支持 `off|shadow|canary|on` 供诊断和事故处置，但 V1 发布默认必须为 `on`。RAG 运行时和五角色编排均由当前仓库独立实现，旧项目生产源码复制数为 0；通用 Agent/RAG 平台继续禁止。详见 [`ADR-030`](docs/decisions/ADR_030_RAG_MULTIAGENT_V1_REQUIRED.md)。

## 本地验证

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts\run_day4_golden.py

cd ..\frontend
npm ci
npm run typecheck
npm test -- --run
npm run build
npm run e2e
```

Golden 50 冻结清单位于 [`evaluation/golden/day4-golden-50.json`](evaluation/golden/day4-golden-50.json)。完整安装说明见 [`INSTALL.md`](INSTALL.md)，15 分钟演示见 [`DEMO.md`](DEMO.md)，发布说明见 [`RELEASE_NOTES_V1.md`](RELEASE_NOTES_V1.md)，许可证与第三方声明见 [`LICENSE`](LICENSE) 和 [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)。
