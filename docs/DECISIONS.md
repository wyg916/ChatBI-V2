# Architecture Decisions

## ADR-071：V1.3.0 发布后只保留本机求职 Showcase 维护面

V1.3.0 的 annotated tag、peeled commit 与 GitHub Release 保持不可变；后续求职材料、启动脚本和本机演示稳定性修复只能作为 main 的 POST_RELEASE 提交，不回写 Release，不启动 V1.4、V2.0 或 Production Deployment。唯一本地可运行目录固定为 `E:\ChatBI V2 项目`，历史 worktree/clone/venv/node_modules/cache 只有在 dirty、untracked、unique commit 完成外部备份与恢复校验后才可删除。

本机 Demo 继续使用 Windows PostgreSQL/MySQL 服务，不新增 Docker 数据库容器或数据库 volume。Frontend 只能通过 Backend API 读取数据；canonical Compose 只运行 Backend、RAG Runtime、Sandbox Controller/Proxy 和 Frontend，固定映射 `18080/18081/15173`。Nginx 通过 Docker DNS 动态解析 Backend，避免容器重建后缓存旧 IP；一键启动始终先验证前端代理版本接口、RAG 认证门禁和五组受保护 API 的匿名 401。

Reset 是仅供本机脚本调用的显式破坏性命令，不暴露 HTTP 入口。它只接受 development、本机 Host、PostgreSQL、数据库 `chatbi_v2` 四重目标约束，重建 `public` 元数据 Schema 并保留只读 `demo_business`；演示业务日期固定为 `2026-08-17`，同时同步 PostgreSQL/MySQL Catalog，使 SQL Guard 在重置后立即拥有 2 Schema、18 表、112 字段和 24 关系的 allowlist。评测种子使用冻结 Golden 50 Evidence 的可下钻 Showcase Snapshot，八类准确率、Release Gate 与 Case Detail 必须表达同一组证据，不能用空 Case 伪造 UI PASS。

## ADR-070：复杂 Provider token 上限绑定请求 Route，失败回退复用已验证工具结果

最终认证使用统一 `FINAL_REAL_PROVIDER_RECERTIFICATION` Gate 名称，因此不能再从全局 Gate 字符串推断当前模型调用是否属于 Complex/Agent。Model Gateway 在唯一网络边界把受信 `RequestContext.route` 传给测试成本控制器：`COMPLEX_ANALYSIS` 使用既有 1024-token 上限，其他路由保持 512；Provider 自报 Route 或正文不能改变该上限。这样避免合法复杂 SQLPlan 在 512 tokens 处截断并产生不必要修复调用，同时不放宽总调用、Provider、重试或预算上限。

若 Agent 在 `QUERY_DATA` 已完成 SQL Guard、只读执行、Result Oracle 和结果签名后才超时，Fallback 必须直接复用该已验证 `data_evidence`，不得再次执行相同 QueryPipeline 或重复付费请求；工具结果不完整或未验证时仍走原有 fail-closed fallback。真实失败响应、Trace、账本与清理证据继续保留在失败 SHA 的外部 Evidence 中。

## ADR-069：Provider ON Join 只按端点列等值 AST 证明

当结构化 Join 使用 `left_table/right_table + on` 而不是列字段或 `join_keys` 时，Result Oracle 使用 SQLGlot 解析 ON 表达式，并且只接受一个或由 AND 连接的多个 EQ 叶子；每个 EQ 两侧都必须是非空 Column、分别由左右已选端点表限定，且不能携带 Schema/Catalog。OR、常量比较、函数、算术、无表限定、同端点自比较、未知表和解析失败都 fail closed。不得用正则、字符串包含或 SQL 执行成功替代这项结构证明。

该决定只覆盖真实 Provider 已产生且 SQL Guard/EXPLAIN/执行/复核值均通过的第三种 Join 元数据表示，不改变 Result Oracle 的结果、指标、维度、时间、过滤或冻结值规则，也不让 Plan 元数据绕过 SQL Guard。旧 SHA 的失败响应与账本保留，新规则必须在 forward successor 上重新通过 exact-SHA 免费与付费 Gate。

## ADR-068：Result Oracle 接受两种严格等价的 Provider Join Key 结构

Provider 的结构化 Join 可以把键表示为 `left_column/right_column`，也可以在同一 `left_table/right_table` 端点下表示为非空 `join_keys[{left,right}]`。Result Oracle 只在左右端点都精确属于 SQLPlan 已选表，并且选择的键形态完整时接受：列形态要求两列同时非空；列表形态要求列表非空、每项是对象且左右键同时非空。两种形态不得通过半列、空列表、空键、未选表或混合不完整字段降级通过。

该兼容只修复 Oracle 对已经结构化并通过 SQL Guard/执行链的 Join 元数据验证，不从 SQL 文本猜测实体、不增加表或列、不放宽 Workspace、Schema、SQL AST、只读执行、复核查询或冻结结果验证。真实 Provider 在该边界失败的 Evidence 保留于原 SHA；修复必须进入新 forward successor 并从空账本重新认证。

## ADR-067：Canonical Projection 只沿唯一 CTE 输出做 AST Lineage 证明

外部 Provider 可以把聚合放入 CTE，再由根 SELECT 投影 CTE 输出列。Projection Contract 只在根 SELECT 的 FROM 恰为一个 CTE、没有 Join、根投影是该 CTE 的直接列引用、CTE 名与输出名都唯一且 CTE 本体是 SELECT 时，沿该列回溯一次到内层投影表达式；任何多来源、重复输出、嵌套歧义、未知 Relation 或非直接引用都保持原表达式并最终 fail closed。回溯只用于 SQL AST、SQLPlan 和 Semantic Contract 的结构指纹比较，规范化仍只修改根 SELECT 的输出 alias 及同层安全依赖，不修改 CTE、底层列、Filter、Join 或 Result Oracle。

年度日期维度的 CTE 证明还要求内层表达式严格为 `YEAR(date_column)` 或 PostgreSQL 等价 `EXTRACT(YEAR FROM date_column)`，函数中只有一个与语义日期维度相同的源列，并且同一 AST 指纹存在于该 CTE 的 GROUP BY。该约束不能扩展为任意日期函数或按 `yr/year` 字符串猜测。证明成立后的 Canonical 列仍是 SQLPlan 声明的 `order_date`；下游相关性工具必须消费该 Canonical 列来构造年度 scope，不得要求 Provider 私有 alias `year/yr`。

## ADR-066：固定 Agent Tool 继承外层控制身份，取消在首事件后抢占工作提交

Complex Analysis 的固定 `QUERY_DATA` 工具必须继承 Chat 创建的服务端 `RequestContext`，包括 `request_id`、`trace_id`、Workspace、User、Route、DataSource、权限签名和成本模式；工具只可把 `question` 更新为受控 ToolCall 的问题，不得自建新的 Case/Trace 身份。这样 Model Gateway、FINAL Case 计划、运营 Ledger、QueryRun 与 OrchestrationRun 对同一请求保持可追溯的一致身份。缺少外层上下文的非 Chat 独立工具测试仍可使用既有系统默认值，但不能冒充最终 Provider 认证。

SSE `run.started` 保持第一事件。服务端在该事件之后、向有界线程池提交实际工作之前等待最多 100ms 的共享取消事件；立即取消会提前结束等待并让工作线程在首个业务 checkpoint 以零模型调用收敛为唯一 `run.cancelled`。窗口不增加首事件 TTFE、不延长取消确认上限，也不改 Provider 超时或重试。若取消发生在真实调用完成之后，已产生的 Token/成本仍必须如实保留，不能改写成零费用。

冻结 Complex 结果的行值验证遵守关系语义：问题明确要求升序、降序或排序时，完整列表顺序和每个单元格都必须一致；未声明排序且存在冻结维度时，以全部维度组成的唯一键进行一对一完整行比较。重复维度键、缺失键、行数不同、缺列或任意值差异均失败。该规则不修改冻结数据、SQL、Result Oracle 或业务指标，只消除把未声明列表顺序误当业务正确性的认证器缺陷。

## ADR-065：Provider Join 契约与取消请求共享同一受控 Case 边界

