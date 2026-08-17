# ChatBI V2 V1 RC 候选：15 分钟演示

## 演示前检查（2 分钟）

1. 运行 `.\scripts\status.ps1` 与 `.\scripts\verify.ps1`。
2. 打开 <http://localhost:5173>，确认浏览器缩放 100%。
3. 准备问题：`2026年按地区按月统计已支付订单收入趋势`。

## 产品闭环（13 分钟）

1. **登录**：使用演示账号进入，默认落在“问数据”。
2. **数据源**：进入“数据源”，展示本机 PostgreSQL 主数据源与 MySQL 兼容数据源；测试连接并打开 PostgreSQL Schema。
3. **Schema**：展示真实表、字段、关系和样例值，强调前端不直连数据库。
4. **Semantic Model**：打开已发布模型，展示 Entity、Metric、Dimension、Relationship、Business Term/Synonym。
5. **Ask**：提交准备好的自然语言问题，观察 Context → SQLPlan → Guard → 只读执行 → Oracle。
6. **KPI / Chart / Insight**：按固定顺序讲解一句话结论、KPI、真实 ECharts、证据绑定洞察和明细。
7. **查询依据**：展开 Metric、Dimension、Time、Filter、Join、SQL、模型版本、数据源、耗时、Oracle 与 Result Signature。
8. **推荐追问**：点击一个追问，证明它重新进入真实 Ask Pipeline。
9. **Answer**：标记“结果有帮助”并保存为 VERIFIED Answer；在答案库查看完整证据与版本，然后复用。
10. **Dashboard**：把 VERIFIED Answer 保存为卡片，查看来源问题、真实图表与签名，执行刷新后得到新 QueryRun。
11. **Evaluation**：在评测中心点击“运行 Golden 20”，查看真实运行、20 个 Case、Expected/Actual/SQL/ResultDiff。
12. **安全收尾**：提交一条 `DELETE` 示例，展示 SQL Guard 在数据库访问前拒绝。

演示中不得声称外部在线模型已配置；当前环境的 `LIVE_MODEL_SMOKE=NOT_CONFIGURED`，完整链路由本地 Runtime 与 Adapter 完成。
