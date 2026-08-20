# 项目状态

## V1.2.0 正式发布冻结（2026-08-20）

- `RELEASE_STATUS=FROZEN`
- `VERSION=V1.2.0`
- `TAG=chatbi-v2-v1.2.0`
- `FINAL_RELEASE_SHA=chatbi-v2-v1.2.0^{}`；annotated Tag 的 peeled SHA 是最终发布身份，推送后的 local/tracking/`ls-remote` 一致性记录在正式交付中。
- `P0_BLOCKERS=NONE`；`P1_BLOCKERS=NONE`。
- `main` 由 `094c81a` fast-forward 到正式集成 `5303bdb`；随后增加版本元数据、发布文档、SBOM 与冻结 Manifest，并只修复正式 main-SHA 门禁发现的停止生成持久化竞态。业务口径与其他已通过的 ChatBI 能力未改变。
- 最终 Backend 门禁为 225/225；停止生成采用经会话/用户授权、按 client message 精确定位的显式服务端取消，再终止 SSE，两个真实取消流程各连续 5/5 通过后才重跑完整 82 项发布门禁。
- V1.2.0 冻结后不得直接向该 Release SHA 增加功能；后续功能必须从新的开发分支开始。
- 非阻塞 P2 保留：ECharts 555.48 kB chunk warning、重新生成新增同文可审计 user turn、Docker Desktop 冷启动受本机缓存体量影响。

## 2026-08-20

- ChatGPT 风格问数据已正式合入 `codex/v2.1-final-integration`：Target pre-merge `094c81a` 与 Source `31530f3` 通过 merge commit `8676c07` 汇合；两侧互非祖先，采用 `MERGE_COMMIT`，无冲突，两个重叠文件自动合并且语义均保留。
- 正式集成发布门禁为 Backend 223/223、Frontend 13 files / 50 tests、TypeScript、Vite 741 modules、Playwright 定向 52/52 与最终串行 82/82 全部 PASS；Console/Page/Request/unexpected blocking 4xx/5xx、横向溢出和 Composer 覆盖均为 0。
- 全量首轮 81/82 发现测试把 pending Assistant 当成事务提交证据；门禁现轮询 Conversation API 的第 21 条真实 user row，隔离 1/1 与完整 82/82 复跑通过，未降低断言或增加固定 sleep。
- Docker Compose 从完全停止状态两轮启动均 PASS；第二轮复用镜像 33.794 秒，三项服务 healthy。五张正式截图、脱敏文本日志与 manifest 位于 `artifacts/chat-ui-optimization-20260819/final-integration/`；原始 HTML/trace 与临时 auth state 因可能包含 Cookie 未提交。
- 最终推送只允许创建/更新 `codex/v2.1-final-integration`；`main`、Source branch 和全部既有 Tag 保持不变，不创建 Release Tag。

## 2026-08-19

