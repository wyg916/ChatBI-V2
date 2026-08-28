# 项目状态

## 2026-08-29：V1.3.1 最终发布身份 Successor

- P0 Windows 一键启动兼容性已修复：根目录 `一键启动-ChatBI-V2.cmd` 固定使用 Windows PowerShell 5.1，而 `bootstrap.ps1` 曾把 `python -c`、Alembic 与 deployment bootstrap 嵌入同一条 `sh -c` 字符串；WinPS 5.1 在 PowerShell → Docker → Linux shell 边界重写嵌套引号，使 Python 实际只收到 `from` 并报 `SyntaxError`。Bootstrap 现改为四个原生参数调用并逐步 fail-fast，保留单次镜像构建优化。
- 修复后已在 Windows PowerShell 5.1 下从 `0` 个 Showcase 容器连续完成两次停止态启动，其中第一次直接执行根目录 CMD；两次均为 `BOOTSTRAP=PASS`、migration head `20260828_0013`、`VERIFY=PASS`、`START=PASS`，最终 Backend/RAG/Frontend/Sandbox Controller/Sandbox Proxy `5/5 healthy`，版本 `1.3.1`，匿名受保护 API `5/5` 返回 401，外部 Provider 调用 `0`。V1.3.1 部署契约测试 `7/7 PASS`，相关 deployment/system/showcase/migration 定向回归合计 `20/20 PASS`。
- 本轮属于 P0 发布身份与正式发布收口，不新增功能、页面、API、Migration、Agent、RAG、NL2SQL、部署能力或 UI 优化。对已认证候选 `51f130df635e2199208952333ed184191a96091a` 的发布前只读审计发现后端默认版本、前端壳层、Showcase release identity 与 SBOM 元数据仍含 `1.3.0`/`candidate` 当前身份，因此禁止直接发布原候选。
- 唯一 successor 只统一当前产品身份为 V1.3.1，更新公开 README、Release Notes、Rollback、SBOM 元数据和版本契约测试；历史 V1.3.0 Tag/SHA、Phase 文档、Golden Snapshot、workflow 分支名、迁移 `0012` 与依赖组件版本保持不变。
- Successor 必须重新完成版本/Backend/Frontend/TypeScript/build/System Information/Showcase/Enterprise Doctor 门禁，并在冻结新 SHA 后通过唯一 Model Gateway 对 MiMo、DeepSeek、Kimi 各执行一次受控 live smoke。全部通过前不得晋升 main、创建 Tag 或 GitHub Release。

## 2026-08-28：V1.3.1 A/B/C 受控整合候选

- 本轮属于 P0 的发布候选整合与验证，不新增 P2 范围。候选从 C `fbb42a48568985808dbbc12d07728abcb59febc9` 建立，以 `--no-ff --no-commit` 合入 B `656496a470404390d0324b8cdddd4666e4423b6c`；正式 merge commit 为 `9d2dbef8841cfbfab22fb685e58163612e85debe`，A `8f0326b59759e2549e7f684f0a3e40e3b6faffdf` 与 V1.3.0 release `52db955fd67ebe592c289399a135528c13cb3e3d` 均保持祖先关系。main、Tag、Release 均未修改。
- A Showcase：PASS。独立 `chatbi_v131_showcase` Schema 上完成当前正式一键 Stop/Reset/Start/Status，固定端口、固定本地演示账号、Demo Seed 与 deterministic/LEVEL0/no-paid 语义未受 Enterprise Env 污染；Playwright 核心体验目标 45/45。门禁结束后 A 已恢复为固定端口 15173/18080/18081、5/5 healthy，A 自身 Status/Verify/Login PASS，main 仍精确等于 origin/main 且 clean。
- B Enterprise Productization：PASS（冻结前门禁）。唯一 canonical Compose 支持 Default/Showcase/Enterprise/Integration 四种参数化运行形态，活动数据库服务 0、数据库 volume 0；配置优先级统一为 Process/CLI > 指定 EnvFile > 默认 `.env` > 安全默认值。Doctor 0 failure/0 warning，Bootstrap、RAG、Sandbox Worker、统一镜像、两次完全停止后启动、配置负例、备份恢复均通过。
- C Functional Experience：PASS（继承完整 894/894 控件基线并执行整合增量）。整合未修改 Frontend UI 结构；45/45 浏览器主链路与额外管理员写入/重启回读验证覆盖设置、Workspace、Appearance、System Info、User、Role、Invite、Audit、RBAC、Provider Toggle，Analyst API/UI 管理访问均 403，console/page/request error 为 0。
- Integration 免费门禁：Backend 704 collected、697 passed、7 条设计性 skip、0 failed；Frontend 16 files / 64 tests、TypeScript 0 diagnostics、production build 991 modules；迁移唯一 head `20260828_0013`，empty→head、0013→0012→0013、existing 0012→0013 均 PASS；Golden50 的 execution/result/semantic 均 50/50，危险 SQL 56/56；PostgreSQL 与 MySQL 均完成只读连接、9 表/56 字段/12 关系同步及代表查询。
- 元数据备份恢复使用隔离 Schema `chatbi_v131_integration`，V2 manifest 记录迁移头、候选版本、Git SHA、脱敏计数与 SHA-256；备份时 settings/provider/invitation/RBAC/workspace 均为非零。故意修改使指纹变化，恢复后严格回到原指纹。两次停止退出仍观察到 Backend/Sandbox Proxy exit 137 且 `OOMKilled=false`，未见数据损坏、资源泄漏或重启失败，按既有 ADR 保持 registered non-blocking。
- tracked files 冻结后的两套 Enterprise Fresh、Security、exact-SHA Provider 与远端分支核验只写入仓库外受控 Evidence；若任一门禁失败，本候选不得推送或宣称 Integration PASS。

## V1.3.0 POST_RELEASE 求职 Showcase 维护模式（2026-08-27～28）

