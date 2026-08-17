# ChatBI V2 Day 2 Status

```text
BASE_HEAD=c6394d039a9c201f69f4488cb19167511a0c6f8d
DELIVERY_BRANCH=codex/day2-nl2sql-result-oracle
DAY_2_GATE=PASS
```

## 主链路

真实链路已打通：`自然语言 → Schema Linking → QueryContext → Nl2SqlRouter → SQLPlan → SQLGlot AST Guard → 只读 Query Executor → Result Oracle → 结果页 → 反馈/答案保存`。

- `QueryContext` 含 Workspace、数据源/方言、语义模型版本、实体、候选表列、指标、维度、关系、术语/同义词、Verified SQL、时间、行数/超时/allowlist 和确定性 token budget。
- 本地 Runtime 依据语义对象与通用分析意图组合 SQL，不读取 Golden SQL，不维护完整问题字典。
- OpenAI-compatible Provider 通过环境变量可替换；本轮未配置外部模型，`LIVE_MODEL_SMOKE=NOT_CONFIGURED`。
- PostgreSQL 是默认真实问数路径；MySQL 使用同构兼容语义模型。

## 安全与执行

- SQLGlot AST Guard：单语句、SELECT/CTE、Schema/Table/Column allowlist、危险函数、系统 Schema、通配符和行数上限。
- 38/38 危险 SQL 在 Query Executor 前被拒绝，阻断率 100%。
- PostgreSQL/MySQL `chatbi_reader` 各执行 1 次真实 UPDATE 尝试，成功数 0；两库订单行数前后均为 1,095。
- Query Executor 提供 PostgreSQL/MySQL、只读事务、8 秒默认超时、500 行默认上限、4 并发基础限制、结果截断、耗时、错误分类和审计。

## Result Oracle 与 Golden Set

- Oracle 不比较 SQL 文本，检查执行、AST 授权、指标、维度、时间、过滤、Join、列集合、行形状/空值、值容差和顺序无关 SHA-256 签名。
- Golden 20 分布：简单指标 4、时间 4、过滤/分组/TopN 4、Join 5、复合问题 3。
- Manifest SHA-256：`d40bb690a4208240ecf347abe47e045cd74c8eb89b9162d5d53890ecf24bc282`。
- PostgreSQL：执行 20/20、结果 20/20、语义匹配 20/20。
- MySQL 基础兼容：执行 5/5、结果 5/5。

## UI 与 API

- 原固定演示结果已替换为 `/api/v1/ask` 真实查询。
- 页面展示问题、结论、KPI、动态图表、真实明细、折叠 SQL、语义模型版本、指标、维度、时间/过滤、耗时、Oracle、反馈、答案保存和推荐追问。
- Loading、Empty、Error、SecurityRejected、OracleMismatch 均为独立真实状态。
- 1440×900 截图位于 `docs/evidence/day2/ask-result-1440x900.png`；1366×768、1440×900、1920×1080 无页面级横向裁切。
- OpenAPI：32 paths / 45 operations。

## 验收

- Backend Pytest：66/66 PASS；`pip check` PASS。
- SQL Guard 单元危险样例：38/38 PASS；Backend 另有 3 条安全 SELECT、两方言 Router、Oracle、API 反馈/保存测试。
- Frontend：10 files / 26 tests PASS；TypeScript PASS；Vite build PASS（728 modules）。
- Playwright：12/12 PASS，其中 Day 2 指定六场景 6/6，console/page/blocking request error 0。
- Alembic：单一 head `20260817_0004`；本机 PostgreSQL 隔离临时 Schema upgrade → base → upgrade PASS，临时 Schema 已删除。
- 种子连续执行两次计数一致；Day 1 本机业务数据 bootstrap 未修改，仍由既有幂等脚本管理。
- Docker Compose 从停止状态连续启动 2/2 PASS；数据库服务 0、数据库卷 0。

## Known Gaps / Day 3 Input

- 外部在线模型未配置，因此没有 Live Model Smoke；不影响本地真实运行时 Gate。
- Wren runtime 仍未配置，Adapter 如实报告不可用；Day 2 主链路不依赖 Wren。
- 本地 Provider 当前覆盖演示经营语义模型的常用指标、维度、过滤、时间、TopN 和 Join；更复杂派生指标依赖、任意日期表达和二次修复策略进入后续加固。
- 高级图表规划、业务 Narrative 与看板卡片生成属于 Day 3；当前不伪装高级洞察。
- Vite 生产包存在单 chunk 超过 500 kB 的构建警告，不影响当前功能 Gate，进入后续性能优化。

所有详细机器证据位于 `docs/evidence/day2/`。
