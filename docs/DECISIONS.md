# Architecture Decisions

## ADR-001：Day 1 使用模块化单体

前后端分别保持单体部署，后端按 API、Connector、Metadata、Semantic、DB 分层。当前主链路不引入分布式微服务。

## ADR-002：第三方语义引擎必须经过 Adapter

业务模型、ORM 和 API DTO 保持 ChatBI 自有定义。`LocalSemanticEngine` 承担 Day 1 真实校验；`WrenSemanticAdapter` 只转换快照并明确暴露 runtime 可用性，不让业务代码依赖 Wren 内部类。

## ADR-003：元数据使用完整限定名

Schema、Table、Column 使用 datasource、schema、table、column 组合或稳定 ID，避免跨数据源和跨表同名字段碰撞，为后续 Schema Linking 提供可检索目录。

## ADR-004：模拟业务数据写入本机数据库且应用连接只读

本机 PostgreSQL/MySQL 保存两套同构经营数据，覆盖超过 12 个月。PostgreSQL 是主开发/主测试数据库，MySQL 是辅助兼容数据库。初始化管理员仅在交互式引导进程中用于建库授权；ChatBI 保存和使用 `chatbi_reader` 只读账号。Docker Compose 不创建数据库容器或数据卷。

## ADR-005：Day 1 不伪装 Wren runtime 集成

Wren runtime 未进入 Day 1 运行镜像。Adapter 的 capabilities 明确报告不可用，深度集成、MDL Schema 校验与 Semantic SQL 转换列为 Day 2 输入。

## ADR-006：前端不直接连接数据库

真实模拟数据必须通过 `Frontend → Backend API → Connector → Local Database` 使用。浏览器直连数据库会暴露凭据并绕过只读、审计和后续 SQL Guard，因此明确禁止。

## ADR-007：语义模型高保真界面继续由真实 API 数据驱动

Figma 只作为布局、视觉层级和交互意图的批准参考，不作为业务数据来源。语义模型列表接口返回模型及其真实语义资源集合，前端据此计算实体、度量、关系和状态统计；编辑器通过现有语义资源 API 读取与保存配置。缓存策略尚无持久化 DTO 时仅保留为明确提示的界面草稿，不伪装为已写入数据库。

## ADR-007：登录页不伪装生产认证

Day 1 登录页只承担进入 ChatBI 工作空间的高保真界面与前端演示路由。表单通过原生必填校验后进入默认“问数据”页，但不在前端伪造令牌、用户会话或 SSO/OIDC 成功状态；页面中的 SSO/OIDC 文案属于批准设计内容，不作为认证能力已完成的验收证据。真实认证接入必须由后端身份能力、会话安全与审计共同实现。

## ADR-008：问数据结果页在后端执行链完成前采用显式 UI 演示态

问数据空状态可完成问题录入与路由流转；分析结果页先承载批准的布局、ECharts 图表和折叠查询依据交互。由于 NL2SQL、SQL Guard、Query Executor 与 Result Oracle 尚未完成，页面必须显示“UI 结果演示”“未执行查询”等中性标识，不得把设计参考中的数值、可信度或 SQL 状态表述为真实验证结果。Day 2 接入时只允许通过 Backend API 替换展示模型，前端不得直连本机数据库。

## ADR-009：答案库与看板列表使用独立元数据模型和聚合 API

Figma 仅定义答案库与看板列表的布局、视觉和交互，不作为业务数据源。标准答案与看板使用 SQLAlchemy/Alembic 管理的 PostgreSQL 元数据表，摘要指标由 Backend 查询实时聚合，筛选、分页、创建和 JSON 导入统一走 `/api/v1/answers` 与 `/api/v1/dashboards`。演示记录由幂等种子生成，前端只保存展示状态；看板趋势 SVG 属于视觉资源，不承载或伪装业务指标值。

## ADR-010：数据源高保真页面只展示 Backend 可核验元数据