- ChatGPT 风格“问数据”一日优化已完成候选收口：保留紫色品牌与六个一级模块，新增懒创建会话、会话搜索/分组/重命名/删除、单列消息区、默认关闭的查询依据抽屉、无覆盖 Composer、真实 canonical SSE、结构化 Message Parts，以及 VALUE/ZERO/NO_ROWS/NULL_VALUE/FAILED 五态；未增加语音、麦克风、通用 Agent 或前端直连数据库。
- 本轮最终门禁为 Backend 223/223、Frontend 13 files / 50 tests、TypeScript、Vite 741 modules、Playwright 定向 50/50 与单 worker 串行 80/80 全部 PASS；三视口 console/page/request/blocking error、横向溢出和 Composer 覆盖均为 0。NL2SQL/RAG/Multi-Agent/File/Workspace 兼容回归 105 项、Chat UI 专项 11/11 与 Feedback 双 Workspace 5/5 通过。
- Docker Compose 从停止状态启动两次均通过：完整重建 98.911 秒、复用已构建镜像 26.506 秒，Backend、RAG Runtime、Frontend 均 healthy；仍只使用本机 PostgreSQL/MySQL，Compose 数据库服务与数据库卷为 0。最终截图与原始日志位于 `artifacts/chat-ui-optimization-20260819/`。
- v2.1 Day 3 Final Product 的提交前门禁已收口：18 项产品能力均为 PRODUCT_PASS；Open Question 100/100、Memory 30×5（150 turns）、Golden 50/50、Knowledge 20/20、Agent 15/15、File 10/10 均通过，硬编码/幻觉/跨会话与跨对话泄漏均为 0。
- 全量回归为 Backend 209/209、Frontend 12 files / 33 tests、TypeScript、Vite 738 modules、Playwright 69/69；Alembic 唯一 head `20260818_0010` 的 upgrade→base→upgrade 与隔离 Schema 清理通过。两次发布冷启动分别 60.8 秒、55.6 秒，连续停止后启动 2/2 通过，三项服务均 healthy。
- 最终候选前的 Open 100 冷缓存复验发现“去年每月订单量的最大值”曾错误回退为全时段净销售额并触发查询超时；语义运行时现将“去年”解析为确定自然年、在 10M 模型中将泛化订单量绑定 `valid_orders`，并把最大值下推为指标降序与 `LIMIT 1`。专项用例、Backend 209/209、Open 100/100 与 Playwright 69/69 复验通过；该修复后的提交才可作为最终候选。
- 最终 Open 100 还暴露一次外部视觉主提供商瞬时失败；视觉网关现仅对网络错误与 408/425/429/5xx 做最多三次有界重试并遵循最多 2 秒的 `Retry-After`，其余 4xx/无效响应仍立即失败或降级。MockTransport 瞬时 429 回归、真实图片 6/6、Open 100/100、Backend 209/209 与 E2E 69/69 通过。
- 最终 E2E 对资源争用场景完成确定性加固：评测总览巡检与 V2.1 评测专项均对真实聚合保持 30 秒有界等待，长会话刷新前先等待对应助手消息完成服务端提交。原两条竞态用例连续 5 轮 10/10，新增评测专项在累积数据下连续 5 轮 10/10，完整 Playwright 69/69 通过；等待仍以真实元素和消息计数为条件，不使用固定 sleep 或忽略错误。
- 20 并发 15 分钟正式负载完成 3,763 请求且错误率 0：TTFE p50/p95 171.932/676.301 ms、请求 p95 10,592.950 ms、心跳最大间隔 2,056.274 ms、取消清理 241.300 ms；数据库连接、内存、SSE、后台任务和缓存泄漏均为 0。
- 安全攻击集 110/110 通过，56/56 危险 SQL 拦截，业务库写入 0；Python 55 项与前端锁文件 255 项依赖的已知漏洞均为 0，合并 SBOM 319 components、未知许可证 0。发布候选仍须在提交并推送后的同一 SHA 完整复验；`main` 与 `chatbi-v2-v1.1.0` 标签未获授权且未触碰。
- v2.1 Day 2 已完成 B/C/D 集成候选：B 提供 IBM-compatible Evaluation、Golden 50、八维错误分析和 Feedback/Verified SQL 回放；C 提供 PostgreSQL/MySQL Data Workspace；D 提供 ACL/Scenario 隔离混合检索、固定五角色六工具，以及不执行生成代码的结构化文件分析。
- 候选门禁：Backend 185/185、Frontend 12 files / 33 tests、TypeScript、Vite 738 modules、Playwright 63/63、Golden 50/50、Knowledge 20/20、Agent 15/15、File 10/10、Phase 2 60/60、Day 1 semantic 20/20 全部 PASS；业务数据库写入 0。
- SSE 复验为 5 并发 30 秒、68 请求 0 错误，TTFE p95 824.427 ms、heartbeat 最大间隔 2506.574 ms、取消清理 42.070 ms、2 个 >10 秒请求流式率 1.0、连接/任务泄漏 0/0。两次停止态启动分别 27.840 秒和 28.362 秒，三项服务均 healthy。
- Alembic 唯一 head 为 `20260818_0010`，隔离 schema 的 upgrade→base→upgrade 与清理均 PASS。Frozen Zone 交集 22 个文件，均逐文件审查合入，Frozen blob 整体覆盖数 0。
- Day 2 没有复制 IBM、SQLBot、Chat2DB、DB-GPT 或 PandasAI 的源码/UI/品牌资产，也没有新增直接第三方依赖；PandasAI 未导入，文件问数使用项目自有固定操作解释器。
- 最终 PASS 只由文档提交后的同一 SHA 门禁、远端相等验证和 `artifacts/v2_1/day2-final/<SHA>/` 原始清单决定。`main` 未推送、Tag 未创建、后续 Day 未执行。