Result Oracle 继续只接受已选语义实体间的 Join。除既有 `left/right` 与 `left_entity/right_entity/join_keys` 形态外，NL2SQL 校验后产生的 `left_table/right_table/left_column/right_column` 形态仅在两端表都精确属于 SQLPlan `selected_tables` 且两端列均非空时通过；部分字段、未知表或越界端点均 fail closed。该兼容不推断 Join、不放宽 SQL Guard，也不以结果值正确替代语义验证。

FINAL 取消探针与其主 Complex Case 共享 Case 预算和 Provider allowlist。P5C03/P5C04 的唯一计划模式显式同时匹配 `P5-P5Cxx-*` 与 `P5-CANCEL-P5Cxx-*`，不增加总调用上限、Provider 上限、重试或成本预算；网络前仍要求唯一模式、精确 Route 和允许 Provider，取消后仍必须证明唯一 CANCELLED 终态、账本状态、消息清理及 Agent/Sandbox 资源释放。

最终 NL2SQL 认证的绑定输入必须是已发布语义模型及其同一 `datasource_id` 下已同步、`table_count > 0` 的数据源；若目录为空，辅助程序必须先执行真实 Schema Sync 并重新读取目录，仍为空则在 Provider 网络前 fail closed。仅按 API 返回顺序选择第一个已发布模型是无效认证输入。由空目录触发的 `TABLE_NOT_AUTHORIZED` 继续视为 SQL Guard 正确拒绝，真实响应和费用完整保留，不能删除账本或以重试绕过 Case 上限；只能在记录该独立输入缺陷的新 forward successor 上重新认证。

真实 DeepSeek 又证明限定符解析不能只看全数据源列名：`revenue` 同时存在于 `orders` 与 `daily_kpi`，但 SQL AST 的唯一可见来源只有 `orders`。Projection Contract 允许把未限定列绑定到“全局授权 owner 与当前 SQL 可见表的交集恰为 1”的 owner；交集为 0 时仍只接受全局唯一 owner，交集大于 1、两张可见表同名列或语义表达式指向另一表时全部 fail closed。该证明只用于表达式结构指纹，不修改源列限定符；规范化仍仅修改输出 alias。

## ADR-064：Provider 投影必须在 SQL Guard 前收敛为 Canonical Output Contract

SQLPlan 的服务端输出契约显式包含 dimensions、metrics 和受控 auxiliary，每项绑定 `canonical_name`、`semantic_id`、`kind` 与 `expected_projection_type`。Provider 无权声明该服务端字段；任何 Provider 注入的 Canonical Output Schema 与 `model_trace` 一样先剥离，再由当前 QueryContext 的语义对象重建。正式链路固定为 Provider Response → SQLPlan Validation → Projection Contract → SQL Guard → QueryExecutor → Result Oracle，后两项既有规则不得为适配模型别名而放宽。

别名不一致只能通过 SQLGlot AST、SQLPlan 和语义表达式的一对一结构指纹唯一证明后规范化。禁止按列序、字符串相似度、子串或正则文本替换；歧义候选、重复 canonical alias、输出碰撞、缺失投影、未声明额外输出或未知语义对象全部在执行前 fail closed。规范化只改 SELECT 输出 alias，并在不与可见源字段冲突时同步改写 GROUP BY、ORDER BY、HAVING、QUALIFY 的未限定 alias 引用；WHERE、JOIN、底层列或其他不安全依赖一律拒绝。每次动作同时进入 SQLPlan `model_trace.projection_contract` 和 `PROJECTION_NORMALIZATION_ACTION` Audit，不记录提示词、响应正文或内部推理。

确定性/Wren 已有 canonical alias 的 SQL 保持原字符串，不为无动作验证重写整棵 AST；Wren 比较查询的 `previous_<metric>`、`comparison_rate` 和 `contribution_rate` 仅在受信任服务端 Runtime 中作为显式 auxiliary 声明，外部 Provider 的同名额外输出仍不获得豁免。真实 MiMo 失败响应以脱敏 Recorded Fixture 回归，最终必须证明规范输出列为 `revenue`、值为 `1725750.0` 且 Result Oracle PASS。

最终代表性 Complex 实跑又发现年度聚合投影的独立边界：SQLPlan 声明日期维度 `order_date`，SQL 投影可能是 `YEAR(order_date) AS year`。这类派生维度不允许按列包含关系或函数名猜测。当前唯一例外只接受 `YEAR` 这一冻结时间粒度，并同时要求语义对象为 DATE/DATETIME/TIMESTAMP、函数内恰有一个源列且与该语义表达式指纹相同、相同 YEAR AST 同时存在于 SQL `GROUP BY` 和 SQLPlan `group_by`；三方任一不一致仍以缺失规范输出 fail closed。证明成立后只把输出 alias 规范为 `order_date`，不会修改源列、GROUP BY 表达式、Filter、Join 或 Result Oracle。

## ADR-063：最终 Provider 响应先统一归一化，FINAL 调用由 Case 计划原子限额

真实 Provider 的 Chat Completions 响应先进入唯一的协议归一化边界，再交给 NL2SQL 领域解析：文本既可为普通字符串，也可为已知的文本 Part 或严格对象；NL2SQL 只接受完整 JSON、完整 JSON Markdown Fence、单层已知包装或单层 JSON 字符串，不从自然语言中用正则提取 SQL。未知 Content/Tool/Usage 形状、歧义包装、数组、缺失字段或非法 SQLPlan 全部 fail closed，随后仍必须通过 SQLPlan 校验与 SQL Guard。历史失败执行没有保留可安全复现的原始 Provider Body，因此永久 Fixture 明确标为负责人授权的通用变体，不能伪称为历史原文。

FINAL 成本控制不再只依赖 Run 总上限。仓库内冻结代表性 Case 执行计划，逐 Case 固定允许的 Provider、Route、请求上限、重试上限和估算成本，并为 Kimi Vision 扫描 PDF Case 保留不可被非视觉请求消费的容量；控制器在网络前以同一 SQLite 原子事务同时校验 Case、Provider 和 Run 三层额度。账本把 Token 与 Provider 报告费用的未知状态单独记录，汇总中的确认费用不再冒充外部账单全量费用。

同步 `/chat` 也纳入与流式请求相同的 Lifecycle：删除会话前先取消并等待有界终态，超时 Runner 必须取得 Backend 取消确认后才允许清理。取消检查覆盖消息写入、Flush 和 Commit 前边界；任何未确认的取消、晚到写入、外键残留或资源残留都使 Gate 失败。

## ADR-062：最终真实 Provider 认证使用独立 FINAL 等级和代表性 Case 上限

负责人批准的 Phase 5 收口不再重复执行 Level1 定向与 Level2 全量付费套件。测试成本控制器新增 `FINAL` 等级：仍要求 exact SHA Runtime Preflight、同 SHA 完整 Level0 Receipt、最终认证与 Cache Bypass 标志、Provider allowlist、必要性说明、配置/Prompt 身份和外部 SQLite 台账；每 Run 最多 12 次真实 Provider 请求，运行预算 3.00 CNY、每日总预算 5.00 CNY，既有一次有界重试和非重试型 4xx 立即失败规则不变。每条账本必须原样记录 `test_level=FINAL`，不得用 Level1 结果或文档标签冒充。

FINAL Runner 只允许显式选择 2～3 个 Complex Case，以及 1～3 个 Multimodal 代表 Case，从而覆盖 Agent/Tool/SQL 或 Python/Trace/Verification、扫描 PDF、复杂图表和 Premium Vision；完整 Complex5 与 Multimodal10 的 deterministic Level0 Evidence 通过受控 Delta Inheritance 保留。旧 Level1 仍用于受影响 Case 定向回归，旧 Level2 全量模式保持兼容；普通 Push 继续强制真实 Provider 调用为 0。

## ADR-061：查询容量以可取消 FIFO 槽位防止 EXPLAIN 在持续负载下饥饿

SQL 安全链的 EXPLAIN 与实际只读执行继续共享固定 `query_concurrency` 上限，等待时间继续受原查询超时约束，任何失败仍 fail closed。标准 `BoundedSemaphore` 不承诺等待者先到先得；EXPLAIN 与执行分别竞争槽位时，持续进入的新请求可能反复插队，使少量早到请求在数据库未被访问前以 `QUERY_CONCURRENCY_LIMIT` 超时，外层表现为 `QUERY_EXPLAIN_REQUIRED`。查询槽位因此改为进程内可取消 FIFO 队列：每个等待者持有稳定 ticket，释放只唤醒队首资格，取消或超时会原子移除自身且不泄漏容量；并发首次初始化也由锁保证只有一个共享 Gate。该修复不增加 retry、不放宽超时、不提高并发上限，也不绕过 EXPLAIN、SQL Guard 或只读事务。

