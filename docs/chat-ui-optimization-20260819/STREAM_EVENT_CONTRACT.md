# ChatBI V2 统一流式事件契约

版本：`chatbi.stream.v1`
传输：`POST /api/v1/chat/stream`，`text/event-stream`

## 1. Envelope

每个事件至少包含：

```json
{
  "seq": 1,
  "run_id": "STREAM-...",
  "conversation_id": "...",
  "message_id": "pending-<client_message_id>",
  "timestamp": "2026-08-19T10:00:00Z",
  "event_type": "run.started"
}
```

规则：

- `seq` 从 1 开始且在单个 `run_id` 内严格递增。
- `run_id`、`conversation_id`、`message_id` 在一次运行中保持稳定；`run.completed.response` 提供最终持久化消息 ID。
- SSE 的 `event:` 必须等于 JSON 的 `event_type`。
- 事件可以保留 `trace_id/sequence/event` 兼容别名，但新 Frontend 不得依赖别名。
- 除心跳外，不发送 Provider 私有事件；任何 Provider 事件先由 Adapter 转换。

## 2. 规范事件

### `run.started`

首个事件。在数据库/模型完整结果可用前发出，可包含公开路由和能力信息。

### `phase.started` / `phase.completed`

必须包含：

```json
{
  "phase": "querying_data",
  "label": "正在查询数据……",
  "duration_ms": 120,
  "metadata": {}
}
```

允许的公开阶段：

| `phase` | UI 文案 |
| --- | --- |
| `understanding` | 正在理解问题…… |
| `semantic_mapping` | 正在识别指标和维度…… |
| `querying_data` | 正在查询数据…… |
| `retrieving_knowledge` | 正在检索业务规则…… |
| `verifying` | 正在校验结果…… |
| `composing_answer` | 正在整理回答…… |

低层 Schema、Provider、Agent 和工具事件只能映射到上述业务阶段，不得泄露内部推理。

### `answer.delta`

必须包含非空 `delta`：

```json
{
  "event_type": "answer.delta",
  "delta": "华东区域本期销售额为"
}
```

- `delta` 来自真实 Provider 流或服务端 Answer Composer 的实际产出片段。
- 不允许完整答案持久化后再用 timer 切字播放。
- 前端按 `seq` 去重、排序并批量刷新；重复或倒序事件不得二次追加。

### `artifact.ready`

用于 KPI、chart、table、file artifact 或 evidence part。必须包含 `artifact_type` 和结构化 `artifact`；chart/table 必须绑定 Query ID 或结果签名。

### `citations.ready`

必须包含 `citations`，每条引用至少含可公开的标题、版本、定位和受控资源 ID。无授权证据时不得发送伪引用。

### `run.completed`

成功或受控部分成功的唯一终态，且必须是该 run 的最后业务事件：

```json
{
  "event_type": "run.completed",
  "status": "SUCCEEDED",
  "result_semantic": "VALUE",
  "message_parts": [],
  "response": {
    "conversation": {},
    "user_message": {},
    "assistant_message": {}
  }
}
```

`response.assistant_message.content` 必须与该 run 的所有 `answer.delta.delta` 拼接结果一致。不得在 `run.completed` 后继续发裸 `result`。

### `run.failed`

失败唯一终态，包含公开 `code`、`message` 和 `retryable`。不得附带成功结论、图表或已验证答案动作。

### `run.cancelled`

取消唯一终态，包含 `code=RUN_CANCELLED`。取消后不得继续追加 delta、artifact、citation 或 completed。

## 3. 状态机

```text
IDLE
  → UPLOADING
  → SUBMITTING
  → RUNNING
  → STREAMING
  → COMPLETED | FAILED | CANCELLED
```

- `run.started`：`SUBMITTING → RUNNING`
- 首个 `answer.delta`：`RUNNING → STREAMING`
- `run.completed`：`RUNNING|STREAMING → COMPLETED`
- `run.failed`：`SUBMITTING|RUNNING|STREAMING → FAILED`
- `run.cancelled` 或本地主动 Abort：`RUNNING|STREAMING → CANCELLED`
- 终态不可逆；会话切换后旧 run 只能更新其原会话缓存，不能写入当前会话视图。

## 4. 取消与心跳

- Stop 首先 abort 当前 fetch；服务端连接关闭后设置协作取消标志。
- SQL、RAG、Agent、ModelGateway 和文件分析在公开阶段边界检查取消；可中断的 Provider/driver I/O 应立即中止。
- Heartbeat 可以作为额外 `heartbeat` 事件发送，但必须携带标准 envelope，不改变 UI 阶段和答案文本。

## 5. 安全与一致性

- 认证、`query.ask` 权限、Workspace、用户、会话与附件归属在打开 SSE 前失败关闭。
- 不在事件中下发数据库凭据、模型密钥、宿主机路径、Prompt、原始 Provider 响应或思维过程。
- 最终消息、Message Parts、结果语义和前端展示必须来自同一 ChatResponse；刷新后内容不漂移。
- 同一 `client_message_id` 不得生成两套持久化消息或重复 delta。

## 6. 最小协议测试

1. `run.started` 是首事件。
2. `seq` 严格递增且 envelope 字段完整。
3. 至少两个真实 `answer.delta` 的长回答能拼成最终持久化 content。
4. `phase.started/completed` 成对且仅含公开阶段。
5. chart/citations 只在真实产物存在时发出。
6. 每个 run 只有一个终态，终态后无业务事件。
7. Abort 后为 `run.cancelled`，无后续 delta/持久化成功消息。
8. 切换会话时不串流。
9. 匿名、跨 Workspace、跨用户和跨会话请求继续返回 401/403。
