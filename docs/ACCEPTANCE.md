# ChatBI V2 验收标准

V1.0.1 Final Release 的本次执行报告见 [`docs/status/DAY5_STATUS.md`](status/DAY5_STATUS.md) 与 [`docs/releases/V1_FINAL_MANIFEST.md`](releases/V1_FINAL_MANIFEST.md)。只有 Final Manifest 中的功能、正确性、安全、迁移、冷启动、两次正式启动、回滚和 Git 发布 Gate 全部通过，才允许创建新的 annotated Final Tag；既有公开 `chatbi-v2-v1.0.0` 不得移动。Day 3 RC 历史报告保留在 [`docs/ACCEPTANCE_REPORT_V1_RC.md`](ACCEPTANCE_REPORT_V1_RC.md)。

## 产品主链路

- 数据源连接、Schema 同步、语义模型发布、自然语言问数、SQL 校验、查询执行、结果验证、图表、洞察、答案保存、看板和评测全部可用。

## 安全

- 只读账号、单语句、SELECT/CTE allowlist、超时、行数限制、敏感字段控制和完整审计。
- DDL、DML、多语句、系统表越权、文件访问和外部程序全部被拒绝。

## 质量

- Day 3：Golden 20；SQL 执行成功率 ≥95%；结果准确率 ≥90%。
- Day 5：Golden 50；SQL 执行成功率 ≥98%；结果准确率 ≥95%。
- Backend、Frontend、E2E、Migration、Docker 连续启动全部 PASS。
- 浏览器 console error、page error、blocking request failure 为 0。
- Docker Compose 中数据库服务数为 0；项目数据实际存在本机 PostgreSQL/MySQL。
- PostgreSQL 主验证链必须 PASS；MySQL 辅助连接与 Schema 同步必须 PASS。

## V1 RAG 与有限 Multi-Agent

- 专业知识 RAG 与面向复杂分析的有限 Multi-Agent 均为 V1/P0 必选，发布默认必须为 `on`。
- 只允许 `DATA_QUERY`、`KNOWLEDGE_QUERY`、`HYBRID_ANALYSIS`、`COMPLEX_ANALYSIS` 四种路由；普通问数保持 QueryPipeline fast path。
- RAG Golden 至少 120 条，Recall@10 与 Citation Accuracy 均不低于 0.95，越权检索必须为 0。
- 编排固定五角色、六个 allowlisted 工具；步骤不超过 8、工具调用不超过 12、重规划不超过 2、深度不超过 2。发布回归与 `Deterministic`/`Level0` 总超时不超过 30 秒；仅本机 Showcase 的 `Auto`/`Live` 模式在已明确授权 MiMo、DeepSeek、Kimi 真实回退时允许最长 120 秒，且仍使用同一个绝对截止时间，不得扩展到生产发布门禁或其他 Provider。
- Agent 直连数据库、未知工具、SQL Guard 绕过、Result Oracle 绕过、RBAC 绕过、无限循环和无界工具调用均必须为 0。
- Complex Analysis 真实 E2E 至少 10/10，Trace 完整率 100%；长任务仅流式输出公开阶段，不输出内部推理。

## UI

- 1440×900 为设计基准；1366×768 与 1920×1080 可用。
- 六个一级模块导航清楚；问数据为默认首页。
- SQL 和技术细节折叠展示；业务结论优先。

## 工程

- 工作树 clean；主仓库唯一；无重复 clone、长期 worktree 和未说明 stash。
- 文档、迁移、测试、许可证和一键启动脚本齐全。
- 前端只能通过 Backend API 访问数据库；任何前端直连数据库或暴露数据库凭据均为 FAIL。

## V1.3.0 Phase 1 三模型统一控制平面

- Backend 运行时代码中 Provider Chat Completions HTTP 调用平面必须恰好为 1，General、Intent、Vision、NL2SQL 不得各自直连 Provider。
- MiMo、DeepSeek、Kimi 必须使用配置化 Alias/Model、能力矩阵和官方来源价格；不得把 Key、Authorization Header、Provider 错误正文或思考内容写入 Trace、Evidence、Git、Markdown/JSON 报告。
- Balanced 普通请求默认 MiMo；NL2SQL 默认 DeepSeek；Kimi 仅在 Quality/Premium 资格或受控 Vision 回退下调用。预算超限、Provider 401/403/429/额度不足或无效 Key 必须真实失败或按策略回退，不得伪造 PASS。
- “今天是几号/星期几”必须 `MODEL=NONE`；无关语境的“收入”不得进入 DATA_QUERY；跨会话响应、缓存和消息绑定错误必须为 0。
- Chat、Analysis、Query 和 SSE 必须共用同一 `trace_id/request_id`，缓存键必须包含 Workspace、权限与上下文版本边界。
- Phase 0.6 开发门禁使用 `CURRENT_DEV_KEYS_AUTHORIZED=YES`、`THREE_MODEL_SECRET_CONFIGURATION=PASS`、`SECRET_LEAK_IN_EVIDENCE=0`、`SECRET_LEAK_IN_GIT=0`。三组 Key 轮换只作为 V1.3.0 Final Release/生产/公开切流的强制 Gate。

## V1.3.0 Phase 2 数据主链与真实上游能力

- OpenChatBI/WrenAI 只有在官方 commit、selected path、Git blob/SHA-256、路径许可证、import closure、真实 Trace 调用数、关闭开关和 rollback 全部可复验时才计为直接复用；clean-room/命名兼容不得计数。
- DATA_QUERY 保持唯一 ChatBI Router、Model Gateway、SQLGlot→EXPLAIN→QueryExecutor→ResultOracle、Trace 与 SSE；上游不得直连 Provider 或数据库。
- A/B 固定同一数据库、Schema、Golden、模型/Prompt、权限与 Workspace，必须完成 Golden 50 + 复杂 20 的真实结果值比较；执行成功率不低于 0.98、结果准确率不低于 0.95、Catalog Recall@5 不低于 0.95。
- 关键指标/多 Join 的 Verification Query 执行率必须为 1.0；危险 SQL 执行、跨 Workspace recall/replay 和 Guard bypass 必须为 0。
- IBM/SQLBot 的每一种接入模式必须独立闭合许可证和依赖。未闭合的 package/service 模式 official runtime calls 必须为 0；具明确路径许可证、固定 commit/SHA、隔离依赖和真实函数调用证据的 selected-source 模式可单独计数。任何仍阻断的目标项都会使 Phase 2 保持 PARTIAL/BLOCKED；不得用 ChatBI clean-room 替代品宣称官方 PASS。
