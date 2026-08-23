# V1.3.0 Phase 5 测试成本控制与最终 Provider 认证策略

## 1. 决策

Phase 5 的产品、安全、准确率、性能、浏览器、逐控件、冷启动和远端 CI 阈值全部保持不变。成本控制只消除修复期间重复的外部模型调用，不把定向 Smoke、缓存响应或确定性结果冒充最终真实 Provider 认证。

所有普通 push workflow 固定为 `LEVEL0`，设置：

```text
CHATBI_TEST_COST_CONTROL=YES
CHATBI_TEST_EXECUTION_LEVEL=LEVEL0
CHATBI_PAID_GATE_AUTHORIZED=NO
CHATBI_MODEL_PROVIDER=deterministic
```

Model Gateway 是唯一 Provider HTTP 边界。启用测试成本控制时，Level 0 的真实 MiMo、DeepSeek、Kimi transport 会在发出 HTTP 请求前失败关闭；显式 `MockTransport`、录制响应和确定性 Provider 不计为付费调用并可正常运行。生产运行未设置 `CHATBI_TEST_COST_CONTROL` 时行为不变。

## 2. 三级执行

### Level 0：免费高频层

默认用于每一次代码修改。包含 Backend/Frontend/TypeScript/Build、Data100 确定性链、SQL Guard、Result Oracle、Weird50、安全、迁移、数据库持久化、逐控件矩阵、浏览器、10M、冷启动诊断、故障注入和 20×15 分钟应用负载。

- Provider 模式：确定性或录制响应。
- 真实 Backend/API/PostgreSQL/MySQL/SSE/RAG/Agent/File 编排继续执行。
- 付费 Provider 调用：0。
- 20×15 分钟负载与最终小规模真实 Provider Load Smoke 是两个独立 Gate，互不替代。

生成 Level 0 计划：

```powershell
python scripts/phase5-test-cost-control.py plan `
  --level LEVEL0 `
  --sha <40位候选提交SHA> `
  --estimated-cost-cny 0 `
  --output E:\ChatBI_V2_Evidence\V1.3.0\Phase5_Cost_Control\level0-plan.json
```

只有全部必选 Level 0 Gate 均为 `PASS` 时，才能用 `certify-level0` 生成与完整 Git SHA 绑定的 receipt。缺失或失败的 Gate 会使命令退出非零，不能进入 Level 2。

### Level 1：定向真实 Provider Smoke

仅当修改真实涉及 Model Gateway、Provider Adapter、Prompt、Routing、Vision 或 Agent 模型调用时使用。必须同时提供：

- `CHATBI_PAID_GATE_AUTHORIZED=YES`；
- 完整 `CHATBI_TEST_SHA`；
- `TEST_RUN_ID`、单个 `CASE_ID`、Gate、受影响路径；
- 明确 Provider allowlist；
- 外部 SQLite 成本台账路径；
- 不超过预算分类的硬上限。

Level 1 最多 30 次真实请求，每次 runner 只允许选择 1～3 个受影响 Case。Kimi 只允许 Vision、scanned PDF、Complex 或明确 Premium 范围。三 Provider Smoke 必须显式传 `--provider`，不能默认并行跑三家；Multimodal 必须显式传 `--case-id`；Weird/Complex runner 必须显式传 `--weird-case` 或 `--complex-case`。

示例：只复验 scanned PDF：

```powershell
$env:CHATBI_TEST_COST_CONTROL='YES'
$env:CHATBI_TEST_EXECUTION_LEVEL='LEVEL1'
$env:CHATBI_PAID_GATE_AUTHORIZED='YES'
$env:CHATBI_TEST_SHA='<FULL_SHA>'
$env:CHATBI_TEST_RUN_ID='phase5-scanned-pdf-001'
$env:CHATBI_TEST_CASE_ID='M10'
$env:CHATBI_TEST_GATE='multimodal10'
$env:CHATBI_TEST_AFFECTED_PATH='scanned_pdf'
$env:CHATBI_TEST_ALLOWED_PROVIDERS='kimi'
$env:CHATBI_TEST_BUDGET_CLASS='targeted_live_regression'
$env:CHATBI_TEST_BUDGET_CNY='1.00'
$env:CHATBI_TEST_COST_LEDGER_PATH='E:\ChatBI_V2_Evidence\V1.3.0\Phase5_Cost_Control\paid-tests.sqlite3'
python backend/scripts/run_v13_multimodal_live.py --case-id M10 --output '<TARGETED_EVIDENCE_PATH>'
```

