# AGENTS.md — ChatBI V2 全局强制规则

## 1. 项目身份

- 项目：ChatBI V2 / ChatBI Core
- 产品定位：以自然语言问数、语义层、可验证结果、自动图表与业务洞察为核心的独立开源企业级 ChatBI 产品。
- 第一目标：让业务用户能够连接数据库、建立语义模型、自然语言提问、获得正确结果与图表，并沉淀为答案和看板。
- 本仓库不是通用 AI 平台、知识库平台、Agent 平台、模型管理平台或预测平台。

## 2. 不可偏离的核心主链路

任何功能必须服务下列主链路：

`连接数据源 → 同步 Schema → 建立语义模型 → 自然语言提问 → 生成并校验 SQL → 执行只读查询 → 验证结果 → 生成图表与业务结论 → 保存答案或看板 → 进入评测与持续优化`

不直接提升该主链路准确率、安全性、稳定性或易用性的功能，不得进入当前版本。

## 3. 范围优先级

### P0：当前版本必须完成

1. PostgreSQL / MySQL 数据源连接与只读测试。
2. Schema、表、字段、关系和样例值同步。
3. Metric、Dimension、Entity、Relationship、Business Term、Synonym 的轻量语义层。
4. Context Builder、NL2SQL Router、SQL Guard、Query Executor。
5. Result Oracle：指标、维度、时间、过滤、Join 与结果值校验。
6. 问数据、数据源、语义模型、答案库、看板、评测中心六个一级模块。
7. Golden Set、回归测试、Docker Compose 一键启动和发布门禁。

### P1：仅在 P0 全部通过后处理

- 第二数据库方言完善、细粒度 RBAC、审计页面、模型服务页面、评测用例详情、Dashboard 编辑增强。

### P2：当前版本禁止作为阻塞项

- 复杂长期记忆、遗忘策略、通用 RAG 生命周期、通用 Agent/Skills、预测建模、复杂告警、通用报表引擎、插件市场、深度 OIDC/Vault、跨行业工作流。

## 4. 与其他项目的边界

- 项目一是电力预测、交易决策和垂直行业分析应用；不得把预测算法、RAG 平台或行业工作流迁入 ChatBI Core。
- 旧项目二作为冻结技术资产库；只能按清单选择性迁移连接器、模型网关、SQL 执行、RBAC、审计、Docker、测试和通用前端组件。
- 禁止整目录复制旧项目二，禁止把旧项目二的通用 AI 平台结构继续沿用到本仓库。

## 5. 开源复用边界

- 允许：WrenAI、OpenChatBI、IBM Text-to-SQL Evaluation Toolkit 中许可证允许且经过审计的代码或设计。
- 仅作设计参考：SQLBot、SuperSonic、Chat2DB、DataEase、Metabase、Superset、Lightdash。
- 禁止复制受附加许可证限制的品牌、Logo、UI 源码或商业衍生代码。
- 所有第三方能力必须经 Adapter 接入；业务代码不得依赖第三方内部类和目录结构。
- 每次引入第三方代码必须更新 `THIRD_PARTY_NOTICES.md`、版本、提交 SHA、许可证和修改说明。

## 6. 技术与架构约束

- 前端：React + TypeScript + Vite；图表使用 ECharts；页面必须保持 Chat-first。
- 后端：Python + FastAPI；SQLAlchemy/Alembic 管理元数据；SQLGlot 或等价解析器执行 SQL AST 校验。
- 元数据库：PostgreSQL。
- 数据源账号必须只读、最小权限；不得使用超级管理员账号。
- 生成 SQL 只允许单条 `SELECT` 或 `WITH ... SELECT`；禁止 DDL、DML、CALL、COPY、文件访问、外部程序和多语句。
- 查询必须具备超时、行数限制、并发限制、字段脱敏和审计。
- Semantic Engine、NL2SQL Engine、Model Provider、Chart Engine 必须通过明确接口可替换。

## 7. UI 强制原则

- 登录后默认进入“问数据”，不得先展示系统管理后台。
- 一级导航只保留：问数据、数据源、语义模型、答案库、看板、评测中心。
- 模型、用户、角色、审计和系统配置放在二级设置中。
- 回答区固定顺序：一句话结论 → KPI → 主图表 → 业务洞察 → 明细表 → 推荐追问。
- SQL、模型调用和技术细节默认折叠，只展示可核验的查询依据，不展示模型内部思维过程。
- 1440×900、1920×1080、1366×768 在浏览器 100% 缩放下不得出现核心内容裁切。
- UI 必须依据仓库 `docs/ui/` 中批准的高保真参考实现，不得擅自切换为大面积暗色、发光或通用后台模板。

## 8. 真实性与验收规则

- 禁止伪造 PASS、覆盖率、性能、远端推送、测试结果或企业验证。
- 演示数据必须可复现；文档中如实标注演示数据，用户业务界面保持中性表达。
- HTTP 200、SQL 可执行或页面可打开不等于正确；必须验证结果值和业务口径。
- 每项结论必须关联测试证据、日志、截图、SQL、结果签名或评测记录。

## 9. 完成定义

任务只有同时满足以下条件才允许标记完成：

1. 代码、迁移、配置、文档与测试全部提交。
2. Backend unit/integration、Frontend build/test、E2E、Golden Set 回归全部通过。
3. 工作树 clean；没有未说明的 stash、临时分支或未跟踪产物。
4. Docker Compose 连续两次从停止状态启动成功。
5. 用户可见主链路可完整演示且无控制台错误、阻断请求或写数据库行为。
6. 变更未引入 P2 功能或破坏 ChatBI-first 产品边界。

## 10. Git 与交付规则

- 保持单一主仓库、单一集成主线和短生命周期任务分支。
- 禁止创建重复 clone 和长期 worktree；任务结束立即合并或删除。
- 每日结束更新 `docs/STATUS.md`、`docs/DECISIONS.md` 和验收证据。
- 发布前生成 Final Manifest、Release Notes、Rollback 说明和第三方许可证清单。

## 11. 执行顺序

每次开始工作前：

1. 阅读本文件及 `docs/PRODUCT_CHARTER.md`、`docs/ARCHITECTURE.md`、`docs/EXECUTION_PLAN_3_TO_5_DAYS.md`、`docs/ACCEPTANCE.md`。
2. 核对当前分支、HEAD、工作树、远端和现有测试。
3. 说明本任务属于 P0/P1/P2；若为 P2，停止实现并记录延期理由。
4. 先完成最小闭环，再做样式和增强。
5. 结束时给出实际测试数字、未完成项、风险和下一步，禁止使用模糊表述。