- 正式发布事实保持不变：annotated tag `chatbi-v2-v1.3.0` 的 peeled commit 仍为 `52db955fd67ebe592c289399a135528c13cb3e3d`，GitHub Release 不覆盖、不重建、不移动。本节及对应脚本属于 main 上的 POST_RELEASE 维护提交，不启动 V1.4、V2.0 或 Production Deployment。
- 唯一本地正式目录固定为 `E:\ChatBI V2 项目`；`scripts/showcase.ps1` 提供 `Start / Stop / Reset / Status`，根目录提供启动、停止、重置三个双击入口。正式端口为 Frontend `15173`、Backend `18080`、RAG `18081`，默认 deterministic / LEVEL0 / no-paid 模式。
- Reset 只重建本机元数据库 `chatbi_v2.public` 并旋转两组公开演示账号；只读业务 Schema 不变。演示数据固定到 `2026-08-17`，PostgreSQL/MySQL `orders` 均为 1,095 行；元数据固定为 2 个数据源、18 张表、112 个字段、24 条关系、2 个语义模型、128 个答案、18 个看板、50 个可下钻 Golden Case 和 6 篇受控知识文档。
- 浏览器现场验收已跑通：登录后默认进入六模块 Chat-first 问数据；“按地区统计订单收入”真实返回 5 行地区收入、ECharts、洞察与明细；数据源/语义模型与目录统计一致；评测中心 Golden 50、八类 Result Oracle、50/50 执行/结果/语义、38/38 危险 SQL 均显示 PASS。
- 清理遵循先盘点、后备份、再删除：全 refs bundle、根 dirty patch/untracked ZIP、Enterprise 并发提交 bundle/WIP patch、IBM/临时 Evidence 清单均保存在 `E:\ChatBI_V2_Safety_Backup\20260827-170500-pre-showcase`。历史 worktree、重复 audit/release clone、Evidence 下 fresh clone、旧 ChatBI runtime/venv、Codex temp/tmp 缓存和 6 组旧 Uvicorn 进程均已退出运行链；正式本机数据库服务和 canonical Docker 栈保留。
- README 与 `docs/showcase/` 已提供求职定位、演示 Runbook、3～5 分钟和 8～10 分钟视频脚本、面试讲解稿以及资源清理记录。最终 Backend 为 679 collected（672 passed、7 个条件性 skip、0 failed），Frontend Vitest 15 files / 60 tests、Vite 994 modules，Playwright 求职核心闭环 45/45；停止态启动连续 2/2，均完成 5/5 healthy、登录、代理、RAG 和匿名 401 门禁。
- 最终本机只注册 `E:\ChatBI V2 项目` 一个 worktree、本地只保留 `main`；并发 Enterprise 最终 `656496a` 与仓库内 `tmp/phase3-edit` 均先生成可恢复外部归档并校验后清理。全仓 `node_modules/.venv/__pycache__/.pytest_cache/test-results/playwright-report` 匹配数为 0；Docker 只保留 canonical 5 容器、3 images、3 networks、0 volumes，并保持 Demo 运行态。

## 2026-08-27：V1.3 Enterprise Quick Deploy 产品化候选

- 本轮属于 P0 的部署稳定性、安全性与易用性收口，只在 `codex/v1.3-next-enterprise-productization` 推进；不改 main、V1.3.0 Final Tag/Release、A 线工作区、A 线数据库或 A 线 Compose 资源。
- 已落地显式配置校验、幂等 Bootstrap、Start/Stop/Status/Verify/Doctor、带 SHA-256 清单的 Backup/Restore、双重确认 Reset 和公共 API 企业主链路 Smoke；Compose 使用独立项目名、镜像名、端口、存储目录和既有本机 PostgreSQL 专用 Schema，不创建数据库容器或数据库卷。
- 当前真实 B 线预验收：Bootstrap 连续两次 PASS（Workspace 1、用户 2、迁移 head `20260822_0012`）；五服务 healthy，缓存启动 106.7 秒；Doctor 0 failure/0 warning；登录、PostgreSQL 只读连接、9 表/56 字段同步、Catalog、语义发布、问数、RAG、文件和固定 Agent 全部 PASS。
- Backup、Restore、Metadata Reset 均完成真实往返；缺必填、畸形配置、错误数据库和端口占用均按预期 fail-fast，错误演练后的运行容器为 0。维护工具已与本机 PostgreSQL 18.4 对齐，备份不含 Secret。
- Windows checkout 下 DB-GPT 与 PandasAI selected-source 的完整性校验改为只规范化 CRLF 后核对冻结 SHA/长度；真实内容篡改仍 fail closed。部署/RAG/系统/数据源专项 14/14、多模态专项 20/20（退出码 0）通过；完整 Backend 套件因宿主 bind-mount 磁盘等待中止，不冒充 PASS。
- Fresh Clone #1 由浅克隆的 clean `5af33ee38f5830ea34900a041c54ce24a7da3090` 执行，确认 `.env`、`.venv`、`frontend/node_modules` 均不存在；Bootstrap、五服务 Start/Verify、Doctor 与 Enterprise Smoke 全部 PASS，总耗时 1612.7 秒。该冷构建因本轮 selected-runtime package 变更重建固定 DB-GPT 262 MB 与 OCR 系统库 220 MB，未达到 15 分钟目标；缓存复用的 Fresh Clone #2 结果以仓库外脱敏 Evidence 和最终交付为准。
- Fresh Clone #2 由 clean `e316e7f5f72d4a63dd3db027424439eb32452b25` 执行，同样没有本地环境或依赖缓存，功能门禁全部 PASS，但 Docker context 扫描和 7 个一次性探针容器使总耗时达到 1314.7 秒，未达到 10 分钟目标。候选随后把三类镜像构建统一到 Bootstrap、禁止 Start 重复 build，并把数据库认证/迁移/head/seed 合并为一个临时容器、Doctor 两个数据库容器合并为一个；优化后的幂等 Bootstrap 实测 45.0 秒，最终性能复验仍以仓库外 Evidence 和交付输出为准。
- Final-SHA 标准 `start.ps1` 复验在配置门禁前发现内部 Bootstrap 数组 splat 把 `-EnvFile` 错当位置参数；该失败启动容器为 0。入口已改为命名参数 hashtable splat，禁止再用 `-SkipBootstrap` 绕过标准路径作为唯一通过证据。

## V1.3.0 Phase 5 发布加固候选（2026-08-22）

