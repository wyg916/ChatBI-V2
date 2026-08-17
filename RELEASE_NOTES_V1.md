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
- Serial E2E 36/36；5 workers 并行两轮 72/72，retries=0。
- 三模型 Final Smoke 均通过 Discovery、认证、Chat、SQLPlan 与 SQL Guard。
- 隔离 metadata 冷启动与 Day4→Final 回滚恢复模拟通过。

最终 Backend、Frontend、Migration、两次一键启动、Git/Tag 数字以 `docs/releases/V1_FINAL_MANIFEST.md` 与 `docs/status/DAY5_STATUS.md` 为准。

## 可选受控增强

V1 含默认关闭/Shadow 的专业知识 RAG HTTP Adapter 与有限编排契约。它们不替代普通问数主链路，不允许 Agent 直连数据库，也不构成通用 Agent/RAG 平台。旧项目来源待补证的 120 条 RAG payload 不在公开发行包中。

## Known Limitations

- ECharts 为独立懒加载 chunk，压缩前约 555.48 kB，仍触发 Vite 500 kB 提示，但不增加首屏主入口体积。
- V1 仅提供最小 ADMIN/ANALYST RBAC，不包含完整 SSO/OIDC/Vault 平台。
- 可选旧 Agent HTTP 端点不支持注入 ChatBI ToolExecutor，因此保持关闭；完整 Multi-Agent Runtime 不属于 V1。
- 外部模型受供应商网络、配额、价格和数据政策影响；默认演示与发布回归使用 deterministic Runtime。
