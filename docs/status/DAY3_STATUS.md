# ChatBI V2 Day 3 Status

```text
BASE_HEAD=15ae6cdc9e96cc391e5bbeafb35408172c80f835
DELIVERY_BRANCH=flex/day3-chart-insight-v1-rc
DAY_3_STATUS=PASS
DAY_3_GATE=PASS
V1_RC_STATUS=PASS
RC_TAG=chatbi-v2-v1-rc1
RC_TAG_TYPE=annotated
```

## 已完成的产品闭环

`Ask → Result Oracle → ChartSpec/ECharts → Narrative/Insight → Follow-up → Verified Answer → Dashboard Card → Evaluation Run/Case Detail` 已接入真实 Backend API 与本机只读数据库。

- Chart Engine 支持 KPI、Line、Bar、Grouped Bar、Stacked Bar、Donut、Table；Chart Rule 测试 19/19，Query/Signature 绑定通过。
- Narrative 只在 Oracle PASS 后生成，保存字段/行证据、Query ID、结果签名和语义模型版本；推荐追问 3～5 条并可点击重问。
- Answer 保存完整语义、SQLPlan、SQL、结果快照/签名、ChartSpec、Narrative、反馈和版本；只有 HELPFUL + Oracle PASS 可进入 VERIFIED。
- Dashboard Card 绑定 Answer/QueryRun/ChartSpec/Signature，支持来源查看、真实刷新和删除。
- Evaluation 真正执行冻结 Golden20 并持久化 Expected、Actual、SQL、ResultDiff 与错误分类。

## 已通过门禁

- Backend Pytest：85/85；pip check PASS。
- Chart/Insight：19 个规则与边界测试 PASS。
- Frontend：10 files / 26 tests；TypeScript、Vite production build PASS（728 modules）。
- Playwright：34/34；Day 3 专用 19/19，指定 E2E-01～15 全覆盖。
- UI14：14/14 路由 x 3 视口；页面横向裁切、console/page error、blocking failure、unexpected 4xx/5xx 均为 0（响应状态专项复验见测试摘要）。
- Golden：PostgreSQL SQL/结果/语义 20/20；MySQL SQL/结果 5/5；SHA-256 未变化。
- 安全：38/38 危险 SQL 阻断；PostgreSQL/MySQL 只读账号真实写入成功数 0。
- Migration：单 head `20260817_0005`；本机 PostgreSQL 隔离 Schema `upgrade → base → upgrade` PASS。
- Seed 幂等、Secret Scan、生产依赖审计均 PASS。
- 外部模型未配置，`LIVE_MODEL_SMOKE=NOT_CONFIGURED`；本地 Runtime 可用。

## 已完成的发布门禁

- `STOP → START RUN1`：PASS，构建完成，Backend/Frontend HTTP 200、容器 healthy，本机 PostgreSQL/MySQL READY。
- `FULL STOP → START RUN2`：PASS，同一健康与数据源门禁再次通过。
- 最终回归：Backend 85/85、Frontend 26/26、Playwright 34/34、Golden 与安全/迁移/Secret Scan 全部 PASS。
- Git：Day 3 提交合入 main，main 推送并以远端 SHA 与 ahead/behind `0 0` 验收；annotated `chatbi-v2-v1-rc1` 已推送并核验目标。

Playwright 发布门禁因共享本机元数据库和会修改 Schema Catalog 的用例，使用单 worker 执行。一次并行探测暴露 Schema Sync 与查询的测试隔离竞态，已如实记录到验收报告并列入 Day 4 非阻塞加固。

## 范围

`P2_SCOPE_ADDED=0`。未引入 RAG、通用 Agent、长期记忆、预测、告警平台、复杂 Dashboard Builder、插件市场或微服务重写。