- 2026-08-26 `58536b5` 的 MiMo/DeepSeek NL2SQL 与 Kimi M04 均 PASS 后，P5C03 首个 MiMo SQLPlan 在固定 512 tokens 处以 `finish_reason=length` 截断，第二个修复响应正确完成 SQL Guard、EXPLAIN、Result Oracle 与冻结值匹配，但两次调用耗尽 30 秒 Agent 窗口；旧 fallback 又尝试重复 QueryPipeline，并由 `UNNECESSARY_DUPLICATE_PAID_CALL_BLOCKED` 正确阻断。该 SHA 的五条真实响应、账本、Trace、取消与清理证据完整脱敏保留。候选现按受信 `RequestContext.route` 让 `COMPLEX_ANALYSIS` 使用既有 1024-token 上限，并在 Agent 已持有完整 Guard/Oracle/签名结果时直接复用工具证据，禁止重复付费查询；必须形成新 successor，从空账本重新认证。
- 2026-08-26 `f942d9c` 的 exact-SHA Level0 全部通过后，FINAL 认证的 MiMo/DeepSeek NL2SQL 与 Kimi M04 先 PASS；P5C03 本次返回 `left_table/right_table + on` Join 元数据，SQL Guard、EXPLAIN、四行冻结值和复核查询均正确，但 Oracle 尚未识别该严格等值表达式，主 Agent 被错误标为失败并触发一次数据回退。该 SHA 的 5 次响应、0.02380574 CNY 账本、Trace 与清理回执完整保留。候选现只用 SQLGlot AST 接受左右端点均为已选表、每个 ON 叶子都是两端非空限定列之间 EQ 的单键或 AND 复合键；OR、常量、函数、无表限定、Schema/Catalog 限定和端点越界继续 fail closed。必须形成新 successor 并从空账本重新认证。
- 2026-08-26 `90316c2` 的 FINAL 代表认证在 MiMo/DeepSeek NL2SQL 与 Kimi M04 均 PASS 后，由 P5C03 暴露新的 Oracle 结构缺陷：MiMo 返回 `left_table/right_table + join_keys`，SQL Guard、EXPLAIN、四行结果、复核查询和 Canonical 输出均正确，但 Result Oracle 只接受同表端点配 `left_column/right_column`，错误标记 `join_semantics` 失败并触发数据回退。该 SHA 的 5 次真实调用、两条 P5C03 响应、Trace、账本和清理回执完整保留。候选现只在左右表均属于已选表，且 `join_keys` 为非空列表、每个键都含非空左右列时接受这一 Provider 形态；表越界、空键、半键及列形态不完整继续 fail closed。必须形成新的 forward successor，从空账本重做 exact-SHA Level0 与最终 Provider 认证。
- 2026-08-26 `bbcef23` 的新 FINAL 认证先完成 MiMo/DeepSeek NL2SQL、Kimi M04 与 P5C03，并证明取消探针均在 0 Provider 调用下收敛；P5C04 的真实 DeepSeek 年度聚合把 `EXTRACT(YEAR FROM order_date)`、`SUM(revenue)` 与 `SUM(cost)` 放在唯一 CTE 中，外层只投影 `yr/total_revenue/total_cost`。旧 Projection Contract 只比较外层 Column，无法沿唯一 CTE 输出回溯语义表达式，正确以 `PROJECTION_MISSING_EXPECTED_OUTPUT` fail closed；第二次修复响应、完整账本、Trace 与清理证据均已脱敏保留。候选现只解析“外层单一 CTE、无 Join、输出名唯一、内层表达式唯一”的 AST lineage；年度维度还必须在同一 CTE 的 GROUP BY 中出现，歧义或未分组继续拒绝。规范结果列仍为 `order_date/revenue/cost`，相关性工具按 Canonical `order_date` 年粒度形成 `2025_2026` scope，不恢复 Provider alias。必须形成新的 forward successor，并在其 exact SHA 上重新执行受影响免费门禁和最终 Provider 认证。
- 2026-08-26 `4344888` 的 P5C03 最终实跑证明 SQL Guard、EXPLAIN、复核查询、Result Oracle 与四行冻结值均正确，但固定 `QUERY_DATA` Tool 未继承外层 FINAL `request_id/trace_id`，首个工具内 NL2SQL 在网络前以 `FINAL_CASE_NOT_IN_EXECUTION_PLAN` 拒绝并触发数据回退，造成 Agent Steps/Trace 失败；取消探针还因 `run.started` 后工作线程立即启动而在取消到达前完成一次付费调用。候选现把同一受信 RequestContext 传入固定 ToolExecutor，并在首个 SSE 事件之后、工作提交之前提供 100ms 可中断抢占窗口。冻结 P5C03 未声明顺序，验证器改以唯一品类键对完整行关系做一对一精确比较；显式升降序 Case 仍保持序列敏感，重复键、缺行或任意单元格差异继续 fail closed。旧 SHA 的五条响应、0.03147514 CNY 账本与失败回执完整保留；必须在新 forward successor 上从零认证。
- 2026-08-26 `67cdfa8` 的新 FINAL 运行先完成 MiMo NL2SQL 端到端 PASS，随后 DeepSeek 返回真实 `SELECT SUM(revenue) AS total_revenue FROM orders`；数据目录中 `revenue` 同时属于 `orders` 与 `daily_kpi`，旧 Projection 指纹只看全局 owner，未结合 SQL AST 唯一可见表，因此以 `PROJECTION_MISSING_EXPECTED_OUTPUT` fail closed。两条响应、账本费用与清理回执完整保留，Complex/Kimi 暂停。候选现只在授权 owner 与 AST 可见表交集恰为 1 时解析未限定列；两表同时可见的同名列永久负例继续拒绝，并新增该真实 DeepSeek 脱敏响应的全链 Recorded 回归。必须形成新的 forward successor 并重做受影响零付费 Gate 与最终认证。
- 2026-08-26 `12b002a` 已完成 exact-SHA 免费 Delta：Backend 647 collected（641 PASS、6 条既有条件性 SKIP）、Projection 17/17、Data100 100/100/值准确率 1.0、Weird50 50/50、Complex5 与 Cancel 5/5、清理通过、真实 Provider 0。随后第一条 FINAL MiMo 返回 HTTP 200、NL2SQL 校验 PASS、canonical `revenue`，但认证辅助脚本错误选择了已发布但未同步且 `table_count=0` 的 MySQL 演示数据源，SQL Guard 以 `TABLE_NOT_AUTHORIZED` 正确拒绝；该次 1 条响应、账本费用 0.00567724 CNY 和清理回执完整保留，DeepSeek/Kimi 未启动。候选现明确最终认证只能绑定已同步且有表的发布模型；不得删除旧账本或消耗原 Case 的第二次调用，必须形成新的透明 Successor 并从空账本重做。
- 2026-08-26 `a0def7b` 的最终代表性 Complex 实跑保留了两个独立缺陷证据：P5C03 的 Provider Join 采用四字段表/列形态，已选表与冻结结果均正确但 Result Oracle 未识别该已校验契约；P5C03/P5C04 取消请求 ID 未命中只覆盖主请求的 FINAL Case 模式。候选现以严格表成员与非空列约束补齐 Oracle，并让主请求与取消请求共享原有计划额度，不新增调用、预算或重试。旧 SHA 的五次真实调用与失败响应只作诊断保留；必须形成新的 forward successor，并从零完成同 SHA Level0、最终 Provider、推送与远端 CI 后才可宣布 Phase 5 PASS。
- 2026-08-26 最终 MiMo 真实 NL2SQL 结果暴露输出别名契约缺口：SQLPlan 声明 `revenue`，Provider SQL 投影为 `SUM(...) AS total_revenue`，数值 `1725750.0` 正确但 Result Oracle 按规范列名正确 fail closed。候选在 SQLPlan 与 SQL Guard 之间新增 Canonical Output Schema、Projection Contract Validator 和 AST 安全别名规范化；只有 SQLPlan、语义对象和投影表达式形成唯一一对一映射时才同步改写 SELECT alias 及合法依赖引用，歧义、重复、缺失、额外输出和不安全依赖继续 fail closed。真实脱敏 MiMo 响应已固化为 Recorded Fixture。首次提交前零付费 Delta 已实际通过投影契约矩阵 15 项、Backend 636 PASS/6 条既有条件性 SKIP、Data100 100/100（结果值准确率 1.0）、Weird50 50/50、Complex5 5/5、Frontend 60/60、代表 Browser 27/27、逻辑控件 20/20、隔离冷启动含 Golden50、安全供应链与依赖审计；Real Provider calls=0。本条不放宽 Result Oracle、SQL Guard 或执行器，也不预先声明最终 Provider、远端 Push/CI 或 Phase 5 总 Gate PASS。
- 2026-08-26 首个投影 Successor 的代表性 Complex 实跑保留了两项新 Evidence：本机认证解释器缺少冻结 DB-GPT AWEL 分发；年度聚合 SQL 的 `YEAR(order_date) AS year` 无法与 Canonical 日期维度唯一绑定。前者属于外部运行时闭包，必须按已冻结 commit/archive SHA 和审计后的 aiohttp metadata 恢复并通过 `pip check`/真实 AWEL call；后者在 Projection Contract 内新增 SQL AST + SQLPlan group_by + 日期语义表达式三方精确绑定，且只支持冻结的 YEAR grain。新增正负矩阵后投影专项为 17/17，缺少 Plan group_by 的同形 SQL继续 fail closed；必须形成新的 forward successor 并重做受影响免费 Delta 与最终 Provider 认证，旧 SHA 的付费结果不得冒充新 SHA 最终 PASS。
- 2026-08-25 失败候选 `1e665af1a33220e16d01e13e07579a62f2f7f143` 的三项最终阻断已进入最小修复候选：Provider 响应经唯一严格归一化边界后再做 SQLPlan/SQL Guard 校验；FINAL 代表 Case 计划在网络前原子执行 Case/Provider/Run 三层限额并保留 Kimi Vision 容量，Token 与 Provider 账单未知状态显式记账；同步 Chat 纳入可取消 Lifecycle，Runner 超时必须获得 Backend 取消确认，删除会话等待有界终态。历史执行未保留原始 Provider Body，新增 Fixture 明确为负责人授权的通用协议变体。该条不预先声明 Successor、免费 Gate、真实 Provider、远端 Push 或 CI PASS，结论只以冻结后的 exact-SHA 外部 Evidence 为准。
- 2026-08-25 负责人批准将重复的 Level1/Level2 付费认证合并为一次 `FINAL` 代表认证。候选现为成本台账增加真实 `FINAL` 等级、每 Run 最多 12 次真实 Provider 请求及 3.00 CNY/日 5.00 CNY 既有预算，并允许最终认证只选择 2～3 个 Complex 与 1～3 个 Multimodal 代表 Case；旧 Level1 定向与 Level2 全量语义保持兼容。最终 Provider、远端推送与远端 CI 结论仍只以 clean successor SHA 的外部 Evidence 为准，本条不预先声明 PASS。
- 2026-08-25 `484318915ca159ca9419d15747497d4681bd2110` 同 SHA Level0 长负载在 8295 次请求中捕获 1 次低频 HYBRID 失败；仓库外诊断集中负载复现 5/7738 次并读取同请求 QueryRun，全部根因为 EXPLAIN 等待非公平共享槽位超过 30 秒，内部 `QUERY_CONCURRENCY_LIMIT` 被安全映射为 `QUERY_EXPLAIN_REQUIRED`，数据库未被访问。最小修复将固定并发上限实现为可取消 FIFO ticket 队列并锁定单例初始化，不增加 retry、不提高并发、不放宽超时或 EXPLAIN Gate；相关并发、取消、Fault 与成本回归 48/48 通过，真实 Provider 调用 0。必须形成新的 forward successor 并在其上重做 Same-SHA Level0，旧 SHA 的 PASS 证据不得继承。
- 2026-08-25 冻结候选 `3508539d0b0b335f70b5766e5c90df55e9420e73` 的完整控件认证真实执行 390/390，暴露 10 个认证器持久化误判：Ask 结果 URL 刷新会合法追加一次确定性查询，Evaluation 会从 RUNNING 异步收敛到终态，而旧 Gate 要求动作后与刷新后整组聚合指纹精确相等；另有一次反馈已新增 DB 行但浏览器 response listener 未观测 transport。失败 Evidence 原样保留。后续最小修复在 DB probe 中加入脱敏行身份摘要：普通同步组仍要求精确状态，Chat/Evaluation 则要求动作后所有行身份在刷新后仍存在、行数不下降且变化表可追溯；DB 变化加独立 API readback 可作为显式 transport N/A，不冒充网络捕获。永久正/负回归、原失败 10/10、输入身份 24/24、Frontend 60/60、TypeScript 与 build 已通过；必须再形成 forward successor 并从新隔离 Schema 重做完整 Same-SHA Level0。
- 2026-08-25 Phase 5 控件身份契约候选已将展示标签、逻辑控件 ID、定位身份和可变值明确分离；输入控件身份禁止使用当前值或可编辑文本，并以表单/容器作用域和稳定序号消歧。提交前永久输入回归 24/24、历史失败控件 2/2、Frontend 60/60、TypeScript 和 production build 通过；两次独立发现的 Universe Hash 均为 `e495cbe9af09bfe250278d6a0464f6d47af58c729a5fa913c154f12ca6e30951`、Inventory Hash 均为 `1d500fd0edf555f270e8b862e5a379aec004b15252d313322e770300186600b5`，可见/可操作控件均为 475/390，身份使用可变值为 0。该条只记录冻结前最小修复证据；完整 Same-SHA Level0、Level1 许可与最终发布结论仍须由新 forward-history successor 的外部 Evidence 决定，真实 Provider 调用保持 0。
- 2026-08-24 `82ee93eecabe567d717d866c0c31ac3077e3474d` 的受控 Level1 P5C01 暴露了真实 SQL 有效性缺口：Provider 在聚合 SQL 中生成 `ORDER BY r.region_id`，但未把该列加入 `GROUP BY`，SQL Guard 仍放行，EXPLAIN 以 `QUERY_EXPLAIN_ERROR` fail closed，Complex 编排终态保持 REFUSED。后续最小修复只从分组查询中删除既非投影/别名/聚合、也未分组的 ORDER BY 项，保留结果行、聚合值和其余排序，并把 normalization action 写入 Query Audit；合法已分组排序保持不变。发布镜像内的 live Runner 同时改用成本控制器已验证的运行时 SHA 身份，不再依赖镜像内安装 Git。修复后 Backend 581 collected（574 passed、7 skipped）与专项 Query/Live Runner 回归通过；必须先形成新的 forward-history successor 并重做 Same-SHA Level0，不能沿用 `82ee93e` 的 PASS 证据。该次 Level1 台账保留 8 条付费尝试记录、7 成功/1 失败连接记录、1 次有界重试、0 fallback、0 untracked，实际费用 CNY 0.06744162；P5C01 未通过，Level2、生产 Key 轮换、远端推送与远端 CI 均未开始。
- 2026-08-24 Successor 同 SHA Level0 在发布后端镜像中发现扫描 PDF OCR 无法导入 OpenCV：`python:3.11-slim` 缺少 RapidOCR 3.9.2 所用 GUI OpenCV wheel 的 GLib/XCB/OpenGL 运行库。候选 Dockerfile 现显式安装 `libgl1`、`libglib2.0-0`、`libxcb1` 并清理 apt 索引，静态回归固定该边界；最终 PASS 仍须以新 forward-history SHA 重建镜像并重新执行 M10、受影响回归和完整 Same-SHA Gate 后决定。
- 2026-08-24 最终 Successor 收口正在从已认证基线 `3afbfb8f5e06ce9fb370ea0598ed55b05978f9c3` 仅以 forward history 形成：Dashboard 的业务数据读取已移除 `connector.read_rows`，统一进入既有 SQL Guard/QueryExecutor/只读事务/超时/并发/行限/Audit/Trace/结果签名链；静态 Gate 只允许 QueryExecutor、连接测试/元数据同步与测试成本 SQLite 台账的明确边界。测试成本 Gate 已加入同 SHA Backend/配置/Prompt 身份、完整 Level0 receipt、必要性声明、共享原子台账、重复/重试/日预算和每 SHA 一次 Level2 约束；Level0 默认费用仍为 0。391 份历史 receipt 中只有 Network 与 API 同时为空的 47 份允许定向重跑，其余只做可追溯 schema v2 归一化。发布与回滚清单改为 clean successor commit 后生成外部 exact-SHA manifest，回滚仅在隔离 Schema/Compose 项目中演练。提交前受影响 Backend 51/51、Frontend 60/60、TypeScript、production build 与语法检查已通过，真实 Provider 调用 0；Phase5 总 Gate、Level1/Level2、生产 Key 轮换和远端 CI 仍等待 successor 同 SHA 全量证据，不预先宣称 PASS。
- 2026-08-23 Level 0 最终 Blocker 收口候选已加入真实可见控件逐项认证和 CPU 归因：Inventory 以 Playwright 真实可见性排除折叠区内隐藏控件，每个可操作控件生成独立 Browser/API/DB/Readback/Refresh receipt；20×15 负载新增 5 分钟 Idle Baseline、Backend/PostgreSQL/Sandbox/Docker VM/Load Generator/Browser/Other 进程分类及 Load Generator 2 核 CPU 亲和性隔离。提交前专项 23/23、Frontend 60/60 和 production build 已通过；Level 0 总结论仍只能由冻结后同一 SHA 的外部全量 Evidence 决定，本条不预先宣称 PASS。
- 2026-08-23 Level 0 blocker remediation 已完成 Data100 100/100（结果值准确率 1.0）、Weird50 50/50、Complex5 5/5、扫描 PDF 本地 OCR/视觉链、两次冷启动、成本台账覆盖率 1.0、供应链/安全故障门禁、Backend 562 collected（556 passed、6 skipped）及 Playwright 串行 89/89。全程付费 Provider 调用 0、费用 0.00 CNY；历史 Phase 5 失败 Evidence 均保留在原目录，新证据位于独立 `Phase5_Level0_Blocker_Remediation_20260823_1315` 根目录。
- 20 用户 × 15 分钟实际完成 6,841/6,841 请求且业务校验率 1.0，P95 7,046.752 ms、Backend CPU P99 56.083%、DB 连接最大 48、无资源残留；但宿主机 CPU P99 为 98.366%，超过固定 90% 门槛，因此 Load Gate 仍为 FAIL，不降低阈值也不重复执行昂贵长稳态测试。
- 真实浏览器盘点覆盖 21 个页面、831 个可见控件，其中 748 个可操作控件；该执行只完成 Inventory，逐项 Browser→API→DB→Readback→Refresh 认证数仍为 0，覆盖率 0。受控临时 ADMIN 与认证状态已精确清理并有回执。由于控件矩阵和宿主 CPU 两项仍阻断，Level 1 定向真实 Provider、Level 2 最终付费认证、Phase 6、main 合并和 V1.3.0 Tag 均保持禁止，Phase 5 总门禁仍为 FAIL。
- ONE_TRACE 无筛选概览在长稳态数据积累后曾因全历史 ORM 装载耗时约 6.35 秒；现在对每类持久化源精确读取最新 N 个候选后再做 Trace 合并，最近 200 条结果和 complete coverage 不变，实测约 0.90 秒。筛选视图与单 Trace 详情仍走完整历史语义。隔离浏览器端口通过显式 CORS origin 配置接入，带凭据 CORS 继续拒绝空值和通配符。
- 2026-08-23 Phase 5 FAIL 后续修复启用三级测试成本控制：普通 push 与每次修复默认 Level 0，只允许 deterministic/recorded/Mock Provider，Model Gateway 在真实 HTTP 前硬阻断付费调用；Level 1 仅允许 1～3 个受影响 Case、Provider allowlist、最多一次重试和 1.00 CNY 定向预算；Level 2 必须绑定同 SHA 的全 PASS Level 0 receipt、负责人授权、cache bypass、3.00 CNY 最终预算和 5.00 CNY 日硬上限。成本台账只保存 Run/SHA/Case/Provider/Token/Cost/Retry 等脱敏字段。该策略不改变任何最终 Phase 5 Gate，当前 Phase 5 仍为 FAIL，未开始最终付费认证。
- 本次成本控制候选的零付费验证为 Backend 546 collected（540 passed、6 skipped、0 failed/error）、Frontend 15 files/60 tests、TypeScript、production build、3 个 workflow YAML 和成本控制专项 9/9 PASS；Provider 实际调用与费用均为 0。完整 Phase 5 Data100、674 Control Matrix、Browser、Cold Start、20×15、Remote CI 和最终真实 Provider 认证仍按原 FAIL 清单逐项收口，不得用本次策略测试替代。
- 2026-08-23 前端全可见控件追加门禁已进入同一候选：数据源/数据表、语义模型/资源和成员搜索筛选均把条件传入 Backend API 并由 Workspace 约束的数据库查询执行；答案库“待审核”枚举已与后端契约对齐。无实现的工作空间筛选已移除，P1 壳控件保持禁用并说明边界。新建或导入看板不再接受客户端卡片数，看板列表、排序、汇总和详情均从真实 `dashboard_card` 行派生数量，“今日刷新”从当天成功 `REFRESH_CARD` 审计行派生；演示 Seed 不再预填虚假卡片或刷新计数。最终可见控件覆盖率和浏览器结论仍只以最终 SHA 的外部 Evidence 为准。
- Phase 5 以 `89bdc12936be0555bdad8a85f06932fb7dc476ee` 为唯一 Phase 4 基线，在短期分支 `codex/v1.3.0-release-hardening-full-gate` 只做测试、Evidence、性能、安全、故障恢复、依赖兼容和发布工程加固；不启动 Phase 6，不修改 `main`，不创建 V1.3.0 Tag 或正式 Release。
- Sandbox Controller 不再直接持有 Host Docker Socket。唯一持有只读 socket bind 的 restricted proxy 只接受固定 worker 镜像、命令、non-root 用户、无网络、只读根文件系统、能力清空、no-new-privileges、确定资源上限和所有权标签的有状态 Docker API 子集；未知字段、Host namespace、任意容器或 Docker 管理请求一律拒绝。最终风险关闭仍须由同一候选 SHA 的真实 worker/cancel/destroy 与负向攻击实跑证明。
- GitHub Actions 已迁移到不可变 Node 24 action SHA；应用 `httpx==0.28.1` 与 Starlette `httpx2==2.12.0` 兼容桥分别精确固定。冻结的 DB-GPT source/archive 不变，安装时验证 exact provenance 后把未使用但易受攻击的 `aiohttp==3.8.4` 依赖 metadata 精确修正为已审计 `3.14.3`，同步 RECORD 并强制 `pip check` 零冲突。Phase 5 新增确定性 SBOM、许可证/依赖/Secret/攻击审计、独立迁移 Gate 和 Phase 1～4 工作流复验；外部审计输入必须绑定工具版本、依赖清单哈希和被测 Git SHA。
- Data100、10M、20 用户 15 分钟六路 API、Weird50、Complex5、三 Provider 及 DB/RAG/Sandbox 故障、Multimodal10、两次冷启动、完整浏览器、成本账本和远端同 SHA CI 只有在外部 Evidence 真实执行并通过后才能标记 PASS。Weird/Complex 与 API 混合负载的准确性由冻结 rows、result signature、answer claims、citation chunk 和文件/视觉值独立重算，不信任服务自报 VERIFIED/PASSED。远端 workflow 最终 job 只签发 deterministic/migration/supply 的同 SHA CI 证书，并明确不冒充完整 Phase 5 Release Gate。清单结构、直接 SQL 压测、合成故障信封和历史 Phase 1～4 结果均不能替代最终门禁。
- 候选发布文档只描述范围、回滚和待验收条件；最终 SHA、测试计数、性能数字、成本比例、远端 Run ID、Evidence 校验和与 Phase 5 总 Gate 以本轮最终外部 Evidence 为唯一事实源。

