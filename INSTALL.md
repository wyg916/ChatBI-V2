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
.\backend\.venv\Scripts\python.exe backend\scripts\run_day3_golden.py
```

Golden runner 必须报告冻结 SHA-256 `d40bb690a4208240ecf347abe47e045cd74c8eb89b9162d5d53890ecf24bc282`；禁止用 `--freeze` 或修改 Expected Result 来迁就失败。

## 外部模型

默认 deterministic runtime 无需外部密钥。OpenAI-compatible 配置只允许放在本机环境变量中；不得写入、提交、打印或复制 API Key。

## 可选旧 RAG 桥接与有限编排

初始配置保持 `CHATBI_RAG_MODE=shadow`、`CHATBI_AGENT_MODE=off`。旧服务 URL 和 token 只允许保存在 Git 忽略的本机 `.env` 或部署 Secret 中；前端不会接收这些值。没有配置旧服务时，ChatBI 的普通问数与构建发布不受影响。

```text
CHATBI_RAG_MODE=shadow
CHATBI_AGENT_MODE=off
CHATBI_AGENT_ALLOWED_ROUTES=
CHATBI_RAG_FALLBACK_ENABLED=true
CHATBI_AGENT_FALLBACK_ENABLED=true
CHATBI_LEGACY_RAG_BASE_URL=
CHATBI_LEGACY_RAG_TOKEN=
CHATBI_LEGACY_AGENT_BASE_URL=
CHATBI_LEGACY_AGENT_TOKEN=
```

只有在目标 Workspace、身份映射、旧 RAG ACL 和响应 Workspace 回显完成联调后，才可从 `shadow` 提升到 `canary`。旧 Agent HTTP 端点目前不能接受 ChatBI 的 `ToolExecutor` 回调，保持关闭；不得通过配置绕过这一安全限制。

离线迁移只接受已脱敏 JSON 快照，不接受旧数据库 URL，默认 dry-run：

```powershell
cd backend
.\.venv\Scripts\python.exe scripts\migrate_legacy_rag_agent_snapshot.py --snapshot tests\fixtures\legacy_migration_empty.json
```