Figma 定义数据源列表、Schema 浏览器和字段管理的布局与交互，但示例数据源数量、类型、表数、字段数、样例值和业务标签不作为运行数据。Backend 在数据源、Schema 和表 DTO 中聚合返回真实计数，前端只经 API 渲染 PostgreSQL/MySQL P0 能力；元数据未提供样例值、主业务或表所有者时显示“未同步”或“尚未配置”，不得填入设计稿示例值。连接密码只允许在创建或显式更新时向 Backend 发送，已有密钥不回显到浏览器。

## ADR-011：Day 2 生成逻辑只消费语义对象，不消费 Golden SQL

本地确定性 Provider 通过指标、维度、术语、时间、过滤和分组意图组合 SQLPlan，不维护“完整问题 → 固定 SQL”映射。Golden SQL 仅存在于 `evaluation/golden/` 的冻结评测清单，用于独立执行值与签名对照，运行时代码不得读取该目录。

## ADR-012：SQL 安全采用 AST 授权与数据库最小权限双层防线

SQLGlot Guard 拒绝非 SELECT、多个语句、系统 Schema、越权表/列、通配符和危险函数，并强制行数上限。即使 Guard 出现缺陷，Query Executor 使用的本机 PostgreSQL/MySQL `chatbi_reader` 仍无写权限；Day 2 真实 UPDATE 尝试两种方言均失败且行数不变。

## ADR-013：Result Oracle 不以模型自评或 SQL 文本相等代替正确性

Oracle 从 SQLPlan、授权结果、执行结构与冻结期望契约独立验证指标、维度、时间、过滤、Join、列集合、值容差和顺序无关结果签名。没有冻结业务答案的任意查询只声明结构与语义一致性；Golden/Verified Answer 才进行精确结果值核验。

## ADR-014：PostgreSQL 是默认问数运行时，MySQL 作为同构兼容路径

未显式选择数据源时，Backend 优先选择 PostgreSQL 语义模型。MySQL 使用独立但同构的兼容语义模型完成至少 5 条基础 Golden 查询；前端不直接选择或连接数据库。

## ADR-015：Day 2 真实结果页取代 Day 1 临时演示态

ADR-008 的固定 UI 演示态只适用于 Day 1。Day 2 起，问数据结果页必须由 `/api/v1/ask` 返回的 QueryRun、SQLPlan、Guard、Execution 与 Oracle 数据驱动；Loading、Empty、Error、SecurityRejected、OracleMismatch 分别展示，SQL 默认折叠，反馈与答案保存写入 Backend API。前端不得保留固定业务数值作为查询结果。

## ADR-011：评测用例详情在证据 API 完成前只作为显式 UI 演示

评测用例详情属于 P1 范围，本轮仅按用户明确优先级落地批准的界面结构。设计稿中的问题、SQL、准确率、响应时间、结果差异、错误分类和修复建议均只用于视觉与交互参考；在单用例详情、执行记录、Result Oracle 对比、重跑和修复任务 API 完成前，页面必须标明“UI 演示 · 未执行”，并阻止未接入写操作产生虚假成功状态。后续真实数据只能经 Backend API 绑定查询运行、语义模型版本、结果签名和审计证据，前端不得直连数据库或自行推导 PASS。

## ADR-012：P1 系统设置与安全审计页面先落地显式演示壳

模型服务、细粒度 RBAC 和审计页面属于 P1，当前 P0 主链路尚未全部通过。本轮因用户明确要求，只实现批准 Figma 的前端信息架构、响应式布局和本地交互，不新增或伪装后端能力。模型健康指标、成员、角色、权限和审计事件仅为标明“UI 演示/静态样例”的视觉数据；所有保存、启停、邀请、编辑和导出入口必须提示尚未接入，不能产生虚假成功。后续接入时统一使用 `Frontend → Backend API → PostgreSQL/Provider Adapter`，不得在浏览器保存模型密钥、数据库凭据或管理员凭据。