## V1.3.0 Phase 4 产品体验与治理候选（2026-08-22）

- Phase 4 从唯一基线 `8ccf60d2b915406a954790a4f8bf9f3e48b6c60e` 在短期分支 `codex/v1.3.0-product-experience-governance` 增量开发；原共享工作区的用户 WIP 保持原样，`main`、V1.3.0 Tag 与 Phase 5 均未触碰。
- Chat、Analysis、SSE、受控 RAG、固定 Agent、文件和视觉回答统一输出 canonical `AnswerEnvelope`；React 只通过 Dynamic Renderer 消费 Text/Markdown、KPI、Chart、Table、Citation、Artifact、SQL、Evidence、Warning 与 Follow-up。Markdown 使用 `react-markdown + remark-gfm + rehype-sanitize`，不启用 raw HTML；Citation URL、Artifact 文件名与公开阶段都执行 allowlist/脱敏。
- Conversation 已形成完整服务端资源：搜索、重命名、Pin、Archive/Restore、Delete、Project 归属、多选批处理与只读 Share。Share Token 只保存哈希，可过期、撤销，公开响应执行字段 allowlist 与私有 URL/SQL/Trace/敏感内容过滤；Archived Conversation 在恢复前不可继续提问。
- 模型每一次成功、失败、重试和取消尝试写入 append-only `ModelInvocation` 运营台账，只保存 allowlist 元数据。Cost 支持时间、当前 Workspace、用户、会话、路由、Provider、Model 过滤和分摊；ONE_TRACE 展示真实阶段开始时间、耗时、状态、Provider/Model、Tool、SQL/错误与 Artifact 能力，不展示提示词或思考过程；ECharts 已拆为 `EChart` 与 `zrender` chunk，生产构建不再产生 500 kB warning。
- Feedback 状态冻结为 `OPEN → IN_REVIEW → ACCEPTED/REJECTED`。只有经过 QueryPipeline 的 SQL Guard、只读执行、Result Oracle、数据源/语义版本/结果签名绑定并带 Reviewer/Attestation 的候选 SQL 才可晋升 Verified SQL；Replay 重新走同一安全链并写审计和回归证据。
- PostgreSQL QueryExecutor 的 EXPLAIN 与真实只读查询现在都把数据源批准的 schema 作为经过标识符转义的事务级 `search_path`。这消除了模型对同一合法查询偶尔省略 schema 时产生的 `QUERY_EXPLAIN_REQUIRED` 随机失败，同时没有扩大 SQL Guard 的表和 schema allowlist。
- 最终 PASS、测试计数、两次停止态冷启动、远端同步、同 SHA Phase4/Phase3/IBM CI 与 Evidence SHA-256 只以本轮外部 Evidence 和最终交付输出为准；仓库文档不预先宣称尚未完成的远端门禁。

