# ChatBI V2 V1.0.0 Release Notes

ChatBI V2 是一个 Chat-first、可验证、可独立部署的开源企业级问数产品。V1.0.0 完成从数据源连接到持续评测的完整主链路，并以结果值正确性与只读安全作为发布门禁。

## 核心能力

- PostgreSQL 主数据源与 MySQL 兼容数据源连接、测试、Schema 同步和样例值浏览。
- Entity、Metric、Dimension、Relationship、Business Term 与 Synonym 组成的轻量语义层，支持不可变发布版本和回滚生成新版本。
- Context Builder、可替换 NL2SQL Provider、强类型 SQLPlan、SQLGlot AST Guard、只读 Query Executor 与 Result Oracle。
- 一句话结论、KPI、ECharts 图表、证据绑定洞察、明细表和推荐追问。
- Verified Answer、Answer Version、Dashboard Card 与可刷新来源链。
- Golden 50 Evaluation、Case Detail、Expected/Actual/SQL/ResultDiff。
- Kimi、MiMo、DeepSeek 命名 Provider；凭据仅由 Backend 环境变量读取，默认发布路径保持 deterministic。
- ADMIN/ANALYST 最小 RBAC、资源授权和查询/同步/发布/评测/拒绝审计。

## 产品页面与安装

V1 包含登录、问数据空态/结果、数据源列表/详情、语义模型列表/编辑器、答案库、看板列表/详情、评测中心/详情、模型设置与安全审计共 14 个页面，并通过 1440×900、1366×768、1920×1080 验收。

Windows 用户完成本机 PostgreSQL/MySQL 初始化后，可双击 `一键启动-ChatBI-V2.cmd`。完整前置条件、环境变量和验证命令见 `README.md`、`INSTALL.md` 与 `docs/MODEL_PROVIDERS.md`。

## 质量与安全

- Golden PostgreSQL：SQL/结果/语义 50/50；MySQL 10/10。
- 危险 SQL：38/38 阻断，实际写入成功 0。
- Backend 121/121、Frontend Vitest 27/27；Serial E2E 50/50、5 workers Parallel E2E 50/50，retries=0。
- Live RAG Golden 120/120，Recall@10 1.0，Citation Accuracy 1.0，越权检索 0；Complex Analysis 10/10，Trace 完整率 100%。
- 三模型 Final Smoke 均通过 Discovery、认证、Chat、SQLPlan 与 SQL Guard。
- 从停止状态的两次隔离 metadata 冷启动与 Day4→Final 回滚恢复模拟通过。

最终 Backend、Frontend、Migration、两次一键启动、Git/Tag 数字以 `docs/releases/V1_FINAL_MANIFEST.md` 与 `docs/status/DAY5_STATUS.md` 为准。

## V1 受控 RAG 与最小 Multi-Agent

V1 含默认启用的专业知识 Live RAG Bridge 与固定五角色、六工具的复杂分析编排。RAG 使用签名 Workspace 身份、ACL、Citation/Answer Guard；Agent 数据工具全部经过 SQL Guard、Query Executor 与 Result Oracle。旧项目来源待补证的 120 条 payload 不在公开发行包中，当前 Golden 120 为独立编写并对 live bridge 实跑。

## Known Limitations

- ECharts 为独立懒加载 chunk，压缩前约 555.48 kB，仍触发 Vite 500 kB 提示，但不增加首屏主入口体积。
- V1 仅提供最小 ADMIN/ANALYST RBAC，不包含完整 SSO/OIDC/Vault 平台。
- V1 仅提供 ChatBI 专用的有界五角色编排，不提供通用 Agent 平台、动态工具市场或开放式自治循环。
- 外部模型受供应商网络、配额、价格和数据政策影响；默认演示与发布回归使用 deterministic Runtime。
