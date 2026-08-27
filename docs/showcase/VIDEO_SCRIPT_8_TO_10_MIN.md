# 8～10 分钟视频脚本

目标时长：9 分钟。按“业务问题 → 产品闭环 → 工程约束 → 结果沉淀”的顺序讲，不按代码目录逐个念。

## 0:00～0:45 项目定位

- 展示 README 和正式 Release。
- 说明 V1.3.0 tag 固定在 `52db955…`，本地 Demo 是 POST_RELEASE 维护，不是生产部署。
- 一句话定位：让业务用户用自然语言获得可验证的数据答案，而不是只生成 SQL。

讲解重点：

> 企业问数难点不在于 SQL 语法，而在于口径、权限、Join、时间、只读安全、结果值和可复现评测。ChatBI V2 的架构围绕这些不确定性设计。

## 0:45～1:25 功能 1：登录与产品信息架构

- 登录，展示六个一级模块。
- 强调默认进入“问数据”；模型、角色、审计等属于二级设置。
- 展示会话搜索、重命名、Pin/Archive，但不深入展开。

## 1:25～2:10 功能 2：数据源与 Schema Catalog

- 打开 PostgreSQL 主数据源，展示连接、Schema、表、字段、关系与样例值。
- 切到 MySQL 兼容数据源，说明第二方言边界。
- 解释 `Frontend → Backend API → Connector → Local Database`，浏览器不直连数据库。
- 强调业务账号只读、超时、行限、并发和审计。

## 2:10～2:55 功能 3：语义模型

- 打开“新能源经营分析”已发布模型。
- 展示 Revenue/Cost/Profit/Order Count、Region/Time/Category、Entity/Relationship、Business Term/Synonym。
- 解释版本发布和 Context Budget，不把全部 Schema 无限制塞给模型。

## 2:55～4:30 功能 4：自然语言问数主链

输入：`2026年按地区按月统计已支付订单收入趋势`。

按页面阶段讲：

1. Question Router 判断 DATA_QUERY。
2. Context Builder 绑定 Workspace、数据源、语义版本和权限。
3. NL2SQL 输出结构化 SQLPlan。
4. SQLGlot Guard 只允许单条只读查询并验证 allowlist。
5. Query Executor 使用只读账号、事务超时、并发和行限。
6. Result Oracle 独立校验指标、维度、时间、过滤、Join、列与数值。
7. Chart Planner / Insight 只使用验证后的结果。

画面：Streaming → 一句话结论 → KPI → ECharts → 洞察 → 明细 → 追问。

补充：Showcase 使用 deterministic/LEVEL0，保证录屏可重复且不产生付费调用；正式 V1.3 支持 MiMo/DeepSeek/Kimi 的统一控制平面。

## 4:30～5:25 功能 5：依据与安全失败关闭

- 打开右侧查询依据。
- 指出 SQL、语义口径、数据源、版本、耗时、Oracle、Result Signature。
- 在评测中心展示一条 `DELETE`、多语句或越权 Schema 用例被拒绝。

讲解：

> HTTP 200、SQL 可执行、页面有图表都不等于正确。只有 Guard 与 Oracle 都通过，结果才进入可保存状态。失败会返回结构化错误，不用旧答案或模型话术掩盖。

## 5:25～6:25 功能 6：受控 RAG 与有限 Multi-Agent

- 提问：`说明收入与退款的业务口径，并给出可核验引用`。
- 展示文档版本、chunk 引用和 ACL 身份。
- 展示 Complex Analysis 的公开阶段：理解、查询数据、检索知识、验证、生成洞察、完成。

解释边界：

- 固定 `Planner/DataAnalyst/Knowledge/Verification/Insight` 五角色。
- 固定 `QUERY_DATA/RETRIEVE_KNOWLEDGE/VERIFY_RESULT/VERIFY_CITATION/GENERATE_CHART/GENERATE_INSIGHT` 六工具。
- 最大 8 步、12 次工具、2 次重规划、深度 2、30 秒。
- 不输出内部思维过程，不允许动态工具、任意 URL 或数据库连接。

## 6:25～7:25 功能 7：答案、看板和评测闭环

- 保存当前 VERIFIED Answer。
- 加入经营总览看板并刷新卡片。
- 进入评测中心，展示 Golden、Expected/Actual、Result Diff 和安全分布。

讲解：

> 保存的不是截图，而是问题、SQL、语义版本、结果签名、图表和叙述的绑定快照。看板刷新会生成新的 QueryRun，评测可以持续比较模型、Prompt、语义层和 SQL 引擎变更。

## 7:25～8:20 架构与工程取舍

- 展示 README 架构链或 `docs/ARCHITECTURE.md`。
- 前端 React/TypeScript/Vite/ECharts；后端 FastAPI/SQLAlchemy/Alembic/SQLGlot。
- PostgreSQL 是主元数据和主验证路径，MySQL 做兼容；Docker 不承载数据库。
- 上游能力都在 Adapter 后，许可证、版本、SHA、修改说明和 SBOM 可追溯。
- 说明为什么没有做通用 Agent 平台、长期记忆、预测、插件市场：它们不直接提升 ChatBI 主链路。

## 8:20～9:00 发布真实性与结束

- 展示 GitHub Release 页面，不播放 Phase 0～6 认证过程。
- 说明 Release 是源码发布，不是生产部署认证。
- 结束语：

> 这个项目体现的是我对企业 AI 产品工程化的理解：模型负责候选，语义层负责口径，Guard 负责安全，Executor 负责受控访问，Oracle 负责事实，答案与评测负责长期复用。欢迎从 GitHub Release、本地一键 Demo 或代码架构继续了解。