## V1.3.0 Phase 3 RAG / Agent / File / Multimodal 候选（2026-08-22）

- Phase 3 从 Phase 2 精确基线 `c51c2f238bce0e26777c831fb9b44455b58d4c5c` 在隔离短期 worktree 开发；原共享工作区 WIP 不清理、不覆盖。本节记录候选实现，最终测试、提交、远端与同 SHA CI 结论只以外部 Evidence 和交付输出为准。
- DB-GPT 固定 `db580e952e544acf9f6c6c153da29dc67e9e40d7`，仅 `dbgpt-core/AWEL` 的 `DAG`、`MapOperator`、`BaseOperator.call` 进入运行时；AWEL 只接收路由、Trace ID 与硬预算，再调用 ChatBI 固定五角色六工具编排。应用、RAG、数据源、认证、会话、模型凭据和 Skills 均不进入边界。
- PandasAI 固定 `bbbb771d31062d81f6fa19bafb40620d5cbe48f4`，仅直接复用 MIT community `pandasai/sandbox/sandbox.py`。简单文件问题仍由全文件确定性操作执行；复杂关联才经该基类和独立 Sandbox Controller 进入一次性 Docker worker；Backend 无 Docker socket，Controller 仅接受固定协议并强制不可变安全配置，Docker/来源/协议不可用时 fail closed。
- 文件链路支持 CSV/XLSX 全文件解析、公式/提示词注入检查和可定位证据；Vision 统一做方向归一化、去元数据、缩放/分块、敏感字段脱敏和 VisualEvidence 缓存。普通视觉默认 MiMo，仅明确多图、低质量文档或大图分块触发 Kimi；图片不发送给 DeepSeek。扫描 PDF 由固定 pypdfium2 渲染为 PNG 后进入同一受控 Vision 链。
- 图片与数据库对照只接受单个可解析视觉数值，并重新进入现有 DATA_QUERY 的 Schema/Semantic/NL2SQL/SQL Guard/只读 Executor/Result Oracle；数据库证据必须保留 Query Run、Guard、Oracle 与结果签名。同步与 SSE Trace 分开记账，只有真实流式入口记录 `sse.stream`。
- 项目负责人已明确确认 `E:\新能源企业经营分析智能平台` 为其自有旧项目并授权内部复用，因此 Legacy RAG 外部权属审计不再是 Gate。旧项目锁定在 `b2573a9dc1881a54581c5c556fb4a8c34046f9c3`，仅把 byte-identical `indexer.py`、`reranker.py`、`security.py` 作为 selected source 引入；ChatBI 继续独占 HMAC、Workspace/RBAC/ACL、Citation、单一 Model Gateway、Answer Guard、Trace/SSE 与数据模型。自包含 Legacy Gate 为 Knowledge 20/20、真实 selected-source runtime calls 20、Citation Accuracy 1.0，越权/跨场景/Prompt Injection 证据/跨 Workspace 均为 0；最终状态仍须由 Successor SHA 全量回归和同 SHA 远端 CI 绑定。
- 最终提交前本地候选门禁：Backend 391 collected（385 passed、6 个显式外部运行时门禁 skipped）、Phase3 全显式真实 DB-GPT/Controller/Worker 专项 113/113、Phase1/2 定向回归 47/47；同一精确 AWEL runtime 的 Golden Agent15 为 15/15 并累计 15 次 `BaseOperator.call`。File12 真实全文件/Controller/Sandbox runner 为 12/12，三模型真实多模态 runner 完整有界复验为 10/10，Frontend Vitest 13 files/50 tests、TypeScript、Vite 741 modules 均通过。Playwright 完整执行 85 项时 84 项通过，唯一 MiMo HTTP 200 后未形成可接受回答的外部模型失败项保留原日志并按同一真实拓扑有界复验 1/1 通过；不把首轮外部模型失败隐藏成单次 85/85。隔离 Compose 四服务从停止态连续两次 4/4 healthy，分别 30.61s 与 29.38s。上述结论仍须绑定最终 clean SHA，并由 GitHub-hosted Phase3 artifact 与同 SHA IBM self-contained CI 复验后才能作为远端发布门禁结论。