## ADR-060：刷新持久化按同步精确状态与异步行身份保存分别证明

控件认证不能把刷新后“整个业务组的聚合状态必须与动作后即时状态字节级相等”作为所有操作的共同持久化定义。Ask 结果路由带查询参数时，刷新会按产品契约再次执行确定性查询并追加 Conversation、Message 与 QueryRun；Evaluation Run 也允许从 RUNNING 异步收敛为终态。这些新增或终态更新不代表原动作数据丢失。DB probe 因此为每张受控表输出基于主键的脱敏 identity digest 集合。普通同步 mutation group 继续要求动作后与刷新后精确 fingerprint 相等；仅 Chat 与 Evaluation 允许异步收敛，但必须证明动作后每一个行身份在刷新后仍存在、所有表行数不下降、变化表非空且缺失 identity digest 为 0。该例外不允许删除后重建、减少行数或只比较 HTTP 200。

浏览器 response listener 不是唯一事实源。若页面事件监听没有捕获 transport，只有同时存在 workspace-scoped DB before/after 实质变化与成功的独立 Backend API readback 时，`NETWORK_REQUEST` 才可写显式 `NOT_APPLICABLE_WITH_EXPLICIT_REASON`；否则仍为 incomplete evidence/fake success。DB 变化本身计入可观察 transition，但不能替代刷新后的身份保存证明。

## ADR-059：控件逻辑身份与展示和值分离，并绑定可复现 Control Universe

Phase 5 控件认证把 `DISPLAY_LABEL`、`LOGICAL_CONTROL_ID`、`LOCATOR_IDENTITY` 与 `MUTABLE_VALUE` 作为不同字段。输入、搜索、密码和可编辑控件的定位身份禁止引用当前 value 或当前可编辑文本；定位优先使用 route、role、tag/type、稳定属性、表单/容器作用域和同一稳定作用域内的 ordinal。展示标签可以随业务状态变化，但不得进入逻辑 Inventory Hash。回归必须覆盖空值、输入后、清空后、预填充、密码、搜索、重复空输入、同 placeholder 不同表单、动态 placeholder 与 disabled 状态，并证明每个阶段逻辑 ID 不变、精确重定位候选数为 1、`mutable_value_used=false`。

控件数量只有在同一 Control Universe 下才可比较。正式盘点因此签名 routes、roles、viewports、feature flags、workspace、test user、seed version/hash、菜单/Tab/Modal/Drawer 展开规则、动态资源准备、认证模式、动态状态重置与应用地址；每次发现同时输出 Universe Hash 和逻辑 Inventory Hash。隔离 Schema 中在各动态页面采集前后清理测试产生的会话、归档与项目状态，历史 Trace 表格行允许增加但通过稳定逻辑身份去重。两次独立发现必须具有相同 Universe Hash、Inventory Hash、可见数和可操作数，才允许冻结候选；原始 DOM 实例数不得冒充逻辑控件数。

## ADR-058：RapidOCR 发布镜像显式提供 GUI OpenCV 原生运行库

V1.3 固定的 `rapidocr==3.9.2` 声明依赖 `opencv-python`，其 Linux wheel 在导入时动态链接 GLib、XCB 与 OpenGL。`python:3.11-slim` 默认不含这些库，单元测试或 Windows 主机通过不能证明发布容器可执行扫描 PDF OCR。Backend 发布镜像因此显式安装 `libgl1`、`libglib2.0-0`、`libxcb1`，并在同一 layer 清理 apt 索引；发布 Gate 必须在实际构建镜像中导入 RapidOCR/OpenCV并执行 M10 本地扫描 PDF。不得用同时安装 `opencv-python` 与 `opencv-python-headless` 的文件覆盖方式规避依赖，因为两个 distribution 共享 `cv2` 包且会使供应链状态含混。

## ADR-057：控件认证以浏览器真实可见性为边界，负载 CPU 以进程分类和资源分区归因

可见控件 Inventory 不能只依赖 `display` / `visibility` 和几何矩形；关闭的 `details` 子树可能仍返回几何信息，但 Playwright 不允许用户交互。Inventory 因此对每个候选元素调用浏览器级真实可见性，只对当前页面状态中用户实际可见且启用的控件签发 receipt。执行时用稳定 `data-testid` / `href` 或控件身份与同名序号重新定位，不把动态时间文案或全局 nth 当作持久身份。写控件必须证明 DB 指纹变化、API 回读和刷新；纯 UI/导航/剪贴板/下载控件必须给出对应的可观察结果，不得用空泛 N/A 跳过。

Host CPU 超门槛不能直接归因为 Backend。正式 20 用户负载先采集至少 300 秒 Idle Baseline，再在不降低 90% Host CPU P99 固定门槛的前提下，对 Backend、PostgreSQL、Sandbox、Docker VM、Load Generator、Browser 和 Other 进程分类取样。单机环境中 Load Generator 固定到独立 2 核 CPU 亲和集，并在 Evidence 中保留其独立 P50/P95/P99；这是资源分区和可观测归因，不是从 Host CPU 门禁中扣除负载器成本。

## ADR-056：ONE_TRACE 最近页下推候选上限，带凭据 CORS 只接受显式来源

ONE_TRACE 无筛选概览只需要按创建时间返回最近 N 个 Trace。若一条记录不在任何持久化根源各自最新 N 条内，它不可能进入这些根源并集的最新 N 条，因此 QueryRun、Assistant Message、OrchestrationRun 与 KnowledgeRetrievalRun 可以分别在数据库层按 `created_at DESC LIMIT N` 读取，再复用既有合并、阶段和脱敏逻辑。该优化不截断带时间、用户、路由或状态筛选的查询，也不改变单 Trace 详情的全历史收集；Release Evidence 必须同时记录返回数量、coverage 和真实响应时间，不能只用 UI 加载占位掩盖慢查询。

本机并行项目可能占用默认前端端口，发布和隔离 E2E 因此允许通过 `CHATBI_CORS_ALLOW_ORIGINS` 提供逗号分隔的精确 Origin。默认仍只有 `localhost:5173` 与 `127.0.0.1:5173`；启用 Cookie 凭据时空列表和 `*` 一律拒绝。该配置只解决明确 Origin 的浏览器 API 边界，不授权任意跨域、前端直连数据库或把认证状态写入 Evidence。

## ADR-055：可见筛选必须进入数据库查询，派生计数不得由客户端声明

Phase 5 全可见控件门禁要求 Search、Filter、Sort 的用户条件进入 Backend API，并在当前 Workspace、用户和 RBAC 边界内形成真实数据库查询；浏览器对已经取回的全量产品数据做本地过滤不能作为该门禁的实现。为保持概览统计不被当前筛选污染，前端可以并行读取无条件汇总与有条件列表，但两者都只能来自 Backend API。没有本版本实现的控件必须移除或显式禁用并说明边界，不得保留可点击但无动作的外观。

`Dashboard.card_count` 和 `refresh_count_today` 是兼容存储字段，不是客户端输入。新建与 JSON 导入不得提交卡片数，Backend 对额外字段 fail closed；列表排序、汇总和详情统一按真实 `DashboardCard` 行重新派生卡片数量，并按当天成功 `REFRESH_CARD` 审计行派生刷新数量，即使兼容字段漂移也不能向用户显示伪造计数。演示 Seed 只创建空看板，卡片和刷新计数从 0 开始；后续只由受授权的真实卡片创建、删除和刷新操作产生。

## ADR-054：在冻结的 DB-GPT AWEL 边界覆盖未使用的易受攻击 aiohttp 版本

V1.3.0 Phase 5 继续冻结 DB-GPT `dbgpt-core/AWEL` 的相同 commit、archive
SHA 和三个 runtime symbols。该发行 metadata 把 `aiohttp` 精确锁在
`3.8.4`，但 ChatBI Adapter 不调用 DB-GPT HTTP client/server surface，只调用
`DAG`、`MapOperator` 和 `BaseOperator.call`。发布环境因此先安装冻结 archive，
再应用精确的 `aiohttp==3.14.3` 审计覆盖。安装步骤验证 exact direct URL、archive
SHA、subdirectory 与旧依赖声明后，只修正已安装 distribution 的 aiohttp metadata
并同步 RECORD；随后 `pip check` 必须为零冲突。真实 selected-runtime 测试必须重新
证明兼容，依赖审计必须为零未忽略漏洞；本决定不授权通用 DB-GPT 升级或新增
第三方运行面。

