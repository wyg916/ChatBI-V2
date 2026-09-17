# V1.3.0 三模型统一控制平面

## 范围与状态

本能力属于 ChatBI 主链路 P0 运行时质量建设。它只统一模型调用、路由、成本、预算、回退、熔断与 Trace，不扩展为通用模型平台或动态 Agent/Tool 市场。

Phase 0.6 已采用开发阶段密钥授权门禁：当前 MiMo、DeepSeek、Kimi 密钥允许用于 V1.3.0 开发测试；正式生产发布前仍必须完成三组密钥轮换。轮换延期不阻塞 Phase 1～5、RC 功能实现或内部验收，只阻塞正式生产发布与公开切流。

## 单一调用边界

运行时链路固定为：

`RequestContext → L0/Intent/Complexity Router → ModelRequest → RoutingPolicy/Cost Budget → ModelGateway → Provider Adapter → ModelResponse → Trace`

- `backend/app/model_gateway/service.py` 是 Backend 唯一允许创建 Provider Chat Completions HTTP 请求的位置。
- `backend/app/integration/model_gateway.py` 仅保留兼容导入，不含网络调用。
- `backend/app/query/nl2sql.py` 的 Provider Adapter 只构造强类型 NL2SQL 请求并委托 ModelGateway；模型输出仍必须经过 SQLPlan 校验、SQL Guard、只读执行与 Result Oracle。
- Provider SDK、源码、Logo、模型权重均未复制或导入；实现是 ChatBI 自有 Adapter 与控制逻辑。

## 服务端权威契约

契约位于 `backend/app/model_gateway/contracts.py`：

- `RequestContext`：统一 request/trace/conversation/user/workspace/datasource、角色、权限哈希、时区、语言、附件、上下文哈希和预算模式。
- `RouterDecision`：记录路由、置信度、原因、复杂度、是否需要模型/SQL/RAG/Vision/澄清，以及请求 Alias。
- `ModelRequest`：记录能力、模态、复杂度、预算、思考模式、结构化输出、工具和超时。
- `ModelResponse`：只记录请求 Alias、真实 Provider/Model、Token、人民币成本、延迟、TTFT、重试、回退、完成原因和是否观察到思考字段。

模型的 `reasoning_content` 只用于协议兼容性检测，不进入业务回答、Trace、日志或数据库。

## Alias、能力与成本配置

控制配置采用 JSON 子集的 YAML 1.2，运行时用标准库解析，不新增依赖：

- `backend/config/model_capabilities.yaml`
- `backend/config/model_pricing.yaml`
- `backend/config/model_policy.yaml`
- `backend/config/provider_health.yaml`

Alias 只解析 Provider；最终 Model ID 必须来自 Backend 环境配置。当前默认路由为：

| 请求 | 默认顺序 | 说明 |
| --- | --- | --- |
| General / Intent | MiMo → DeepSeek | Balanced 文本路由不自动使用 Kimi |
| NL2SQL / Structured | DeepSeek → MiMo | 生成结果仍是非可信输入 |
| Vision | MiMo → Kimi | Kimi 只作受预算约束的视觉回退 |
| Quality 且复杂度 ≥80/命中 Premium Trigger | Kimi → 其他 | 每请求最多一次 Kimi 候选 |

成本按 Provider 返回的真实 usage 归一化；无 usage 时不伪造 Token 或成本。价格配置记录来源、币种、生效日期和每百万 Token 单价。价格会变化，正式发布前必须复核官方价格并更新生效日期。

## 可靠性与安全

- 仅网络异常、408/425/429 和 5xx 进入有界重试；`Retry-After` 最大等待 2 秒。
- 默认每 Provider 最多 2 次尝试、最多 2 次 Provider 升级、连续 3 次失败打开 30 秒熔断。
- Provider 全部失败时返回真实 `MODEL_UNAVAILABLE`/`VISION_MODEL_UNAVAILABLE`，禁止生成伪回答。
- 取消事件在网络调用前和流式增量间检查；Provider 已输出内容后发生错误不会跨 Provider 拼接答案。
- Header、Key、Provider 错误正文和容器环境变量不进入 Trace 或 Evidence。
- Provider Key 只能来自现有 Backend env/secret configuration。

## L0、Trace、SSE 与缓存

- “今天是几号/星期几”由服务端时区确定性回答，`requested_alias=none`、`model_provider=none`，不调用模型。
- 创作/翻译语境中的“收入”等词不会误路由为 DATA_QUERY。
- Chat、Analysis、Query、SSE 共用同一 `trace_id`；`request_id` 使用客户端幂等消息 ID。
- SSE 每个事件同时带 `run_id`（兼容字段）、`trace_id`、`request_id`、`conversation_id` 和稳定 `message_id`。
- 缓存身份包含 Workspace、用户/Conversation、权限哈希、Datasource 和 Context Hash；语义链接缓存额外纳入权限哈希，避免同角色但授权不同的用户共享旧答案上下文。

## Phase 1 Gate

Phase 1 只有在以下事实均由同一提交测试证据支持时才允许 PASS：

- `MODEL_GATEWAY=PASS`
- `COST_ROUTER=PASS`
- `DATE_ZERO_MODEL_ROUTE=PASS`
- `UNRELATED_REVENUE_FALLBACK=0`
- `CROSS_CONVERSATION_RESPONSE=0`
- Backend 全量、Frontend、E2E、Golden、Secret Scan 和 Git clean/remote sync 均满足项目门禁。

当前文档描述实现契约，不代替最终 Phase 1 测试证据或发布批准。