## V1.3.0 Phase 2 数据主链与真实上游接入（2026-08-21）

- OpenChatBI `c8786cb...` 的 `catalog_store.py` 与 WrenAI `7830cc7...` 的 `type_mapping.py`/`wren_dialect.py` 已按 canonical Git blob 字节等同 vendoring；IBM `60dd451...` 的 11 个 Apache-2.0 selected-source 文件由外部固定 checkout 的隔离 Python 执行且逐文件校验 SHA-256。真实直接复用项目数为 3；ChatBI 不复制或分发 IBM 源码、wheel 或 benchmark bundle。
- PostgreSQL 同库同 Schema/模型/权限 A/B 为 Golden 50 + 复杂改写 20：clean-room 与 selected-source 的执行、结果、语义、Join、澄清均为 70/70；selected-source OpenChatBI/Wren 调用为 588/140，Catalog Recall@5=1.0，A/B 总延迟 p95 为 535.033/397.603 ms，模型 Token/成本/重试均为 0。
- SQL 执行新增 fail-closed EXPLAIN Cost Guard；关键指标/多 Join 新增第二次经 SQLGlot 与同一权限策略保护的只读一致性查询；Oracle 新增 Chart/Narrative 结果绑定。Verified SQL 审核和回放新增 SQL SHA-256、数据源、语义模型/version 与结果签名防篡改。
- 回归结果：Backend 256/256、定向安全 110/110、Frontend Vitest 50/50、TypeScript、production build、Golden 50 与八维 Oracle、危险 SQL 56/56、三模型真实 Discovery/Auth/Chat/SQLPlan/Guard、确定性 E2E 12/12 均 PASS。E2E 首轮误继承开发机 `MODEL_PROVIDER=auto` 而得到 7/12，失败日志保留；显式恢复发布基线 `deterministic` 后完整重跑 12/12。10M 数据源同步为 79 表/1187 字段/111 关系；Docker Compose 从停止状态连续两次启动为 healthy，验收后停止栈、删除临时 metadata Schema 并确认不存在。
- IBM package/wheel 模式仍因 Apache-2.0/MIT 分发元数据冲突而 BLOCKED，但 11 个具明确 Apache-2.0 SPDX/根许可证治理的 selected-source 文件已经闭合。本地官方 `evaluate_prediction` 真实调用 50 次、`get_failed_records` 执行 1 次，execution accuracy 50/50、multiple GT、error analysis 与 Release Gate 均 PASS。Phase 2 Closure 将 CI 改为 GitHub-hosted 自包含模式：临时 PostgreSQL、迁移、固定演示 seed、一次性认证、localhost Backend、固定 IBM checkout、Golden 50 与校验和 artifact；不再依赖外部 `api_base`、生产数据、Provider Key 或长期仓库 Secret。远端 run 是否 `ENFORCED` 只以同一 Closure SHA 的外部 Evidence 为准。
- SQLBot 因 modified GPL 品牌条件、无路径级宽松授权、启动前强制导入的 `sqlbot-xpack 0.0.5.35` 无许可证/公开源码闭包及官方镜像不可固定到目标提交而继续 BLOCKED；official runtime calls=0、xpack loaded=0。正式 Requirement Delta 与 V1.3.0 License Exception 保留 ChatBI clean-room feedback/replay 为 PASS，但不把它计为 SQLBot 上游复用；真实直接复用项目数固定为 3。
- V1.3.0 Requirement Delta、SQLBot Exception、最终 Closure SHA 的回归、非强推交付、local/tracking/`ls-remote` 一致性及 IBM 远端 run 均由外部 Phase 2 Document-Compliant Closure Evidence 验收。本文不预先宣称远端 PASS；不创建 Tag、不修改 main，源工作区 WIP 保持隔离。

