# ChatBI V2 安装与验证

## 前置条件

- Windows PowerShell 7+
- Docker Desktop
- Python 3.11
- 本机 PostgreSQL 15+ 与 MySQL 8+
- Node.js 20+（仅开发与测试需要）

数据库保存在本机服务中；Compose 只启动 Backend 与 Frontend，不创建数据库容器或数据库卷。

## 首次安装

```powershell
git clone https://github.com/wyg916/ChatBI-V2.git
cd "ChatBI-V2"
.\scripts\bootstrap-local-databases.ps1
.\scripts\start.ps1
```

初始化脚本会交互式请求本机数据库管理员口令，只用于当前进程创建最小权限账号与可复现模拟数据，不写入仓库。运行时 `.env` 被 Git 忽略，前端只通过 Backend API 访问数据。

访问地址：

- Web：<http://localhost:5173>
- API：<http://localhost:8000/api/v1/version>
- Swagger：<http://localhost:8000/docs>

## 日常操作

```powershell
.\scripts\status.ps1
.\scripts\verify.ps1
.\scripts\stop.ps1
.\scripts\start.ps1
```

只有明确需要重建模拟业务数据时才运行：

```powershell
.\scripts\bootstrap-local-databases.ps1 -ResetDemoData
```

该选项只重建演示业务 Schema/库，不应被用于清空 ChatBI 元数据。

## 开发验收

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pip check

cd ..\frontend
npm ci
npm run typecheck
npm test -- --run
npm run build
npx playwright test --workers=1

cd ..
.\backend\.venv\Scripts\python.exe backend\scripts\run_day4_golden.py
```

Golden runner 必须报告冻结 SHA-256 `25580af42bc76ebddd3d49e6b9c16f8bfabba8ba485a835c453c29175ee2a64a`，PostgreSQL 50/50、MySQL 兼容集 10/10；禁止修改 Expected Result 来迁就失败。

## 外部模型

默认 deterministic runtime 无需外部密钥。OpenAI-compatible 配置只允许放在本机环境变量中；不得写入、提交、打印或复制 API Key。

## V1 Live RAG Bridge 与最小 Multi-Agent

本机数据库初始化会在 Git 忽略的 `.env` 生成 `CHATBI_RAG_SHARED_SECRET`；前端不会接收该值。Compose 启动 Backend、独立 `rag-runtime` 和 Frontend，PostgreSQL/MySQL 仍使用本机服务，不创建数据库容器或数据卷。

```text
CHATBI_RAG_MODE=on
CHATBI_AGENT_MODE=on
CHATBI_AGENT_ALLOWED_ROUTES=COMPLEX_ANALYSIS
CHATBI_RAG_FALLBACK_ENABLED=true
CHATBI_AGENT_FALLBACK_ENABLED=true
CHATBI_LEGACY_RAG_BASE_URL=http://rag-runtime:8001
CHATBI_RAG_SHARED_SECRET=<GENERATED_LOCAL_RAG_BRIDGE_SIGNING_KEY>
CHATBI_AGENT_TIMEOUT_MS=30000
CHATBI_AGENT_MAX_STEPS=8
CHATBI_AGENT_MAX_TOOL_CALLS=12
CHATBI_AGENT_MAX_REPLAN=2
CHATBI_AGENT_MAX_DEPTH=2
```

`GET /api/v1/query-capabilities` 必须显示 live bridge、签名身份映射和五角色编排均可用。`off/shadow/canary` 只用于诊断或事故回滚，不满足 V1 发布门禁。

离线迁移只接受已脱敏 JSON 快照，不接受旧数据库 URL，默认 dry-run：

```powershell
cd backend
.\.venv\Scripts\python.exe scripts\migrate_legacy_rag_agent_snapshot.py --snapshot tests\fixtures\legacy_migration_empty.json
```