不要把示例中的 SHA、Run ID 或 Evidence 路径固化进仓库。Provider Key 仍只来自 Backend 环境变量，不能进入命令、日志或 Evidence。

### Level 2：最终付费认证

只允许最终候选 SHA 执行一次。除 Level 1 元数据外，还必须满足：

- `CHATBI_FINAL_CERTIFICATION=YES`；
- `CHATBI_TEST_FINAL_SHA` 与 `CHATBI_TEST_SHA` 完全一致；
- `CHATBI_PAID_TEST_CACHE_BYPASS=YES`；
- `CHATBI_LEVEL0_RECEIPT` 可读、SHA 一致、全部必选 Gate 为 PASS；
- `final_certification` 预算不超过 3.00 CNY，日总预算不超过 5.00 CNY。

Level 2 runner 拒绝 Case 过滤，确保最终 Multimodal10、Weird50/Complex5 和三 Provider 认证保持完整。Level 1 的定向 PASS 不会被提升为 Level 2 PASS。

## 3. Token、重试与预算

- 普通测试输出上限 512 tokens；Complex/Agent 上限 1024 tokens。
- 测试环境最多重试 1 次，即最多 2 次总尝试。
- 402、401、403 等不可恢复错误不重试；429、可恢复 Transport/5xx 最多一次受控 backoff。
- 默认预算：普通修复 0.50 CNY、定向真实回归 1.00 CNY、预最终 1.50 CNY、最终认证 3.00 CNY、单日硬上限 5.00 CNY。
- 预计成本、Run 累计保守成本或日累计成本越界时，在网络调用前返回 `TEST_BUDGET_EXCEEDED`。

## 4. 成本台账

每一次获准的真实 Provider 尝试先在外部 SQLite 台账中预留预算，完成后只记录以下脱敏字段：

```text
TEST_RUN_ID, SHA, CASE_ID, GATE, PROVIDER, MODEL,
INPUT_TOKENS, CACHED_INPUT_TOKENS, OUTPUT_TOKENS,
COST_CNY, RETRY_COUNT, STATUS, ERROR_CODE
```

不保存 Prompt、模型正文、图片、Key、Authorization Header 或数据库凭据。`summary` 子命令按 Provider 和 Gate 聚合真实费用。失败尝试仍保留预算预留，避免以 402/超时产生的未知计费绕过硬上限。

## 5. Provider Response Cache

非最终开发允许使用包含 Provider、Model、Prompt Version、Request/Input Hash、Capability、Temperature 和 Model Version 的录制响应缓存。最终 Level 2 必须 `PAID_TEST_CACHE_BYPASS=YES`，缓存结果不得作为真实 Provider Evidence。

## 6. GitHub Actions

当前 Phase 4、Phase 5 和 IBM/Phase 3 的普通 push 均显式运行 Level 0，外部 Provider 调用在唯一网关处失败关闭。当前 Phase 5 仍为 FAIL，因此仓库不提供会自动消耗 Provider 费用的 push job。

未来新增真实 Provider workflow 时必须仅使用 `workflow_dispatch` 或明确的 final-certification 条件，并在注入 Provider Secret 前完成 Level 0 receipt、最终 SHA、`PAID_GATE_AUTHORIZED=YES`、预算和 cache bypass 校验。未满足任一条件时 job 必须停止，不能降级为自动付费调用。

## 7. 当前修复顺序

1. 零付费：Data100、674 控件矩阵、持久化、Conversation Delete、Browser、Cold Start、Load Infrastructure。
2. 基本零付费：Weird50、Complex deterministic、安全、Phase 1～4 deterministic regression。
3. 定向真实模型：单个 Complex 失败 Case、M10 scanned PDF、受影响 Provider Smoke。
4. 最终候选：完整确定性回归 PASS 后，只执行一次完整真实 Provider 认证。

该顺序不改变 `CORE_DATA_GOLDEN`、`RESULT_VALUE_ACCURACY`、Complex5、Multimodal10、安全、浏览器、Control Matrix、Load、Cold Start 或 Remote CI 的最终标准。