## ADR-013：经营看板查询复用只读数据源连接，评测总览只展示持久化运行证据

经营看板详情的业务指标必须通过 `Frontend → Backend API → DataSource Connector → Read-only PostgreSQL` 查询真实业务数据，不能使用权限仅覆盖元数据表的应用会话跨权读取业务 Schema，也不能让浏览器持有数据源凭据。Backend 只执行服务端定义的单条 `SELECT`/`WITH ... SELECT` 聚合语句，并在 DTO 中返回计算口径、数据日期与查询范围。评测中心总览只展示已持久化的评测运行、Golden Set 数量和指标快照；在评测执行器与 Result Oracle 证据链未接入前，运行、导入和新建入口不得生成虚假评测记录或 PASS 状态。

## ADR-016：UI14 基线以精确路由契约和可重复三视口 Gate 收口

14 页高保真实现不再通过零散页面专项结论认定完成，而由精确的 14 项 Route Manifest、六项一级导航断言和 14 页 x 3 视口 Playwright Gate 共同冻结。每个直接 URL 必须返回页面并出现专属 React 标记；浏览器运行时错误、请求失败、页面级横向裁切和关键控件遮挡均为硬失败。截图与 trace 属于可再生测试产物，统一保存在 Git 忽略的 Playwright 输出目录，避免回归运行修改已提交证据文件。系统设置与安全审计继续作为二级 P1 界面壳，不能进入六个 ChatBI-first 一级模块，也不能把静态 UI 示例升级为后端能力已完成的证据。

## ADR-017：ChartSpec 是后端生成的受控展示契约

Chart Engine 只根据已执行 QueryRun 的字段、行形状、指标、维度和结果签名生成 `KPI/LINE/BAR/GROUPED_BAR/STACKED_BAR/DONUT/TABLE` 之一。前端 EChartsRenderer 只翻译该白名单契约，不执行模型生成的 JavaScript。ChartSpec 必须绑定 `data_source_query_id`、列、行数和 `result_signature`，从而阻止静态图、随机数据或与查询结果脱离的图表进入答案和看板。

## ADR-018：Narrative 只能从 Oracle 通过的结果抽取可证明陈述

NarrativeEngine 在 Result Oracle 未通过时不生成业务洞察；通过时只描述可由行值证明的指标、趋势、贡献、差异、集中或异常，并为陈述保存字段和行索引证据。它不得声称未经数据证明的因果关系。推荐追问由当前 Metric、Dimension、Filter 与结果形状确定性生成，保持 3～5 条并重新进入 Ask Pipeline。

## ADR-019：答案与看板卡片保存完整证据快照而非仅保存 SQL

只有 Oracle 通过且用户给出 `HELPFUL` 反馈的 QueryRun 才能保存为 VERIFIED Answer。AnswerVersion 保存语义意图、SQLPlan、SQL、结果签名/快照、ChartSpec、Narrative、数据源和语义模型版本；Dashboard Card 继续绑定 Answer、QueryRun 和结果签名，刷新时重新执行来源问题并生成新 QueryRun。

## ADR-020：Evaluation Run 必须真正执行冻结 Golden Set

评测 API 在运行前验证冻结清单数量和 SHA-256，在运行中逐条经过 Ask Pipeline 与 Result Oracle，并把 Expected、Actual、Generated SQL、ResultDiff 和错误分类持久化为 Case Result。Docker 镜像从仓库唯一冻结清单复制运行资产，不维护第二份 Golden 内容。前端只展示持久化记录，禁止写死 100% 或 20/20。

## ADR-021：发布状态由全部 Gate 决定

产品测试通过不等于 RC 已发布。两次从停止状态启动、Clean Worktree、远端同步和 annotated Tag 都是发布 Gate；若执行环境不允许访问 Docker 或 `.git`，必须保持 `PARTIAL` 并禁止创建 PASS/RC Tag。

## ADR-022：共享状态 E2E 发布门禁串行执行