## ADR-053：Phase 5 将发布结论绑定到真实链路 Evidence，而不是清单或合成信封

Phase 5 的 Data100、10M、并发、Weird50、Complex5、Multimodal10、故障注入、成本、迁移、冷启动、浏览器和远端 CI 都必须记录 `tested_sha`、真实命令/工具来源、输入哈希、逐例观察、清理收据和 SHA-256。Manifest validator 只产生 `CONTRACT_PASS`；直接 SQL 只能证明数据源执行性能；由测试代码预填的 fail-closed 信封只能证明预期契约。三者均不得提升为真实 ChatBI 主链、Router、SQL Guard、Result Oracle、RAG/Agent、Provider 或发布总 Gate 的 PASS。

真实并发必须由 20 个不同认证用户持续至少 900 秒访问 Backend API/SSE，并覆盖 Data、RAG、Hybrid、Agent、File 和 Vision。报告要解析唯一终态及业务 Evidence，记录实际 elapsed、P50/P95/P99、CPU/RAM/连接池并精确清理临时主体、会话、附件和负载数据。成本只统计本次 request ID 与时间窗交集中的 append-only `ModelInvocation`，逐请求和逐路由证明台账完整后才能计算 Kimi Premium Share 与全 Premium 反事实节省率。

远端 `V1.3 Phase5 Release Hardening Gate` 负责确定性合约、迁移、安全、供应链和前后端回归；Phase 4、Phase 3 与 IBM 工作流在同一 Phase 5 分支提交上复验。需要本机数据库、真实 Provider 或浏览器拓扑的门禁保存在仓库外 Evidence 根并与最终 SHA 校验。任一必需门禁缺失、过期或无法绑定同一 SHA 时，Phase 5 必须保持 FAIL/PARTIAL，Phase 6 不允许开始。

## ADR-052：Sandbox Docker 控制面采用有状态最小权限代理

Phase 3 的独立 Controller 虽不把 Docker Socket 暴露给 Backend 或一次性 Worker，但 Controller 自身仍可通过 daemon API 管理主机容器。Phase 5 在 Controller 与 Host Socket 之间增加专用 restricted proxy：Controller 以 `65532:65532` 非 root 运行，只加入 private internal control network；proxy 是唯一 socket 持有者，不发布 Host 端口、不进入应用网络，并保持只读根文件系统、能力清空与 no-new-privileges。

代理对 create 请求执行 exact schema 和不可变 WorkerSpec 校验，仅允许固定镜像、固定命令、固定用户/工作目录/环境、`network_mode=none`、无挂载、只读根、资源上限、固定 tmpfs 与 ownership labels。代理维护 `job_id → container_id` 状态，start/wait/logs/kill/delete 只允许由同一受控 create 产生的对象；列举、镜像、卷、网络、secret、exec、build、未知参数、未知字段、Host namespace、privileged/capability/security-opt 扩张和任意对象 ID 均 fail closed。正常完成、取消、超时和异常都必须销毁对象并清除代理状态。

此方案不把 Host Docker Socket 交给 Worker，也不把通用 Docker API 交给 Controller；但“风险关闭”仍依赖真实 daemon 正向生命周期与完整负向攻击证据。proxy 不可用或策略拒绝时 Sandbox 必须失败，不得回落到直连 socket。若真实攻击 Gate 不能证明 `DOCKER_CONTROL_ESCAPE=0`，V1.3.0 正式发布继续阻断。

## ADR-051：负责人授权的 Legacy RAG 只复用三个锁定源码模块

项目负责人明确确认 `E:\新能源企业经营分析智能平台` 为其自有旧项目并授权 ChatBI 内部复用；外部作者、公司和权属证明不再是本轮 Gate。工程 Gate 仍锁定 Git commit `b2573a9dc1881a54581c5c556fb4a8c34046f9c3`、selected paths、Git blobs、SHA-256、依赖、Secret、数据隔离、接口和回滚。

旧知识 API/Retrieval Service 依赖其模块化单体的 Identity、Governance、ORM 和数据库，若按 Service 整体接入会建立第二套 Auth/Workspace/Data Model。ChatBI 因此选择最小 `SELECTED_SOURCE_INTERNAL_PACKAGE`：byte-identical `indexer.py`、`reranker.py`、`security.py` 在导入前校验锁文件，真实执行 deterministic feature-hash vector、BM25、RRF、rerank 与 prompt-injection detection；ChatBI Adapter 只把已经通过 HMAC、Workspace/用户/角色、ACL、场景和版本过滤的 Chunk 映射为无持久化结构对象。

正式路径保持 `Question → ChatBI Workspace/RBAC → LiveRagAdapter/HMAC → ChatBI ACL/scenario → selected-source BM25/vector/RRF/rerank → Citation → 唯一 ModelGateway → Answer Guard → AnswerEnvelope → ChatBI SSE`。旧项目不得获得数据库连接、Provider Key、Conversation、SQL Executor、外部 SSE 或动态工具。锁校验失败必须 fail closed；回滚只需 revert Successor commit，不含 Schema 或数据迁移。完整清单见 `docs/runtime/V1_3_PHASE3_OWNER_AUTHORIZED_LEGACY_RAG_LOCK.md`。

## ADR-050：Phase 3 仅引入窄范围上游运行时，并保持单一安全与证据控制面

DB-GPT 只允许固定提交 `db580e952e544acf9f6c6c153da29dc67e9e40d7` 的 `dbgpt-core/AWEL` 执行 `DAG`、`MapOperator` 与 `BaseOperator.call`；AWEL 输入不包含原始问题、SQL、数据源/模型标识、连接器、密钥、RAG 状态或工具结果。它只承载路由、Trace ID 和硬预算，并回调现有 ChatBI 固定五角色六工具编排。任何来源校验失败、运行时缺失或预算越界均 fail closed，不得回落后再记为真实 DB-GPT 调用。

PandasAI 只允许固定提交 `bbbb771d31062d81f6fa19bafb40620d5cbe48f4`、Git blob `6f31f9dfd3dbd023c7f82a1533bb3c577efd19fd` 的 community `pandasai/sandbox/sandbox.py`。不得导入根包或任何 `ee/**`。简单文件问题使用项目自有全文件确定性操作；只有复杂关联通过继承的 `Sandbox.execute` 进入独立一次性 Docker worker。Worker 必须 non-root、无网络、无主机挂载、无生产密钥、只读根文件系统、drop capabilities、no-new-privileges，并限制 CPU、内存、PID、时间、输入文件和输出；取消、超时与异常均同步销毁容器。Backend Compose 不直接挂载 Docker socket，只能在私有 internal control network 上向独立 Sandbox Controller 发送固定版本、固定字段的请求；Controller 独占 Docker socket，按不可变 WorkerSpec 创建容器，拒绝客户端镜像、命令、挂载、环境变量、网络及 Docker 参数，最多并发两个任务。Controller 的 Docker daemon 权限仍是部署高权限边界，生产环境应进一步采用 rootless daemon/socket proxy 并保持该控制网络不可外部访问。

Vision 先执行方向归一化、元数据清除、尺寸约束、必要分块、提示词注入识别与敏感字段脱敏，形成可签名 `VisualEvidence`。普通视觉默认 MiMo；Kimi 只由多图、低质量文档或大图分块等显式 premium trigger 选择，DeepSeek 不接收原始图片。扫描 PDF 经固定 pypdfium2 逐页渲染后复用同一 Vision 链。图片与数据库对照必须重新走 ChatBI Schema/Semantic/NL2SQL/SQL Guard/只读 Executor/Result Oracle，并保留 Query Run 与结果签名；视觉文本不得直接生成或执行数据库 SQL。

正式 Trace 只记录实际执行的 `rag.retrieve`、`agent.step`、`file.parse`、`python.execute`、`model.invoke`、`sql.execute`、`oracle.verify`、`answer.compose` 和 `sse.stream`。同步入口不得记录 `sse.stream`，失败或回滚不得冒充已完成 span。Legacy RAG 的历史 `BLOCKED` 结论已被项目负责人授权和 ADR-051 的最小 selected-source lock 覆盖；ACL、Citation、Answer Guard 与单一控制平面要求不变。