## 2026-08-18

- v2.1 Day 1（仅 E + A）已在 `codex/v2.1-final-integration` 完成集成候选收口：固定 Seed `20260818` 的 PostgreSQL 10M/5M 事实数据、72 个分区、345 个索引、4 个预聚合、可复现文件集与全链路 SSE 已落地；数据签名为 `34b8ec8023f410ea387003475f84bd63b05743580138ea919880979caf86af4c`。
- 默认 DATA_QUERY 运行链现为 OpenChatBI-compatible Workspace 隔离 Hybrid Schema Linking → SuperSonic-compatible SemanticQuery → Wren-compatible MDL/dry-plan/Semantic SQL → SQLGlot → 只读执行 → Result Oracle；20/20 覆盖 Case、20/20 Golden 值、三个运行时调用率与主要链接准确率均为 1.0，LocalSemanticEngine 仅作为显式回滚。
- Day 1 集成证据：Backend 174/174、Frontend 29/29、Playwright 55/55、Phase 2 运行时 60/60、迁移单 head 与 upgrade→rollback→upgrade、Docker 两次从停止状态启动、隔离冷启动 76.8 秒、一键启动、Secret/License 检查均 PASS。严格 SSE 106 请求 0 错误，TTFE p95 213.104 ms，心跳最大间隔 2508.131 ms，取消清理 250.802 ms；另有 26 个真实 >10 秒样本流式率 1.0。详见 `docs/v2_1/day1/DAY1_REPORT.md`。
- Phase 2 Frozen Zone 共有 16 个交集文件，均为基于 Phase 2 的最小差量语义合并；Frozen blob 整体覆盖数 0。B 未合并，main 未推送，Final Tag 未创建，Day 2/3 未执行。
- v2.1 工作流 C 已形成独立 Data Workspace 候选输入：PostgreSQL/MySQL 目录检索、关系/主外键、10M 表懒加载样例、SQL 格式化/Explain/只读执行、用户级历史/重放与 Verified SQL 均进入真实 UI/API。10M PostgreSQL 查询与 MySQL 查询的 Oracle 均 PASS，危险 SQL 1/1 阻断、业务库写入 0；该结论仅针对 C 功能分支，不代表 v2.1 Final PASS。
- Phase 2 真实问答、认证、会话与多模态闭环达到预提交硬门槛：开放式 60/60、Trace 60/60、连续追问 10/10，数据 SQL/结果、知识引用、文件与图片准确率均为 1.0，不支持请求幻觉为 0。
- 统一 Chat/SSE 入口覆盖九类正式路由；DATA_QUERY 继续复用 Semantic/NL2SQL/SQL Guard/只读执行/Result Oracle，GENERAL/FILE/IMAGE 使用真实配置模型且不可用时返回明确错误。
- 服务端 HttpOnly 会话、登录限流、RBAC/Workspace/用户隔离和统一前端守卫已完成；匿名 API、无效会话为 401，跨 Workspace/附件为 403，logout 只撤销当前会话。一键启动不自动登录或写 Token。
- Frontend 多轮会话、底部固定输入框、Enter/Shift+Enter/IME、停止/重试、滚动跟随、文件拖拽/粘贴/进度/删除已完成；11 类文件格式解析和真实图片问答通过。
- 预提交门禁：Backend 134/134、Frontend 29/29、TypeScript/Build、Migration 1/1、Playwright 55/55 均 PASS；一键启动从停止状态连续两轮 20.09 秒与 18.98 秒 PASS，三个服务最终 healthy；临时 PostgreSQL Schema 的独立发布冷启动 48.8 秒 PASS。最终 clean SHA 复验和提交状态以交付输出为准，未创建 Final Tag。详见 `docs/evidence/phase2/README.md`。

## 2026-08-17

