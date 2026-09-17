# ChatBI V2 V1 RC1 Release Notes

> 状态：已发布 RC。Day 3 与 V1 RC Gate 为 PASS，annotated Tag 为 `chatbi-v2-v1-rc1`。

## 发布能力

- 真实查询结果驱动的受控 ChartSpec 与 ECharts Renderer。
- 证据绑定 Narrative、Insight 与 3～5 条可点击推荐追问。
- 完整 VERIFIED Answer、AnswerVersion、复用与状态管理。
- Answer 到 Dashboard Card 的保存、来源查看、刷新与删除闭环。
- 可从前端触发的真实 Golden20、持久化 Evaluation Run/Case Result 与 Expected/Actual/SQL/ResultDiff。
- PostgreSQL 主路径、MySQL 兼容路径、SQLGlot AST Guard 与数据库最小权限双层保护。

## 发布验证结果

Backend 85/85、Frontend 26/26、Playwright 34/34、Golden 20/20、MySQL 5/5、危险 SQL 38/38、迁移与 Secret Scan PASS。

## 后续质量加固

Day 4 将在不改变 V1 RC 产品主链路的前提下扩展 Golden 50、把结果准确率门槛提升至至少 95%，并加强语义模型版本/回滚、权限审计、测试隔离与 UI 边角质量。