## ADR-049：V1.3.0 以自包含 IBM 远端 Gate 和受控 SQLBot 例外收口 Phase 2

V1.2.0 Runtime Architecture 的架构、能力、测试、安全、性能、许可证、Evidence 与 Git 原则继续约束 V1.3.0；旧版本号、分支、Tag 和历史基线 SHA 仅作历史字段。正式映射由 `docs/runtime/V1_3_RUNTIME_ARCHITECTURE_REQUIREMENT_DELTA.md` 控制。IBM 远端 Gate 不再依赖外部 `api_base` 或长期仓库 Secret：GitHub-hosted Runner 创建临时 PostgreSQL 和一次性主体，应用迁移与固定 seed，只启动 localhost Backend，再从固定 checkout 的隔离 Python 调用 Apache-2.0 selected source。生产数据库、生产用户、Provider Key 和数据库连接均不提供给 IBM；任何初始化、Golden 50、官方 compare、error analysis、脱敏或 artifact 步骤失败都必须非零退出。

SQLBot 固定提交的根 modified-GPLv3/附加品牌条件没有路径级宽松授权；官方启动又必经许可证/公开源码未闭合的 XPack，且没有可固定到目标提交的公开完整运行时。因此 V1.3.0 接受 `docs/opensource/V1_3_SQLBOT_LICENSE_EXCEPTION.md`：直接源码、官方服务和 XPack 运行继续阻断，真实调用与加载均为 0；项目自有 feedback/Verified SQL replay 保持 PASS，但不得改写为 SQLBot 集成或计入上游复用。Phase 2 的真实复用数固定为 3，本例外只适用于 V1.3.0，并在上游许可证、XPack 来源、不可变 artifact、分发边界或项目授权变化时强制复审。这是工程合规决策，不是法律意见。

## ADR-048：IBM 只允许固定 checkout 的 Apache-2.0 selected-source 离线评测

IBM `60dd451...` 的 package/wheel/sdist 继续因根 `LICENSE=Apache-2.0` 与发行 metadata `MIT` 冲突而阻断；这不自动扩展为所有源码路径均不可用。实际运行闭包只包含 11 个固定文件：执行文件均有 IBM Copyright 与 Apache-2.0 SPDX，唯一无 SPDX 的包初始化文件由根 Apache-2.0 许可证治理，依赖许可证也逐项闭合。ChatBI 因此只从外部精确 checkout 的隔离 Python 调用官方 `evaluate_prediction` 与 `get_failed_records`，每次执行前核对 commit 和逐文件 SHA-256，不安装/复制/分发冲突 package，也不给官方工具数据库连接或 Provider 密钥。

IBM 工具只评测 QueryPipeline 已执行并经 Oracle 校验的结果。Golden 50 的官方 execution accuracy 为 50/50；G50 双方一致空结果仍原样保留官方 `subset_non_empty_execution_accuracy=0`，仅分类为不适用诊断，不修改官方结果。现有在线 IBM-compatible adapter 保持 `chatbi-clean-room`，因此禁用离线任务即可回滚。共享 CI 已 fail-closed 接线，但在真实远端 workflow 成功前状态只能是 `WIRED_PENDING_REMOTE_RUN`。SQLBot 的强制 xpack 许可证闭包仍不成立，不能借服务边界绕过，Phase 2 因真实复用 3/目标 4 保持 PARTIAL。

## ADR-047：V1.3.0 Phase 2 只计可验真的最小上游源码复用，许可证冲突保持阻断

OpenChatBI/WrenAI 整包依赖闭包分别会引入自己的 LLM、向量/数据库运行时或重型执行依赖，破坏 ChatBI 的单一 Router、Model Gateway 和 SQL 执行入口。Phase 2 因此只 vendoring 固定 commit 下三个字节等同的最小源文件：OpenChatBI CatalogStore 的名称投影函数，以及 WrenAI 类型映射和 SQLGlot Wren dialect。每次运行在统一 Trace 中记录 adapter、commit、source SHA 与调用数；`selected_source|clean_room` 进入缓存键并可用环境变量 A/B，完整回滚仍为 `local`。

SuperSonic 继续 clean-room。IBM 同一发行物的根 LICENSE 与 package/wheel metadata 分别为 Apache-2.0/MIT，SQLBot 同时存在 modified GPL 品牌条款和无许可证元数据的 xpack 二进制；两者不形成官方运行时调用，也不得把项目自有兼容代码计为真实复用。Phase 2 总 Gate 因此保持 PARTIAL，即使合法的 OpenChatBI/Wren 路径和 ChatBI 自有质量闭环通过。

所有 SQL 继续进入 SQLGlot、Workspace/RBAC、EXPLAIN Cost Guard、只读 QueryExecutor 和 ResultOracle。关键指标及多 Join 查询额外执行第二条经同一 Guard 的只读一致性查询；它只能证明执行结果稳定，不冒充独立业务口径验证。Chart/Narrative 必须绑定 Query ID、列、行数、结果签名及证据字段。

## ADR-046：V1.3.0 采用单一三模型控制平面并把密钥轮换延期为生产发布门禁

V1.3.0 将 General、Intent、Vision 和 NL2SQL 的 Provider 网络调用收敛到 `app/model_gateway/service.py`。业务调用方只构造项目自有 `RequestContext`、`RouterDecision`、`ModelRequest` 与 `ModelResponse`；旧 `integration/model_gateway.py` 仅保留兼容导入，NL2SQL Adapter 不再直接创建 HTTP Client。MiMo 作为 Balanced 普通路由默认，DeepSeek 作为 NL2SQL/Structured 默认，Kimi 只在 Quality 预算与 Premium 资格满足时升级，或作为受控 Vision 回退。价格、能力、路由和健康策略存放于可审计配置，真实 Provider usage 才能计入成本。

当前三组开发 Key 经用户明确授权可继续用于 Phase 0.6、Phase 1～5 和开发测试；因此 `SECRET_ROTATION_CONFIRMED=YES` 不再是 Phase 0.6/Phase 1 条件。生产发布、正式部署或公开切流前仍必须重新验证 `PRODUCTION_SECRET_ROTATION_CONFIRMED=YES`，否则 `FINAL_RELEASE_ALLOWED=NO`。任何阶段都不得把 Key、Authorization Header、完整环境变量、Provider 错误正文或模型思考内容写入回复、Evidence、Git 或测试报告。

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

## ADR-034：V2.1 Evaluation 与反馈复用既有证据表，核心 QueryPipeline 保持冻结

V2.1 的 IBM-compatible EvaluationAdapter 只比较 ChatBI 正式 QueryPipeline 已执行的结果，不持有数据库连接，也不以 SQL 文本相等代替正确性。Multiple Ground Truth、八类准确率、Result Diff 与错误分析进入 `EvaluationCaseResult.actual`；评测 Profile 暂存为 `EvaluationRun.trend_points` 的类型化 metadata，并在 API 输出时过滤。SQLBot 仅作产品流程参考，错误修正通过 `VerifiedAnswer.feedback` 与 `AnswerVersion` 保存，只有人工审核且 Oracle PASS 的 SQL 才能晋升；回放时 Verified SQL 仍重新进入 Context、NL2SQL、SQL Guard、只读 Query Executor 和 Result Oracle。专用表和每运行 Provider/Prompt/Engine 注入由 `docs/integration_requests/EVAL_FEEDBACK_INTEGRATION_REQUEST.md` 交给主控 Migration/Runtime 统一处理。

## ADR-035：数据工作台复用 ChatBI 安全查询链并对 Chat2DB 采用 clean-room 参考

Chat2DB 当前主线采用带外部分发和嵌入限制的 `LicenseRef-Chat2DB`，因此本项目不复制、依赖、调用、嵌入或分发其源码、服务、容器、UI 与品牌资产，只将公开能力类别作为行为参考。Data Workspace 由项目自有 React/FastAPI 代码实现；所有 SQL 必须经过会话认证、Workspace/资源授权、SQLGlot Guard、QueryExecutor 只读事务、Result Oracle/只读结果校验和审计历史。样例值由服务端懒加载并按敏感列名脱敏，查询历史同时按 Workspace 和用户隔离；浏览器不接触数据库凭据。