- Day 5 RAG + Multi-Agent Final Closure 全部门禁 PASS：RAG Golden 120/120、Recall@10 1.0、Citation Accuracy 1.0、越权检索 0；Complex Analysis 10/10、Trace 100%；Backend 127/127、Frontend 27/27、串行 E2E 51/51、并行 E2E 5 workers 连续三轮 153/153、Golden PostgreSQL 50/50 与 MySQL 10/10。隔离冷启动 72.3 秒；完整停止后的一键启动 Run1 54.5 秒、Run2 33.2 秒；三家 Provider Live Smoke、Migration、Secret Scan、License 与安全回滚模拟均通过。最终 Git/远端/annotated tag 以 `docs/status/DAY5_STATUS.md` 和发布返回为准。

- ADR-030 已把受控 RAG 与最小 Multi-Agent 提升为 V1/P0 必选：新增独立 Live RAG Runtime、HMAC Workspace/用户/角色映射、ACL/Citation/Answer Guard、固定五角色六工具、8/12/2/2/30s 预算、SSE 阶段和运行性能字段。默认 `CHATBI_RAG_MODE=on`、`CHATBI_AGENT_MODE=on`；普通 `DATA_QUERY` 仍只走 QueryPipeline。
- 旧项目二生产源码复制数为 0；六个 Prompt 均独立编写并保存 source/version/purpose/checksum。15 张运行时表均有真实使用记录；迁移 head 为 `20260817_0008`。
- Day 4 Quality Hardening 全部 Gate PASS：Parallel E2E 5 workers 连续三轮 36/36、Golden 50 PostgreSQL 执行/结果/语义 50/50、MySQL 10/10、原 Golden 20 回归 PASS、危险 SQL 38/38、Backend 99/99、Frontend 27/27、串行 E2E 36/36、两次完整停止后的一键启动均 PASS；main 已推送并完成 live remote verify，annotated quality tag 由最终发布收口创建。
- Day 4 完成共享状态竞态加固、NL2SQL/Result Oracle 扩展、语义模型版本/发布/回滚、ADMIN/ANALYST 最小 RBAC、资源授权与真实审计；UI14 的 Loading/Empty/Error/Permission/Success 状态均由真实 API 或真实错误状态驱动。前端 route-level lazy loading 将入口 JS 从 963.34 kB 降至 273.08 kB，ECharts 独立按需 chunk 的非阻断 warning 保留为 P1。
- 新增根目录双击入口 `一键启动-ChatBI-V2.cmd`：自动检查 Docker Desktop，复用既有本机数据库启动/验证链，构建 Backend/Frontend 并打开 ChatBI 首页；失败时保留可读错误，不 reset、不提交当前 Day 4 工作树。
- Day 4 模型 Provider 子任务保持完成：Kimi `kimi-k2.6`、MiMo `mimo-v2.5`、DeepSeek `deepseek-v4-flash` 已通过项目自有 Adapter 接入；密钥只在 Git 忽略的本机 `.env`，前端通过只读 Backend API 展示真实配置状态，默认回归路由仍为 deterministic。本轮遵循负责人授权，没有重复开发 Provider 或输出密钥。
- Day 3 V1 RC 候选产品闭环已实现：真实 Query Result 生成受控 ChartSpec/ECharts、证据绑定 Narrative、3～5 个推荐追问、Verified Answer/版本、Dashboard Card 和可持久化 Golden Evaluation。
- 产品与测试 Gate：Chart Rule 19/19、Backend 85/85、Frontend Vitest 26/26、TypeScript/Build PASS、Playwright 34/34（Day 3 专用 19/19）、Golden SQL/结果/语义 20/20、MySQL 5/5、危险 SQL 38/38、真实写入成功 0、迁移单 head 与 upgrade→base→upgrade PASS、Secret Scan PASS。
- Day 3 时外部模型尚未配置；Day 5 已完成 Kimi、MiMo、DeepSeek Discovery/Auth/Chat/SQLPlan/Guard Live Smoke，发布默认 Runtime 仍为 deterministic。
- Day 3 / V1 RC 发布门禁已收口：两次从完整停止状态的一键构建与启动均 PASS；最终 Backend 85/85、Frontend 26/26、Playwright 34/34、Golden、安全、迁移与 Secret Scan 全部 PASS；main 与 origin/main 同步，annotated Tag `chatbi-v2-v1-rc1` 已推送并核验。项目进入 Day 4 Quality Hardening。详见 `docs/status/DAY3_STATUS.md` 与 `docs/evidence/day3/`。