Day 3 E2E 会同步 Schema、发布语义模型、保存 Answer/Dashboard Card 并运行 Golden Set，多个文件共享同一本机 PostgreSQL 元数据库。发布门禁因此使用 Playwright 单 worker 串行执行，避免 Schema Catalog 重建与查询 allowlist 构建发生测试级竞态。并行模式仍可作为压力探测，但其结果不得替代 34 项确定性发布 Gate；Schema Sync 与在线查询的并发隔离列入 Day 4 加固。

## ADR-023：命名模型供应商共享 Adapter 契约但保留请求差异

Kimi、MiMo 与 DeepSeek 都提供 OpenAI Chat Completions 兼容接口，但兼容不等于请求参数完全相同：Kimi K2.6 不接受任意 `temperature`，MiMo 官方 HTTP 示例使用 `api-key`，三家对最大输出字段也不完全一致。ChatBI 因此用命名 `ProviderDefinition` 保存 Base URL、Model ID、认证头和安全请求参数，再统一进入 `OpenAICompatibleProvider`、`SQLPlan` 强校验和 SQL Guard；业务代码不直接依赖供应商 SDK。API Key 只来自 Backend 环境变量，前端状态 API 永不返回密钥。默认发布与 Golden 回归继续使用 deterministic，外部模型只能显式选择，避免非确定性与费用进入基础 Gate。

## ADR-024：并行 E2E 先建立稳定运行时，再并发只读与隔离写入

Playwright `globalSetup` 在 worker 启动前只同步一次 PostgreSQL/MySQL Catalog；Schema Sync 通过数据源行锁与单事务替换元数据，查询在提交前继续看到旧目录。会发布和回滚的测试使用独立语义模型并负责清理，跨 worker 的 UI/查询/Golden 场景按正式主模型稳定标识取运行时，不再使用“最新更新时间”或列表首项。这样既避免测试竞态，也修复了临时已发布模型劫持产品默认运行时的真实风险。

## ADR-025：Golden 50 是可追溯冻结清单，不是问题到 SQL 的运行时映射

`day4-golden-50.json` 保留原 Golden 20 的 SHA-256 来源并新增 30 条多指标、贡献率、NULL、环比/同比、自然月/季度、去重粒度和空结果用例。冻结 Expected SQL/Result/Signature 仅由独立评测脚本读取；NL2SQL 运行时仍只消费语义对象。正式 Gate 要求 PostgreSQL 50/50、MySQL 至少 10/10，并由 Result Oracle 同时验证结果值和语义契约。

## ADR-026：语义回滚生成新发布版本，历史版本保持不可变

Publish 在完整校验实体、指标依赖、维度、关系键和业务术语引用后写入快照。Rollback 读取目标快照、重新校验并生成递增的新版本，例如 V1→V2 后回滚 V1 会发布 V3，并在快照记录 `rollback_source_version=1`；历史 V1/V2 不被覆盖。

## ADR-027：Day 4 最小 RBAC 信任上游身份头并记录真实审计

Backend 以受信反向代理提供的 `X-ChatBI-Actor` 解析已持久化用户；缺省本地模式映射为 ADMIN，显式未知或停用用户被拒绝。ADMIN 拥有系统设置和审计权限，ANALYST 只能访问授予的 DataSource/SemanticModel，并可使用问数、答案、看板和评测权限。拒绝访问、查询、Schema Sync、语义发布/回滚、评测、答案和看板写操作均写入 PostgreSQL 审计表。完整 SSO/OIDC 认证仍不在本轮伪装实现。

## ADR-028：前端页面按路由加载，图表库保持独立非阻断 chunk

14 个页面改为 React Router lazy route，入口 JS 从 963.34 kB 降到 273.08 kB。ECharts 被隔离到只有图表页面才加载的 555.48 kB chunk；该独立 chunk 仍触发 Vite 500 kB warning，但规范明确其为非阻断 P1，不为消除 warning 引入大规模图表重构。