## ADR-036：知识检索在 ACL 过滤后使用确定性混合排序并冻结场景身份

RAG Runtime 先验证签名 Workspace、用户和角色，再应用 KnowledgeAcl 与 `scenario_id`，随后执行项目自有 BM25-like、确定性 token vector、RRF 和覆盖率 rerank。历史 `chatbi-v1` 仅作为 `charging_ops` 的兼容别名，其他场景仍 fail closed。注入指令命中的 chunk 不进入候选；没有授权证据时 Answer Guard 拒绝，不能产生确定性伪知识答案。前端只展示文档/版本/chunk/locator、有限阶段和 Trace，不展示 Chain-of-Thought。

## ADR-037：结构化文件问数采用无代码执行面的固定操作解释器

PandasAI 不作为运行依赖，也不导入其 community 或 `ee/**` 代码。CSV/XLS/XLSX/Parquet 在类型、签名、大小、行数、Workspace 和用户校验后提取至受限预览；固定解释器只允许行数、过滤、分组、聚合、Join、客户分层、趋势和 TopN 等白名单操作，最多分析/输出 100 行，不执行模型或用户生成的 Python、Shell、网络、数据库连接、宿主机路径或密钥访问。结果带 SHA-256 签名、表格、ECharts、Trace 和鉴权 Artifact；超过预览上限时必须明确声明非全量结论。

## ADR-038：SSE 使用有界复用执行器并把认证写入移出请求热路径

20 并发长稳态负载表明，为每条 SSE 请求创建一个新的业务 OS Thread 会让 Python/系统分配器为已退出线程保留 arena，高并发处理能力虽然正常，Backend RSS 却随累计请求持续上升。正式流式入口因此使用线程安全事件队列、框架复用的同步 StreamingResponse worker，以及 6 个可复用业务 worker 的进程内有界执行器：20 个客户端仍可同时连接、立即收到 `accepted` 并在排队时每 0.5 秒获得 heartbeat，但双核发布拓扑不会让重 CPU/DB 工作阻断共享事件循环。同步 Token/Workspace/RBAC 与 Conversation 授权由 FastAPI 的有界同步工作池完成，不在 async 入口内直接执行阻塞 SQL。每条流仍有独立 Session、取消事件与 Trace，连接关闭继续传播到 SQL 执行，Agent/Sandbox 计数保持独立。该执行器不是通用任务平台，也不改变固定路由或工具边界。

认证仍对每次请求校验 Token 哈希、撤销、过期、用户状态、Workspace 和权限，但 AuthSession/AppUser 改为一次联表读取；SSE 再把 Conversation 所有权合并进同一查询，不使用可能延迟撤销生效的认证缓存。`last_seen_at` 与 `last_active_at` 只按 60 秒活动心跳写入，避免所有并发请求争用同一认证行。语义检索缓存固定上限为 256，Key 必含 Workspace、Role、Semantic/Knowledge/Data Version 与 Input Signature。正式性能门禁必须在完整路由预热后真实运行 20×15 分钟，并同时满足 TTFE、阶段时延、错误率以及 DB/SSE/后台任务/缓存隔离和内存无持续增长；短时 smoke 不可替代该门禁。

## ADR-039：依赖漏洞审计是发布阻断项并与兼容性回归绑定

首次 Day 3 `pip-audit` 对旧锁定集报告 86 个已知漏洞，候选立即保持不可发布。Backend 直接锁定已修复的 FastAPI/Starlette、cryptography、python-multipart、PyArrow、pypdf、Pillow 与 pytest 版本，并重建正式容器；版本更新只有在 `pip-audit` 为 0、SBOM 重生成、Backend/文件解析/安全攻击/E2E/冷启动全部通过后才可进入候选。审计工具退出 0 不能替代产品兼容性测试，反之测试通过也不能豁免已知漏洞。

## ADR-040：自然时间、业务指标与极值必须进入结构化语义计划

开放问题不能因路由正确或 HTTP 成功就视为正确。`去年` 等自然时间必须解析为基于运行上下文的确定起止边界；不同语义模型对泛化“订单量”的物理指标名可以不同，10M 基准模型统一绑定已发布的 `valid_orders`，不得回退为默认销售额；“最大值/最小值”必须下推为指标排序和 `LIMIT 1`。这些槽位需同时出现在 SemanticQuery、SQLPlan、生成 SQL 与 Trace 中，并以冷缓存 Open Question 回归验证，避免语义遗漏退化成不必要的跨分区全表扫描和偶发超时。

## ADR-041：视觉模型只对可恢复错误做有界重试

真实多模态回答继续依赖已配置的外部视觉模型，不用本地固定答案掩盖不可用状态。为避免单次网络抖动或服务端限流让整条图片主链路失败，视觉请求对 Transport Error、408、425、429 和 5xx 在同一提供商内最多尝试三次，并把 `Retry-After` 等待限制在 2 秒；普通文本模型的既有快速 failover 不变，权限、请求格式、模型不支持等非重试型 4xx 立即进入下一提供商或明确失败。重试次数和状态只进入安全错误摘要，不记录密钥、请求正文或图片内容。

## ADR-042：对话运行使用 canonical 九事件，答案以结构化部件持久化

“问数据”统一消费 `run.started`、成对 `phase.started/phase.completed`、`answer.delta`、`artifact.ready`、`citations.ready` 与唯一末尾 `run.completed/run.failed/run.cancelled`。每个事件必须携带单调递增 `seq` 和稳定的 Run/Conversation/Message 身份；客户端拒绝倒序、重复、终态后事件和 delta 与最终正文不一致。Provider 输出通过 Adapter 增量转发；确定性查询由 Answer Composer 从已验证结果逐部件产出，禁止定时器、`sleep` 或字符动画伪装流式。

Assistant 消息以 Text、KPI、Chart、Table、Citation、Evidence、Artifact 和 Follow-up 等 Message Parts 保存，并显式记录 `VALUE/ZERO/NO_ROWS/NULL_VALUE/FAILED`；数值 0 不得按空结果处理。SQL、数据口径、公开阶段和校验结论默认进入右侧证据抽屉，Agent 类名、工具名、Trace 与模型内部推理不得进入业务消息。新会话只在首条消息或附件上传时服务端创建，重命名/删除继续按 Workspace 和用户隔离。旧事件适配只允许留在客户端内部用于短期滚动兼容，不得作为真实流式发布证据。

为控制流式终态的宽表放大，Table Part 只携带前 20 行可视预览，`row_count` 与结果签名保留真实总量，Result Oracle 使用的原始 execution 不截断。Feedback 术语必须经 Semantic Model 所属关系显式按当前 Workspace 过滤，并以规范化 `(term, mapped_object)` 业务键稳定去重；前端展示键不得掩盖跨 Workspace 混入或重复资源问题。

## ADR-043：Chat UI 正式集成使用 merge commit 与脱敏浏览器证据

正式集成开始时远端 Target 不存在，而远端 `main` 已在 Original Base 之后包含两个合法竞态加固提交，Source 同时包含三个 Chat UI 提交，双方互非祖先。因此从远端 `main` 创建 `codex/v2.1-final-integration`，再以双父 merge commit 汇合，不 rebase、不 force push、不伪装 fast-forward。自动合并的重叠文件必须同时保留目标侧有界持久化等待和 Source 侧 Chat-first/SSE 断言。

浏览器发布证据提交 PNG、脱敏文本日志、非秘密命令元数据和 SHA-256 manifest；Playwright HTML、trace、storageState 与 auth cookie 只用于本地诊断，扫描后删除，不进入 Git。共享状态 E2E 继续遵守 ADR-022 串行门禁；pending Assistant DOM 不能作为事务提交证明，刷新持久化用例必须等待 Conversation API 的真实消息行。包含证据 manifest 的 Git commit 无法在自身内容中自引用最终 SHA，因此最终分支 SHA 以推送后 local/tracking/`ls-remote` 三方一致结果为准，并在交付输出中记录。

## ADR-044：V1.2.0 以 fast-forward main、annotated Tag 与不可变冻结清单发布