- UI14 正式集成收口：14/14 React 页面与 14/14 Router 路由已按现有实现冻结；六个一级模块保持 ChatBI-first，系统设置仍是二级管理入口。本轮未重新设计或从 Figma 生成页面。
- UI14 Gate：`npm ci` 0 vulnerabilities，Frontend TypeScript PASS，Vitest 10 files / 26 tests PASS，Vite production build PASS（728 modules），Playwright 15/15 PASS；专用 UI14 用例完成 42/42 路由-视口检查并生成 42 张忽略的运行截图。
- 1440x900、1366x768、1920x1080 的页面级横向裁切、关键控件遮挡、Route 白屏、console error、page error、blocking request failure 均为 0；Day 1 数据源、Schema、语义模型真实浏览器链路继续 PASS。
- 清理了未被引用且已被真实页面替代的 `SecondaryPages.tsx` 占位组件，并把视觉测试产物统一输出到 Git 忽略的 Playwright 目录；详见 `docs/status/UI14_INTEGRATION_STATUS.md` 与 `docs/evidence/ui14/`。

- Day 2：Schema Linking、QueryContext、NL2SQL Router、结构化 SQLPlan、SQLGlot AST Guard、PostgreSQL/MySQL 只读执行、Result Oracle、真实结果页、反馈与答案保存已完成并通过门禁。
- Golden 20 已冻结：PostgreSQL 执行/结果/语义 20/20，MySQL 基础兼容 5/5；38/38 危险 SQL 被阻断，两个只读账号真实写入成功数 0。
- Backend 66/66、Frontend 26/26、Playwright 12/12；本机 PostgreSQL 迁移单 head 与 upgrade→base→upgrade PASS，Compose 两次冷启动 PASS。
- Docker 仍仅有 Backend/Frontend，数据库服务 0、数据库卷 0；默认查询使用本机 PostgreSQL，MySQL 仅作兼容验证。
- Day 2 详细结论与证据见 `docs/status/DAY2_STATUS.md`、`docs/evidence/day2/`。