## ADR-029：旧项目二 RAG 与有限编排只能受控复用

P0 全部通过后，允许把专业知识 RAG 与复杂 ChatBI 分析的有限编排作为非阻断 P1，通过自有契约、Adapter、Feature Flag、Shadow/Canary、RBAC/ACL 与审计接入。普通 `DATA_QUERY` 永远优先走现有 NL2SQL、SQL Guard、只读执行与 Result Oracle；Agent 不持有数据源连接。旧项目二没有完整多 Agent Runtime，当前只复用其 RAG 运行时 HTTP 契约和已验证的 Tool/Skill/Model Gateway/RBAC/Audit 设计，补充最薄有界状态机，不宣称完整 Multi-Agent 复用通过。旧仓库缺少根许可证，生产源代码抽取在归属与许可证补齐前保持阻塞。完整决策见 `docs/decisions/ADR_LEGACY_RAG_AGENT_REUSE.md`。

该早期结论已由 ADR-030 覆盖，仅保留为决策历史。

## ADR-030：受控 RAG 与最小 Multi-Agent 是 V1/P0 必选能力

最终产品决策冻结四类路由、真实 HMAC RAG Bridge、Workspace/用户/角色映射、ACL/Citation/Answer Guard，以及固定五角色、六工具、8/12/2/2/30s 硬预算的复杂分析编排。默认模式均为 `on`；通用 RAG/Agent 平台仍禁止。旧项目二生产源码复制数保持 0，六个 Prompt 独立改写并记录来源、用途和 checksum。完整决策见 `docs/decisions/ADR_030_RAG_MULTIAGENT_V1_REQUIRED.md`。

## ADR-031：所有用户输入统一进入持久化 Chat Runtime

Phase 2 起，普通输入、示例问题、推荐追问、文件和图片都通过 Conversation/Message 主资源进入同一 Chat/SSE 入口。路由覆盖 DATA、KNOWLEDGE、HYBRID、COMPLEX、GENERAL、FILE、MULTIMODAL、CLARIFICATION、UNSUPPORTED；DATA_QUERY 保持确定性可验证管线，其余路由按受控 RAG/Agent 或真实模型执行。完整问题到固定答案/SQL 的映射、模型不可用时的伪答案和附件宿主机路径回传均禁止。Trace 只保存公开执行证据，不保存模型隐私推理。

## ADR-032：服务端会话是唯一身份边界，一键启动保持匿名安全

前端路由守卫只负责体验，所有受保护 API 必须从 HttpOnly Cookie 或显式 Bearer 会话解析已持久化用户与 Workspace；数据库只保存会话 Token 哈希。缺失、过期、撤销会话返回 401，已认证但越权返回 403，客户端身份头不能替代认证。一键启动只启动服务、检查公开健康端点并确认受保护端点匿名返回 401，不创建匿名用户、不登录、不生成浏览器 Token，也不写 localStorage 或 Token URL。

## ADR-033：v2.1 默认语义运行链使用三个 clean-room 兼容 Adapter

ADR-005 关于“Wren runtime 尚不可用”的历史结论被本 ADR 覆盖，但不删除。Day 1 默认 `DATA_QUERY` 依次调用 OpenChatBI-compatible Hybrid Catalog/Schema Linking、SuperSonic-compatible SemanticQuery 和 Wren-compatible MDL/dry-plan/Semantic SQL，再进入既有 SQLGlot、只读 QueryExecutor 与 ResultOracle。三项 Adapter 都由 ChatBI 自行实现，只依据已审计的公开概念和契约，不复制第三方内部类、目录、UI、品牌或受限代码。Trace 保存候选对象、置信度、Evidence、SemanticQuery、MDL 映射覆盖率和 dry-plan，不保存模型私有推理。Workspace 是检索缓存键的第一维。`CHATBI_SEMANTIC_RUNTIME_MODE=local` 是显式回滚，不是默认或 Shadow 模式。