V1.2.0 只把已经通过正式集成门禁的 `codex/v2.1-final-integration` 安全 fast-forward 晋升到 `main`，随后仅允许版本元数据、Release Notes、Release/Rollback/Evidence Manifest、SBOM、冻结状态文档，或正式 main-SHA 门禁证实的 P0/P1 根因修复进入最终发布提交；任何根因修复都必须重跑完整发布门禁。Tag 必须是 `chatbi-v2-v1.2.0` annotated Tag，且 peeled SHA 与 local `main`、tracking `main` 和 `ls-remote main` 完全一致；禁止 force push、批量推送 Tag、移动旧 Tag 或把 P2 优化混入冻结提交。

包含 Release Manifest 的 Git commit 无法在自身内容中写入自身 SHA，因此仓库内以 `chatbi-v2-v1.2.0^{}` 作为可验证的发布 SHA 解析式，真实完整 SHA 由推送后 Git 三方核验与最终交付记录。V1.2.0 冻结后，任何功能开发必须从新分支开始；仅在 Source 分支全部提交已进入 `main` 和正式 Tag、且无独有提交时，才允许删除该轮 Source 任务分支。Integration 分支继续保留。

## ADR-045：停止生成必须显式取消服务端运行并按 client message 清理

仅依赖浏览器关闭 SSE 连接会存在传播窗口：短分析可能先提交成功消息，用户界面却已经显示取消。V1.2.0 的停止操作因此先调用受 `query.ask`、Conversation Workspace 与用户所有权约束的显式取消端点，以 `(conversation_id, client_message_id)` 精确设置运行取消事件，再终止浏览器 SSE reader。Backend 在运行 checkpoint 与显式取消端点两侧都只清理该 client message 的 user/assistant 消息，覆盖“尚未提交”和“已提交但终态尚未送达”两个竞态窗口；不得按会话批量删除，也不得把该能力扩展成通用任务平台。

发布门禁同时保留两条真实浏览器验证：原生停止按钮激活后不得持久化 SUCCEEDED assistant；停止后必须可继续验证拒绝与重试。取消接口只有在匹配运行结束并完成提交窗口后的二次精准清理后才返回，浏览器收到该确认后再关闭 SSE，因此“已停止”也是服务端持久化边界。由于本地确定性分析可能在 Playwright 的鼠标 actionability 等待期间完成，发布门禁在按钮出现后直接使用原生 Enter 激活，点击处理器另由组件回归覆盖；同一复杂问句带每次运行唯一标识，避免语义运行时缓存进一步缩短取消窗口，但不模拟 SSE、不强制点击、不跳过持久化断言。

## ADR-046：Phase 4 以 canonical AnswerEnvelope 和受控 Conversation 资源统一产品体验

所有正式回答入口必须在既有运行时完成后适配为同一 `AnswerEnvelope`，前端 Dynamic Renderer 不得按 DATA/RAG/Agent/File/Vision 再造平行渲染链。Envelope 只包含可公开验证的正文、结构化结果、引用、Artifact、SQL、阶段、错误、Token/成本和校验状态；Markdown 禁止 raw HTML，URL 和文件名执行 allowlist 与脱敏。旧的 `result-state-*`、`query-success/query-empty/query-mismatch/query-security` 可观测契约作为兼容标记保留，但不参与业务决策。

Conversation、Project、Share 与 Batch 均为 Backend 持久化资源并由 Workspace、用户、RBAC 和审计约束。Share Token 只保存哈希，支持过期与撤销，匿名共享始终只读并通过专用公开 DTO 过滤 SQL、Trace、私有地址和敏感内容。Archive 是服务端只读状态，恢复前禁止继续写消息；批处理在单事务内校验全部资源，任何越权项使整批 fail closed。

## ADR-047：Phase 4 治理以 append-only 调用尝试、阶段级 ONE_TRACE 和受证明 Verified SQL 为准

Model Gateway 每次 Provider 尝试都向请求事务绑定的 append-only `ModelInvocation` 台账追加 allowlist 元数据，包括成功、失败、重试和取消；不得保存提示词、回答正文、凭据或媒体。事务绑定必须位于同一业务调用栈，不能跨 FastAPI 同步 yield dependency 的 AnyIO Context 进入/退出边界。Cost Dashboard 只按当前 Workspace 汇总并支持时间、用户、会话、路由、Provider 和 Model 筛选；ONE_TRACE 使用真实阶段时间与 completion receipt，显示阶段、耗时、状态、Provider/Model、Tool、SQL、错误和 Artifact 能力，不伪造模型内部时间线。

Feedback 采用 `OPEN → IN_REVIEW → ACCEPTED/REJECTED` 有限状态机。ACCEPTED 候选必须重新进入 QueryPipeline 的 SQL Guard、只读执行和 Result Oracle，并把 Reviewer、问题模式、数据源、语义模型/version、SQL SHA-256、结果签名和 Attestation 固定为 Verified SQL 版本；Replay 仍重走同一安全链，不能把历史通过当成当前正确。PostgreSQL EXPLAIN 与执行在同一只读事务策略下设置经过引用的数据源 schema `search_path`，使允许的未限定表名与 Guard/Oracle 语义一致，而不扩大跨 schema 访问范围。

## ADR-048：Phase 5 修复采用三级测试成本控制，最终阈值保持不变

Phase 5 FAIL 后的普通修复默认只运行 Level 0：真实 Backend/API、本机 PostgreSQL/MySQL、SSE、RAG/Agent/File 编排、浏览器、Control Matrix、10M 和 20×15 分钟负载继续执行，但 Provider 使用 deterministic、recorded response 或显式 MockTransport，付费调用必须为 0。普通 push workflow 显式设置 Level 0；唯一 Model Gateway 网络边界在 HTTP 发出前阻断未授权真实 Provider，因此 CI 没有 Provider Key 也不会因错误路由产生费用。

Level 1 只用于实际修改 Model Gateway、Provider Adapter、Prompt、Routing、Vision 或 Agent 模型调用后的 1～3 个定向 Case，要求负责人授权、完整 SHA、Run/Case/Gate、Provider allowlist、外部成本台账和不超过 1.00 CNY 的默认硬预算；默认优先 MiMo，DeepSeek 只在能力或被改适配路径需要时显式选择，Kimi 只服务明确 Premium/Vision/Complex 范围。Level 2 只允许最终候选 SHA，在同 SHA Level 0 全门禁 PASS、cache bypass、明确最终认证标志和 3.00 CNY/日 5.00 CNY 硬上限下执行一次完整认证。Level 1 定向 PASS、录制缓存或确定性结果都不能冒充 Level 2。

测试 Provider 输出默认限制为 512 tokens，Complex/Agent 最多 1024；最多一次重试，402/认证错误立即失败。每次真实尝试在外部 SQLite 台账预留预算并记录 Run、SHA、Case、Gate、Provider、Model、Token、Cost、Retry、状态和安全错误码，不保存 Prompt、正文、媒体、密钥或数据库凭据。完整执行规范见 `docs/testing/V1_3_PHASE5_COST_CONTROLLED_TEST_STRATEGY.md`。

## ADR-049：Phase 5 Successor 只保留一个业务 SQL Gateway，并以外部 exact-SHA 清单执行回滚

Dashboard 的固定聚合 SQL 不再通过 Connector 的 `read_rows` 旁路执行。所有业务数据查询统一复用 Data Workspace 的 `execute_sql` 与唯一 `QueryExecutor`，继续经过 SQL AST Guard、只读事务、超时、并发、行限、结果签名、`SqlWorkspaceRun`、Audit 和 Trace。Dashboard 的服务端固定 SQL 只能使用代码内版本化的最小表/列策略；永久静态 Gate 限定该策略只有一个调用点，并对 QueryExecutor 类数、Connector 直接读取及原始连接执行入口执行明确 allowlist。元数据库 ORM 查询、连接测试和 Schema 元数据同步不被误归类为业务数据 SQL Gateway。

Phase 5 测试成本治理以 Backend 唯一 Model Gateway 为强制预留点。Level1 和 Level2 都必须先读取同 SHA 的完整 Level0 receipt；每次付费尝试绑定 Git/Backend SHA、配置哈希、Prompt 版本、必要性、稳定 Case、Provider/Model、Token/费用、重试/回退及日累计。共享 SQLite 台账使用原子事务阻断跨 runner 换路径、重复首调、预算越界和第二次 Level2；Level0 的小额异常只能由负责人显式授权且上限 0.50 CNY，普通 push 永远保持 0。

