# ChatBI V2

> 面向企业数据分析的开源 ChatBI：把自然语言问题转换为受语义层约束的只读 SQL，返回可验证结果、图表、业务洞察，并沉淀为答案和看板。

[![Release](https://img.shields.io/badge/release-v1.3.0-5b5bd6)](https://github.com/wyg916/ChatBI-V2/releases/tag/chatbi-v2-v1.3.0)
[![License](https://img.shields.io/badge/license-Apache--2.0-2f855a)](LICENSE)
[![Frontend](https://img.shields.io/badge/frontend-React%20%2B%20TypeScript-3178c6)](frontend)
[![Backend](https://img.shields.io/badge/backend-FastAPI%20%2B%20SQLAlchemy-009688)](backend)

![ChatBI V2 可验证问数结果](artifacts/chat-ui-optimization-20260819/final-integration/chat-ui-result-1440x900.png)

## 这个项目解决什么问题

传统 Text-to-SQL 只证明“生成了一条 SQL”，但企业问数真正关心的是：指标口径是否一致、SQL 是否只读、Join/时间/过滤是否正确、结果值是否可核验，以及答案能否继续沉淀和回归。

ChatBI V2 把这条链路收敛为一个可审计闭环：

```text
数据源 → Schema Catalog → 语义模型 → 自然语言问数
→ NL2SQL → SQLGlot Guard → 只读执行 → Result Oracle
→ 图表与洞察 → Verified Answer → Dashboard → Golden Evaluation
```

它不是通用 AI 平台。产品边界始终围绕 ChatBI 的正确性、安全性、可验证性和业务使用闭环。

## 适合在 7 个功能里看懂

1. **Chat-first 登录与问数据**：登录后直接进入对话式分析，不从系统后台开始。
2. **PostgreSQL / MySQL 数据源与 Schema**：连接测试、表字段关系与样例值同步。
3. **轻量语义层**：Metric、Dimension、Entity、Relationship、Business Term、Synonym。
4. **可验证自然语言问数**：Context → NL2SQL → SQL Guard → Query Executor → Result Oracle。
5. **答案结构与查询依据**：一句话结论、KPI、ECharts、洞察、明细、追问和证据抽屉。
6. **受控 RAG 与有限 Multi-Agent**：Workspace ACL、引用校验、固定五角色/六工具和硬预算 Trace。
7. **答案、看板与评测闭环**：保存 Verified Answer、生成看板卡片、运行 Golden/安全回归。

完整录屏顺序见 [Showcase 导航](docs/showcase/README.md)。

## 启动本地求职 Demo

前置条件：Windows PowerShell、Docker Desktop、本机 PostgreSQL 15+、MySQL 8+。数据库运行在本机；Docker 只运行 Backend、RAG Runtime、Sandbox Controller/Proxy 和 Frontend，不创建数据库容器或数据库 volume。

首次初始化只执行一次，管理员口令仅在当前 PowerShell 进程中使用：

```powershell
git clone https://github.com/wyg916/ChatBI-V2.git
cd ChatBI-V2
.\scripts\bootstrap-local-databases.ps1
```

之后使用根目录三个入口：

```powershell
.\一键启动-ChatBI-V2.cmd
.\一键停止-ChatBI-V2.cmd
.\一键重置-ChatBI-V2-演示数据.cmd
```

首次启动需要构建本地镜像，耗时取决于网络和机器性能；后续启动会复用镜像缓存。

也可以使用命令行：

```powershell
.\scripts\showcase.ps1 -Action Start -NoOpen
.\scripts\showcase.ps1 -Action Status
.\scripts\showcase.ps1 -Action Stop
.\scripts\showcase.ps1 -Action Reset -NoOpen
```

启动后：

- 浏览器：<http://127.0.0.1:15173/>
- API：<http://127.0.0.1:18080/api/v1/version>
- Swagger：<http://127.0.0.1:18080/docs>
- Demo 账号：`admin@chatbi.local`
- Demo 密码：`ChatBI-Showcase-2026!`

Showcase 启动器强制使用 `deterministic / LEVEL0`，不会调用付费模型；一键重置会清空并重建本机 ChatBI 元数据、演示账号和会话，保留只读业务模拟 Schema。PostgreSQL/MySQL 种子日期冻结为 `2026-08-17`，确保录屏数字可重复。

## V1.3 工程亮点

- **统一模型控制平面**：MiMo、DeepSeek、Kimi 通过同一 Model Gateway 管理能力、成本、重试、熔断、回退与 Trace；Key 只存在于 Backend 本地环境。
- **可替换语义运行时**：ChatBI 自有 Adapter 连接 Schema Linking、SemanticQuery、MDL/dry-plan、SQL Guard 和 Result Oracle。
- **安全 SQL 边界**：只允许单条 `SELECT` / `WITH ... SELECT`，限制 Schema/Table/Column、危险函数、超时、并发、行数和估算成本。
- **结果值验证**：Oracle 检查指标、维度、时间、过滤、Join、列集合、容差、结果签名、图表与叙述绑定，而不是比较 SQL 字符串。
- **受控知识与编排**：RAG 使用 HMAC 身份、Workspace/角色映射、ACL、Citation/Answer Guard；Multi-Agent 固定五角色、六工具、8 步/12 次工具/30 秒预算。
- **真实产品闭环**：会话、Streaming/取消、答案版本、看板、评测、反馈和 Verified SQL 均落在后端资源与审计边界内。
- **开源与供应链治理**：第三方能力必须经 Adapter、路径级许可证审计、锁定版本/提交和 SBOM；不复制受限品牌或商业衍生代码。

## 正式发布事实

V1.3.0 的 annotated tag `chatbi-v2-v1.3.0` 固定指向：

```text
52db955fd67ebe592c289399a135528c13cb3e3d
```

[GitHub Release](https://github.com/wyg916/ChatBI-V2/releases/tag/chatbi-v2-v1.3.0) 记录了 DATA100、三 Provider、真实多模态、远端 Phase 3/4/5 和 Phase 6 审计结果。该 Release 是开源源码发布，不是生产部署认证；本 README 后续的 Showcase 文档和本地脚本属于 **POST_RELEASE** 维护提交，不移动 V1.3.0 tag。

## 项目结构

```text
frontend/          React + TypeScript + Vite + ECharts
backend/           FastAPI + SQLAlchemy + Alembic + SQLGlot
packages/          RAG、有限编排、Prompt 与上游 Adapter 契约
database/          本机 PostgreSQL/MySQL 的可复现模拟业务数据
evaluation/        Golden、复杂分析、文件/多模态与安全用例
sandbox_runtime/   受限 Python/Docker 执行边界
scripts/           初始化、Showcase、验证与发布门禁
docs/showcase/     录屏、面试与本地演示材料
```

## 深入阅读

- [本地 Demo 操作手册](docs/showcase/DEMO_RUNBOOK.md)
- [3～5 分钟视频脚本](docs/showcase/VIDEO_SCRIPT_3_TO_5_MIN.md)
- [8～10 分钟视频脚本](docs/showcase/VIDEO_SCRIPT_8_TO_10_MIN.md)
- [面试讲解稿](docs/showcase/INTERVIEW_TALK_TRACK.md)
- [技术架构](docs/ARCHITECTURE.md)
- [运行时与模型控制面](docs/runtime/MODEL_CONTROL_PLANE.md)
- [V1.3.0 Release Notes](docs/releases/V1_3_0_RELEASE_NOTES.md)
- [第三方声明](THIRD_PARTY_NOTICES.md)

## 本地验证

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -q

cd ..\frontend
npm ci
npm run typecheck
npm test -- --run
npm run build
```

完整发布门禁、许可证、远端 CI 和生产部署要求与求职 Demo 分离。当前维护模式只接受 Showcase 稳定性、文档和安全修复，不启动 V1.4、V2.0 或 Production Deployment。