- Phase 0：PASS，GitHub 基线已建立。
- Day 1：基础工程、数据源、Schema Metadata、Semantic Layer MVP、14 个 UI 路由和一键启动已实现并通过本地门禁。
- 数据运行基线：本机 PostgreSQL 主、MySQL 辅；Docker 数据库服务与旧模拟数据卷均为 0。
- 当前范围保持 ChatBI-first；未进入 NL2SQL、Result Oracle、复杂 Dashboard、Agent、RAG 或长期 Memory。
- 详细证据与 Day 2 输入见 `docs/status/DAY1_STATUS.md`。
- 语义模型列表与编辑器已按批准的 Figma 节点 `19:3`、`19:5` 落地：列表卡片、状态统计和最近变更读取 Backend API；编辑器支持实体、度量、维度、关系和业务术语的选择、添加、配置保存、发布与预览。
- 语义模型列表 API 返回真实资源集合以支持卡片计数；前端未写死模型业务数据，也未直连数据库。
- 本次 UI 验收：Frontend 11/11、Backend 14/14、E2E 4/4；1366×768、1440×900、1920×1080 无页面级横向裁切，两个目标页面的 console/page/blocking request error 均为 0。
- P0“问数据”空状态与分析结果页已按批准的 Figma/PNG 参考完成高保真实现：自然语言提交、推荐问题、ECharts 趋势/区域图、查询依据、推荐追问及默认折叠的 SQL/明细弹层可用。
- 本轮前端验收：Vitest 5 个测试文件、11 个测试全部通过；TypeScript/Vite 生产构建通过；生产依赖审计 0 个已知漏洞；1366×768、1440×900、1920×1080 两个问数据路由均无横向裁切，浏览器 error/warning 为 0。
- Day 1 分析结果曾明确标记为“UI 结果演示”；该临时状态已由 Day 2 真实 `/api/v1/ask`、SQL Guard、Query Executor 与 Result Oracle 结果替换。
- 登录页已按 Figma 节点 `5:73` 与 `docs/ui/01_登录页.png` 完成高保真实现；Figma 光晕与开关资源已本地化，表单具备可访问标签、键盘焦点、记住登录交互，并在演示校验通过后进入“问数据”。
- 登录页专项验收：Vitest 2/2、Playwright E2E 1/1；1440×900、1366×768、1920×1080 三个目标视口均无页面级横向裁切，浏览器 console error/warn 为 0。
- P0“答案库”和“看板列表”已按批准的 Figma 节点 `20:2`、`22:2` 与 `docs/ui/08_答案库.png`、`docs/ui/09_看板列表.png` 落地。统计、筛选、分页/视图切换、创建和 JSON 导入均通过 Backend API 使用 PostgreSQL 元数据，浏览器不直连数据库。
- 新增 Alembic 版本 `20260817_0002`，本机 PostgreSQL 已迁移并写入可复现演示元数据：128 条标准答案、18 个看板；答案与看板首屏各返回 6 条，统计值由数据库聚合生成。看板趋势图使用从 Figma 节点下载并本地化的 12 个 SVG 资源。
- 本轮综合验收：Backend 17/17、Frontend 16/16、Playwright E2E 5/5、TypeScript/Vite 生产构建通过；1366×768、1440×900、1920×1080 下无页面级横向裁切，答案库/看板列表 console error、page error、blocking request failure 均为 0。1440×900 实机截图保存于独立验收目录，未写入仓库。
- 同日答案库、看板、数据源、语义模型等 UI/API 变更已纳入 Day 2 全量回归；E2E 继续通过浏览器同源 `/api/v1` 使用 Backend。
- P0“数据源列表”和“数据源详情与 Schema 管理”已按批准的 Figma 节点 `8:2`、`1:25` 与 `docs/ui/04_数据源列表.png`、`docs/ui/05_数据源详情与Schema管理.png` 完成高保真实现。列表统计、搜索、类型/状态筛选、全量同步和新增连接均读取或写入 Backend API；详情页支持真实 Schema/表切换、字段角色展示、样例值预览、连接测试和设置更新，前端不保存或回显已有密码。
- 数据源列表与详情使用元数据聚合得到真实表/字段数量；本机 PostgreSQL 当前同步结果为 9 张表、56 个字段。未同步样例值时显示明确空状态，不用 Figma 示例行或硬编码总数伪装业务结果；Figma 中非 P0 的数据源类型也未被添加为虚假能力。
- 本轮验收：Backend 17/17、Frontend 16/16、Playwright E2E 5/5、TypeScript/Vite 生产构建通过（712 个模块）；1366×768、1440×900、1920×1080 均无页面级横向裁切，数据源列表/详情浏览器 error/warning 为 0。构建仍有既存的单个 JavaScript chunk 超过 500 kB 警告，未作为本轮 P0 UI 阻塞项。
- 按用户明确优先级完成 P1“评测用例详情”高保真 UI：依据批准的 Figma 节点 `29:12` 与 `docs/ui/12_评测用例详情.png` 落地用例概览、Golden/Generated SQL 对照、结果集对比、错误分类、业务语义与修复建议；时间线装饰资源从 Figma 下载并本地化。
- 评测详情尚未接入单用例执行/重跑/修复任务 Backend API，因此页面统一显示“UI 演示 · 未执行”，指标标注为示例，写操作只返回真实状态提示；不把设计稿中的 PASS、准确率、SQL 或结果差异伪装为当前 Golden Set 验证证据。
- 本轮最终验收：Backend 19/19、Frontend 20/20、Playwright E2E 5/5、TypeScript/Vite 生产构建通过（721 个模块）；1366×768、1440×900、1920×1080 均无页面级横向裁切或结果表内部横向溢出，评测详情浏览器 console error/warning 为 0。构建仍保留既存的单个 JavaScript chunk 超过 500 kB 警告。
- 评测详情 UI 变更与答案库、看板、数据源、语义模型回归已统一进入 Day 2 集成门禁；评测单用例执行 API 仍如实保持未接入状态。
- 按用户明确优先级完成 P1“系统设置与模型服务”“用户、角色与审计”高保真 UI：依据批准的 Figma 节点 `42:11`、`45:11` 与 `docs/ui/13_系统设置与模型服务.png`、`docs/ui/14_用户角色与审计.png`，落地模型提供商卡片、路由策略、服务健康样例、成员/角色/权限策略视图、角色摘要、审计时间线、搜索筛选和邀请表单；4 个 Figma SVG 资源已下载并本地化。
- 两个设置页面当前统一显示“UI 演示”边界。模型开关、配置保存、成员邀请、权限编辑和审计导出只更新页面状态或返回未接入提示，不伪造模型调用、用户写入、权限同步或审计成功；设计稿中的健康指标、成员与审计记录均明确标注为静态样例，后续只能通过 Backend API 替换。
- 本轮最终验收：Frontend 10 个测试文件、22/22 测试通过；Playwright E2E 5/5；TypeScript/Vite 生产构建通过（728 个模块）；1440×900、1366×768、1920×1080 两个目标页面均无横向溢出，浏览器 console error/warning 为 0。构建仍保留既存的单个 JavaScript chunk 超过 500 kB 警告。
- 模型服务、细粒度 RBAC 和审计仍只保留明确标识的 P1 前端界面壳，不被 Day 2 P0 主链路 PASS 误标为后端已完成能力。
- P0“经营看板详情”和“评测中心总览”已按批准的 Figma 节点 `4:2`、`7:2` 与 `docs/ui/10_经营看板详情.png`、`docs/ui/11_评测中心总览.png` 完成开发落地。经营看板详情通过 Backend API 使用已保存的只读 PostgreSQL 数据源连接，实时聚合最近 30 天及上一周期的收入、利润、利润率、活跃客户、日期趋势和区域表现；前端没有直连数据库或写死业务指标。
- 新增 Alembic 版本 `20260817_0003` 与评测运行元数据。评测中心总览的 Golden Set、SQL 生成率、结果集准确率、语义理解准确率、相关性、响应时间、错误分布、趋势和版本对比均由 `/api/v1/evaluation/overview` 返回数据库记录；“运行全部评测”等尚未连接评测执行器的写操作只显示真实未接入提示，不伪造运行成功。
- 本轮专项验收：经营看板/评测 Backend API 测试 5/5、目标页面 Vitest 2/2、目标流程 Playwright E2E 1/1、TypeScript 与 Vite 生产构建通过；E2E 覆盖 1366×768、1440×900、1920×1080，均无页面级横向裁切，两页各渲染 2 个 ECharts，浏览器 console error/warning 为 0。构建保留既存的单个 JavaScript chunk 超过 500 kB 警告。
- 同日集成期间发现的语义资源数量旧断言和问数据 UI 演示断言已按真实 Day 2 契约更新；最终 Backend 66/66、Frontend 26/26、Playwright 12/12 全部通过。

## 2026-08-18：V2.1 Evaluation / Golden / Feedback 并行闭环

- 独立 worktree/branch 从 `origin/main@23c6be7` 建立，没有触碰主工作树的并行未提交修改。
- EvaluationAdapter 已完成 execution-based compare、Multiple Ground Truth、八类准确率、错误分析、五维 Profile 比较、Dashboard 与 Release Gate。
- SQLBot 仅作流程参考；反馈闭环以 ChatBI 自有 QueryFeedback、VerifiedAnswer、AnswerVersion、SQL Guard、Query Executor 和 Result Oracle 实现，无第三方源码/UI/品牌复制。
- 隔离验证：Backend 130/130、Frontend 29/29、Vite build、专项 E2E 2/2、PostgreSQL Golden 50/50、MySQL 10/10、危险 SQL 38/38、Feedback replay 3/3 全部 PASS。
- 详细状态与证据：`docs/status/V2_1_EVAL_GOLDEN_FEEDBACK_STATUS.md`、`docs/evidence/v2.1/`；主控接口请求见 `docs/integration_requests/EVAL_FEEDBACK_INTEGRATION_REQUEST.md`。
