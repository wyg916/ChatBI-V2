# ChatBI V2 V1.0.0：15 分钟演示脚本

## 演示前检查（2 分钟）

1. 双击 `一键启动-ChatBI-V2.cmd`，或运行 `./scripts/launch.ps1 -NoOpen`。
2. 运行 `./scripts/verify.ps1`，确认 Backend、Frontend、PostgreSQL 主数据源和 MySQL 兼容数据源均可用。
3. 打开 <http://localhost:5173>，浏览器缩放保持 100%。

## 产品闭环（11 分钟）

1. **登录与问数据**：登录后默认进入“问数据”，不从管理后台开始。
2. **数据源**：展示本机 PostgreSQL 主数据源与 MySQL 兼容数据源；测试连接并打开 Schema。
3. **语义模型**：展示 Entity、Metric、Dimension、Relationship、Business Term 与 Synonym，以及已发布版本。
4. **Ask 主问题**：提交 `2026年按地区按月统计已支付订单收入趋势`，观察 Context → SQLPlan → SQL Guard → 只读执行 → Result Oracle。
5. **结果结构**：按“一句话结论 → KPI → 主图表 → 业务洞察 → 明细表 → 推荐追问”讲解回答。
6. **查询依据**：展开 Metric、Dimension、Time、Filter、Join、SQL、模型版本、数据源、耗时、Oracle 与 Result Signature。
7. **答案与看板**：保存 VERIFIED Answer，将其加入看板，刷新卡片并确认生成新的 QueryRun。
8. **Golden 50**：在评测中心运行 Golden 50，查看 Case 的 Expected/Actual、SQL 和 ResultDiff；补充说明 MySQL 兼容集为 10/10。
9. **安全门禁**：提交一条 `DELETE` 示例，展示 SQL Guard 在数据库访问前拒绝。

## 推荐问题（按剩余时间选用）

- `统计全部订单收入、成本和利润`
- `2026年按地区按月统计已支付订单收入趋势`
- `按地区统计收入贡献度`
- `按品类统计利润率`
- `2026年第一季度按地区统计收入和成本`

## 外部模型、Live RAG 与有限编排（2 分钟）

- Kimi、MiMo、DeepSeek 通过后端 OpenAI-compatible Adapter 接入；密钥仅保存在本机 `.env`，不进入前端、Git 或证据文件。
- 发布默认 Provider 仍为 deterministic，保证演示可复现；三家在线 Provider 已通过 Discovery、鉴权、Chat、SQLPlan 与 SQL Guard Live Smoke。
- RAG 与最小 Multi-Agent 在 V1 默认 `on`。演示 `KNOWLEDGE_QUERY` 的真实引用、`HYBRID_ANALYSIS` 的验证融合、`COMPLEX_ANALYSIS` 的五角色/六工具 Trace 与 SSE 阶段；普通 `DATA_QUERY` 始终只走 QueryPipeline。

演示时只陈述当前页面和验收证据可以证明的结果，不展示密钥、内部思维过程或本机绝对路径。
