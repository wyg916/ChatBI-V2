# 面试讲解稿

## 30 秒版本

> ChatBI V2 是我独立设计并开源的企业级自然语言问数产品。它把 PostgreSQL/MySQL 数据源、轻量语义层、NL2SQL、SQLGlot 只读安全、结果值 Oracle、图表洞察、答案看板和 Golden 评测串成完整闭环。V1.3 还加入受控 RAG、有限 Multi-Agent、文件/多模态和统一模型成本治理，但始终坚持 Agent 不能绕过确定性的 SQL 与结果验证边界。

## 2 分钟版本

### 背景

企业 Text-to-SQL 的最大风险不是 SQL 生成失败，而是 SQL 能运行但口径或结果错了。只看执行成功率会漏掉错误指标、错误时间、错误过滤、错误 Join，以及模型根据错误结果生成的漂亮结论。

### 我的方案

我把运行链拆成五个明确责任：

1. Semantic/Context 约束业务口径和允许的数据范围。
2. NL2SQL 只生成结构化候选计划。
3. SQL Guard 做单语句、只读、Schema/Table/Column、危险函数和成本校验。
4. Query Executor 负责只读账号、事务超时、并发、行限、脱敏和审计。
5. Result Oracle 独立检查指标、维度、时间、过滤、Join 和结果值，再允许 Chart/Insight/Answer 使用。

产品上，用户可以把 VERIFIED 结果保存为答案、加入看板，再通过 Golden Set 对后续模型和语义变更做回归。

### V1.3

三家模型通过统一 Gateway 管理能力、预算、重试、熔断和成本。知识问答必须通过 Workspace ACL 与 Citation Guard；复杂分析只使用固定五角色六工具和硬预算，数据工具仍回到原来的 QueryPipeline。文件和图片也不能直接把模型输出当事实，必须保留定位证据或与数据库结果交叉验证。

## 架构图怎么讲

```text
React Chat UI
  ↓ /api/v1 + authenticated session + SSE
FastAPI Application
  ├─ Question Router / Context Builder / Semantic Adapter
  ├─ Model Gateway / NL2SQL
  ├─ SQLGlot Guard → Query Executor → Result Oracle
  ├─ Controlled RAG / Bounded Orchestrator
  └─ Answer / Dashboard / Evaluation / Audit
  ↓
Local PostgreSQL metadata + read-only PostgreSQL/MySQL business data
```

重点不是组件数量，而是所有数据结论最终只能通过同一个 SQL Gateway 和 Result Oracle；RAG/Agent/文件/图片不拥有旁路数据库权限。

## 关键技术取舍

### 为什么不用“模型自评”代替 Result Oracle？

模型自评仍是概率输出，容易被表达方式影响。Oracle 使用结构化意图、真实执行结果、独立验证查询、容差和结果签名，错误可以定位到指标/维度/时间/过滤/Join/值，而不是只给一个置信分。

### 为什么 PostgreSQL 和 MySQL 都需要？

PostgreSQL 是主开发和主验证路径，保证元数据、迁移和完整闭环稳定；MySQL 用来验证第二方言、连接器与 Schema 同步边界。两者不是两套产品，业务代码依赖统一 DataSource Adapter。

### 为什么数据库不放 Docker？

这个项目的本地基线要求业务与元数据保存在用户已安装的本机数据库，Docker 只承载无状态应用服务。这样数据库生命周期不会被 `docker compose down -v` 误删，也能真实验证外部数据源连接。

### 为什么 Agent 是固定的？

ChatBI 的目标是可信分析，不是通用 Agent 平台。固定角色、固定工具和硬预算让权限、失败模式、成本和 Trace 可验证；普通 DATA_QUERY 直接走确定性 QueryPipeline，避免为了 Agent 而 Agent。

### 为什么录屏时可以切到 deterministic？

根目录一键启动默认是 `Auto`，有凭据时会真实使用 MiMo、DeepSeek、Kimi。求职录屏如果更看重稳定、可复现和无付费风险，可以显式选择 `ProviderMode Deterministic`；它仍执行真实数据库、SQL Guard、Executor 和 Oracle，只替换外部 Provider 的不稳定网络边界。

### 如何处理上游开源复用？

所有第三方能力都放在 ChatBI 自有 Adapter 后；锁定提交、路径和校验和，做许可证审计并更新第三方声明/SBOM。不能满足许可证或供应链约束的能力只做设计参考或 clean-room，不为了“复用数量”强行接入。

## 常见追问

### “怎么证明结果正确？”

回答顺序：Golden Question → 结构化 Expected → 真实 SQL 执行 → Result Oracle 八类检查 → Result Signature → Expected/Actual/Result Diff → 回归记录。强调 HTTP 200 和 SQL 执行成功都不是正确性证据。

### “怎么防止越权？”

Session 绑定用户和 Workspace；资源查询带 Workspace/RBAC；数据源使用只读最小权限；SQL AST 再做 Schema/Table/Column allowlist；RAG 以签名身份和 ACL 过滤文档版本；缓存 Key 包含权限和版本；所有拒绝写审计。

### “如何控制模型成本？”

统一 Gateway 做能力/复杂度路由，记录 Token、估算成本、重试和 fallback。CI 与免费回归仍显式使用 LEVEL0；当前本机交互 Showcase 经负责人授权后使用 `Auto`，关闭测试付费门禁，但 Provider 账号自身的额度与计费仍然有效。

### “最难的工程问题是什么？”

推荐讲三类：

1. 把 SQL 可执行与业务正确拆开，建立结果值 Oracle 和验证查询。
2. 把 Streaming、取消、事务提交和会话持久化做成同一状态机，避免 UI 显示取消但后端已提交成功答案。
3. 把 RAG/Agent/文件/视觉纳入同一权限、成本、Trace 和事实边界，而不是形成多个绕过主链路的子平台。

### “下一步会做什么？”

当前不启动 V1.4/V2.0。维护重点是 Showcase 稳定性、问题修复和文档；生产部署需要独立完成 Secret、不可变镜像/依赖、生产环境观测、备份恢复和正式部署 Gate，不能用源码 Release 或本地 Demo 代替。

## 结尾

> 我希望面试官看到的不只是一个页面，而是一套可解释的工程判断：模型可以不确定，但权限、SQL 安全、数据访问、结果校验、成本和发布事实必须确定。