## V1.3.0 Phase 1 三模型统一控制平面（2026-08-21）

- Phase 0.6 已按用户最新授权通过：`CURRENT_DEV_KEYS_AUTHORIZED=YES`、`THREE_MODEL_SECRET_CONFIGURATION=PASS`、`SECRET_LEAK_IN_EVIDENCE=0`、`SECRET_LEAK_IN_GIT=0`。三模型 Key 轮换延期到 V1.3.0 Final Release/生产/公开切流前，不阻塞 Phase 1～5 开发测试。
- Phase 1 在独立分支 `codex/v1.3.0-runtime-control-plane` 从 `chatbi-v2-v1.2.0^{}` 增量实现，不合入本地主工作区的 V1.2.0 后续候选提交，也未重跑 Phase 0/0.5。
- Provider HTTP 调用已收敛到单一 ModelGateway；新增 Request/Router/Model 契约、MiMo/DeepSeek/Kimi Alias 与能力配置、真实 usage 成本、Economy/Balanced/Quality 预算、重试、熔断、回退、取消和安全健康摘要。
- Chat/Analysis/Query/SSE 已统一 `trace_id/request_id`，语义缓存加入权限哈希；日期问题走服务端 L0 `MODEL=NONE`，创作语境中的“收入”不再误路由到 DATA_QUERY。
- Phase 1 功能与本地发布门禁已通过：Backend 236/236、Frontend 50/50、Vite 741 modules、统一控制平面专项生产 E2E 3/3、Golden 50/50、迁移单 head 与 upgrade→base→upgrade、两次停止态 Docker 启动 2/2、三模型真实 Smoke 3/3、Secret Scan 0。最终提交 SHA 与远端同步状态由独立 Evidence 和交付输出记录；未创建 Release Tag，正式发布仍受三模型密钥轮换门禁约束。