包含最终 SHA 的发布清单不能在其自身 Git commit 中自引用，因此 tracked 文档只冻结生成规则；successor 提交 clean 后，由外部 manifest 绑定 final/rollback SHA、镜像 digest、配置/Compose hash、迁移 head/target 与 exact commands。回滚演练从两个 exact SHA 的 Git archive 构建隔离五服务环境，只创建和删除 run-specific PostgreSQL Schema/Compose 项目，验证候选与旧版 API、浏览器和业务数据 fingerprint。Phase 5 没有新增迁移，`20260822_0012 → 20260822_0012` 明确记录为无需 downgrade；不得操作生产、删除本机业务数据库、重写历史或用清单替代真实 dry-run Evidence。

## ADR-050：分组查询只做可审计的无效排序归一化，Live Gate 从服务身份取得 exact SHA

外部 Provider 生成的聚合 SQL 即使通过表、列、函数和只读 AST allowlist，也可能包含数据库无法执行的排序项，例如 `ORDER BY` 引用了既未投影、也未进入 `GROUP BY` 的稳定 ID。SQL Guard 在授权检查通过后，只允许删除这种无效排序项；投影表达式、投影别名、聚合表达式、序号以及已分组表达式必须原样保留。该归一化不得新增列、表、Join、Filter 或 Group，也不得修改选择行和聚合值；每个动作写入 `GuardResult.normalization_actions` 与 `SQL_GUARD` Audit，随后仍必须经过真实 EXPLAIN、只读执行、验证查询和 Result Oracle。合法 SQL 不产生 normalization action。

Phase5 Live Runner 在 Level0/1/2 运行前已经通过唯一成本控制器验证 Backend SHA、Git SHA、配置、Prompt、Gate 和 Ledger Identity，因此 Evidence 的 `tested_sha` 应直接来自该验证后的 runtime identity。发布运行镜像可以继续不安装 Git；Runner 只有在没有合法运行时 SHA 时才允许回退读取 checkout Git，读取失败必须明确标记 `tested_sha_missing`，不得崩溃或用宿主 HEAD 冒充被测 Backend。
## ADR-071 — Server-bound Provider year-grain AST reconciliation

- Status: Accepted (2026-08-26)
- A Provider SQL plan may omit its descriptive `group_by` array while its single
  read-only SQL AST contains an exact `YEAR`/`EXTRACT(YEAR ...)` projection and
  matching `GROUP BY` expression for a typed semantic date dimension.
- The Projection Contract may normalize that alias only when the response is
  marked by the server-owned Model Gateway binding, the resolved Provider equals
  the runtime plan Provider, the semantic column fingerprint matches exactly,
  and the SQL AST group expression matches exactly.
- Bare/unbound plans still fail closed. Provider JSON cannot assert the binding:
  the strict Provider DTO forbids `model_trace`, normalization strips attempted
  server-owned fields, and the runtime attaches the marker after capture.
- This prevents a second paid NL2SQL call for an already valid grouped query
  without relaxing SQL Guard, Result Oracle, or ambiguous projection behavior.
## ADR-072 — Server-bound Provider predicate alignment

- Status: Accepted (2026-08-26)
- For a server-bound live Provider plan, every SQL `WHERE` predicate that uses a
  literal must be represented by the structured `filters` or bounded
  `time_range` fields. Declared structured fields must also be present in SQL.
- SQL AST table aliases are resolved before comparison. An undeclared business
  predicate such as an inferred order status fails closed before SQL execution;
  it is never treated as a harmless model preference.
- The live NL2SQL prompt now explicitly requires predicate/plan parity and
  forbids inferred business filters. SQL Guard and Result Oracle remain intact.
- A failed `QUERY_DATA` projection/provider contract or sandbox validation is
  terminal for that orchestration attempt. The API returns the structured
  failure and never launches a second paid NL2SQL fallback call.

## ADR-073 — Annual Provider output and runtime readiness are canonical gates

- Status: Accepted (2026-08-26)
- Annual/yearly analytical requests require one aggregate row per year. The
  live Provider prompt repeats that canonical output contract and forbids raw
  fact rows; declared metrics and dimensions must each be projected exactly
  once and aggregate metrics must be grouped by the declared dimensions.
- A server-bound annual dimension may use `DATE_TRUNC('year', <date column>)`
  only when its semantic column fingerprint and exact SQL `GROUP BY` AST match.
  `YEAR`/`EXTRACT` remain supported, and unbound or ambiguous plans still fail
  closed before execution.
- Correlation scope identity canonicalizes date/timestamp values to four-digit
  years after Result Oracle validation, so equivalent annual SQL forms produce
  one stable scope without changing result values.
- `RESULT_ORACLE_NOT_PASSED` and DB-GPT runtime timeout are terminal for the
  current orchestration attempt; neither may launch a second paid query. The
  selected DB-GPT runtime import closure is preloaded during Backend lifespan
  startup so readiness reflects the exact runtime before requests are served.

## ADR-074 — Provider Join identities reconcile only through unique table leaves

- Status: Accepted (2026-08-27)
- Result Oracle treats a Provider entity such as `orders` as the same selected
  table as `demo_business.orders` only when that unqualified leaf identifies
  exactly one selected table. Exact qualified identities continue to match
  directly.
- If two selected schemas expose the same leaf name, an unqualified Provider
  entity is ambiguous and the Join fails closed. Join keys or a strict `ON`
  expression remain mandatory; this reconciliation never authorizes a new
  table, column, Join predicate, or SQL rewrite.
- This keeps the Oracle aligned with the SQL Guard and Projection Contract for
  live schema-qualified Provider plans without weakening cross-schema safety.

## ADR-075 — Broad CI unit suites isolate Level0 fallback from injected gateways

- Status: Accepted (2026-08-27)
- The Phase3/IBM workflow keeps Level0 as its workflow-wide default for real
  runners, but clears `CHATBI_TEST_COST_CONTROL` and
  `CHATBI_TEST_EXECUTION_LEVEL` only for the broad Backend unit-test step.
- Those unit tests inject explicit fake gateways and contain no Provider
  credentials. Applying the runtime Level0 fallback to that step replaces the
  injected doubles and tests a different behavior; all later deterministic,
  security, Phase3 and IBM jobs continue to run with Level0 enforced.

## ADR-076 — Functional certification fails closed without independent C-line databases

- Status: Accepted (2026-08-28)
- V1.3.1 Compose and browser certification may start only with an independent
  metadata database and isolated demo schema/database. An isolated Compose
  project name or container network alone is not sufficient database isolation.
- If the application role cannot provision the required database, the result is
  `PARTIAL_BLOCKED_C_DATABASE_PROVISIONING`. The workflow must not reuse,
  migrate, seed, or otherwise mutate the Track A metadata or demo databases.
- Browser/control counts, restart persistence, and start/stop-cycle results stay
  `NOT_EXECUTED` until that prerequisite exists. Provider-only smoke evidence
  may remain valid when it is bound to its exact implementation SHA and a
  persistent sanitized invocation ledger.

## ADR-077 — Runtime provider toggles, local fallback, and administration UI fail closed explicitly

- Status: Accepted (2026-08-28)
- A workspace may disable every external model Provider. In that state the advertised Local Semantic Runtime remains the bounded DATA_QUERY fallback; only the exact `no enabled provider` condition may use it, while transport, authentication, model, contract, Guard, Oracle, and other Provider failures continue to fail closed or follow their existing bounded policy.
- Enabling or disabling a Provider is a configuration persistence action and must not issue an implicit paid request. Credential presence is validated when enabling; network health is measured only by the explicit connection-test action and recorded in the invocation ledger and audit log.
- A connection test is observational: creating its first runtime-health row preserves the Provider's configured-by-default enabled state, while an existing explicit disabled state remains disabled. The probe requests at most eight output tokens so every configured Provider, including premium Kimi, fits the economy health-check budget without relaxing normal routing budgets.
- Non-ADMIN users do not receive navigation into system/user administration. Direct URL access still relies on Backend RBAC as the authority and renders only a permission-denied state after 403, never inactive-looking management controls.
- Chart display uses semantic labels and units from the validated result binding. Axis truncation is presentation-only: the original category value remains available to ECharts tooltip rendering, and numeric axes/tooltips use thousands separators plus the declared unit.
- The final commit cannot self-record its own SHA. Exact-SHA runtime, Browser, Provider, regression, cost, and digest evidence remains external and must be generated only after the forward commit is frozen.