## V1.2.0 正式发布冻结（2026-08-20）

- `RELEASE_STATUS=FROZEN`
- `VERSION=V1.2.0`
- `TAG=chatbi-v2-v1.2.0`
- `FINAL_RELEASE_SHA=chatbi-v2-v1.2.0^{}`；annotated Tag 的 peeled SHA 是最终发布身份，推送后的 local/tracking/`ls-remote` 一致性记录在正式交付中。
- `P0_BLOCKERS=NONE`；`P1_BLOCKERS=NONE`。
- `main` 由 `094c81a` fast-forward 到正式集成 `5303bdb`；随后增加版本元数据、发布文档、SBOM 与冻结 Manifest，并只修复正式 main-SHA 门禁发现的停止生成持久化竞态。业务口径与其他已通过的 ChatBI 能力未改变。
- 最终 Backend 门禁为 225/225；停止生成采用经会话/用户授权、按 client message 精确定位的显式服务端取消，等待匹配 worker 结束并完成提交窗口后的二次清理，再终止 SSE。事务型停止门禁连续 10/10、两次停止态启动 2/2、完整 82/82 发布门禁通过。
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
- Phase5 final Provider P5C04 follow-up: bound exact SQL-AST year-grain aliases
  can now satisfy the canonical output contract without a duplicate paid repair
  call; unbound plans remain fail-closed (ADR-071).
- Phase5 final Provider P5C04 follow-up: live Provider literal predicates are
  now fail-closed against structured filters/time range before execution, and
  the prompt forbids inferred business filters; terminal query-contract
  failures cannot trigger a duplicate paid fallback call (ADR-072).
- Phase5 final Provider annual-output follow-up: the prompt now requires one
  aggregate row per year, exact declared projection, and no raw fact rows;
  server-bound `DATE_TRUNC('year', ...)` is reconciled only through matching
  semantic and SQL AST identity, correlation scopes normalize to canonical
  years, DB-GPT is preloaded at startup, and Oracle/runtime terminal failures
  cannot trigger duplicate paid calls (ADR-073).
- Phase5 final Provider P5C03 follow-up: Result Oracle now reconciles an
  unqualified Provider Join entity with a schema-qualified selected table only
  when its leaf name is unique; duplicate leaf names across schemas remain
  ambiguous and fail closed (ADR-074).
- Remote Phase3/IBM CI follow-up: the broad Backend unit step now isolates the
  workflow-wide Level0 fallback so its explicit fake gateways remain active;
  real deterministic runners and every downstream remote Gate remain Level0
  with paid Provider calls disabled (ADR-075).

## 2026-08-28：V1.3.1 功能体验、模型管理与全控件收口

- 独立分支已完成聊天意图、答案语义展示、模型服务、系统设置、工作区安全、用户/角色/邀请/审计及控件闭环；Frontend 只经 Backend API 访问持久化元数据。
- 自动验证已通过 Backend `681 passed, 7 skipped`（另以 exact repository object database 补跑 Git introspection `2/2`）、Frontend `60/60`、专项 `25/25`、TypeScript 和 991-module Vite build。
- MiMo、DeepSeek、Kimi 已各完成一次生产 `ModelGateway` 实调，3 次 transport attempt、无 retry/fallback、合计估算成本 CNY `0.0005425`，持久化调用账本未包含密钥或认证头。
- 当前状态为 `PARTIAL_BLOCKED_C_DATABASE_PROVISIONING`：应用角色无建库权限，独立数据库不存在；为保护 Track A，未对共享数据库启动 Compose。因此 2 次启停、浏览器全控件、RBAC 与持久化验收均未执行，远端未推送。
- 详细证据与恢复条件见 `docs/status/V1_3_1_FUNCTIONAL_EXPERIENCE_CLOSURE_STATUS.md`（ADR-076）。

## 2026-08-28：V1.3.1 C 线数据库解阻与最终候选前收口

- 已以独立本机 PostgreSQL 数据库 `chatbi_v131_functional` 解阻；owner 为 `chatbi_app`，应用角色继续保持 `CREATEDB=false`、`SUPERUSER=false`，未新增 Docker 数据库服务或卷。
- Cycle 1 已完成真实 Chat、设置持久化、Admin/Analyst RBAC、角色切换、停用/启用、邀请创建/复制/重启读回/撤销、审计、成员移除、最后管理员保护和完整停止；Track A 全程保持 healthy。
- Cycle 2 已从空 schema 正式迁移到唯一 head `20260828_0013`，并由正式 seed 重建 9 张业务表、1,095 条订单和 1,825 条日 KPI。
- 浏览器发现并最小修复：全外部 Provider 关闭时 DATA_QUERY 走 Local Semantic Runtime；Provider 开关不再隐式产生付费探测；排名图表业务化标题、金额单位与长名称展示；Analyst 管理入口/直达 URL 前端 fail-closed。
- 第二轮最终浏览器又发现并修复：首次显式连接测试不得把已配置 Provider 的默认启用态反转为禁用；三家健康探针统一限制为 8 个输出 Token，Kimi 不再因普通 2,048 Token 请求预算而在实际连接前被误拒绝。
- 最终 forward commit 之后才执行同 SHA 全回归、三 Provider 各一次显式连接测试、最终 UI 控件清单与 SHA-256 manifest；这些自引用证据只写入仓库外 `E:/ChatBI_V2_Evidence/PostRelease/Functional_Experience_Closure/`。
- C 线浏览器全控件验收发现 SQL Workspace 保存的 `VERIFIED` 答案可能不具备语义模型、查询运行或图表绑定；答案库现按 Backend 的真实前置条件分别门禁“复用”和“加入看板”，列表与详情均显示禁用原因，避免可点击后返回 422 的假可用控件（ADR-078）。
