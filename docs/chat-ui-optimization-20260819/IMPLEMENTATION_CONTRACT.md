# ChatBI V2 对话界面一日优化实施契约

日期：2026-08-19
任务分支：`codex/chat-ui-chatgpt-style-20260819`
权威基线：`6cd05aaf7f558fee53fe83b1ccf82aeb98bf2a6f`

## 1. 范围与基线

本任务属于 P0。它只重构问数据页面、会话管理、统一流式事件、回答组织和结果语义，不重写 NL2SQL、受控 RAG、五角色六工具编排、附件解析、RBAC、Workspace 隔离或数据库访问边界。

基线实测：

- Backend：209 tests，退出码 0。
- Frontend Vitest：12 files / 33 tests PASS。
- TypeScript + Vite production build：738 modules PASS。
- Playwright 首轮：68/69 PASS；唯一失败是 `day1-core-flow.spec.ts:104` 的评测总览在默认 5 秒内仍处于加载态。
- 上述失败场景安静环境单独复验：1/1 PASS（19.9 秒）。首轮失败仍保留为基线事实，不计为全量 PASS。
- Backend `/health`、`/api/v1/version` 和 Frontend `/` 均返回 HTTP 200。
- 优化前截图：`artifacts/chat-ui-optimization-20260819/baseline/`，包含 1920×1080、1440×900、1366×768。

初始检查时存在两处未提交的图片模型临时失败重试实现和测试。它们已由共享仓库中的另一个执行流提交并推送为 `6cd05aa`；本任务不覆盖或重写该历史。

## 2. 目标布局

- 保留 236px 深色全局导航及六个一级模块；问数据仍是默认首页。
- 问数据顶部栏为 56px。
- 会话栏桌面展开 240–270px，可折叠为图标轨；1366px 基准取 240px。
- 消息区单列居中，阅读宽度 840–960px；用户消息右对齐浅紫气泡，Assistant 普通文本不套巨大外卡。
- KPI、图表、表格、引用等真实产物才使用卡片。
- 查询依据默认隐藏，以 360–420px（建议 392px）右侧 overlay drawer 打开，不成为固定第三列，不挤压消息区。
- Composer 位于 flex 正常流底部；页面只有消息区一个主滚动容器，会话列表可独立滚动。
- 适配 1920×1080、1440×900、1366×768；无横向滚动、无 Composer 覆盖。

回答区顺序固定为：核心结论 → KPI → 主图表 → 业务洞察 → 明细表 → 推荐追问。SQL、模型、Trace 和技术细节默认隐藏。

## 3. 会话管理

- 点击“新会话”只进入本地空态；第一条消息发送或首次附件上传时才创建服务端会话，避免空会话污染。
- 首轮完成后生成业务化标题；已存在的 `v2.1-final-load-*` 等严格测试前缀不进入正式列表展示。
- 会话按“今天 / 昨天 / 最近 7 天 / 更早”分组并支持本地搜索。
- 当前会话为浅紫选中态；更多菜单在悬停、焦点或按键时出现，包含重命名和删除。
- 新增受 RBAC、Workspace、用户隔离保护的 `PATCH /api/v1/conversations/{id}`，持久化重命名。

## 4. 后端流式与回答契约

唯一事件协议见 `STREAM_EVENT_CONTRACT.md`。Frontend 只依赖 ChatBI 规范事件，不依赖 Provider 原始格式，也不依赖旧 `progress/result` 事件。

统一回答由 Answer Composer 生成并同时服务流式展示与最终持久化。外部模型使用 Provider 的真实 streaming；确定性 Query/RAG/Agent 结果按实际生成的业务片段立即发出，不使用定时器或前端逐字符播放。最终 `run.completed.response.assistant_message.content` 必须等于所有 `answer.delta.delta` 按 `seq` 拼接后的文本。

结构化 Message Parts：

| `type` | 必需内容 | 用途 |
| --- | --- | --- |
| `text` | `text` | 核心结论、原因、建议、限制 |
| `kpi` | `items[{label,value,unit}]` | 已验证指标 |
| `chart` | `chart_spec`, `result_signature` | 绑定真实 Query 的图表 |
| `table` | `columns`, `rows`, `row_count` | 明细结果 |
| `citations` | `items[{title,version,locator}]` | 受控知识或文件引用 |
| `evidence` | `sql`, `guard`, `oracle`, `semantic`, `phases` | 查询依据抽屉 |
| `error` | `code`, `message`, `retryable` | 失败状态 |

内部 Agent 类名、工具名、Provider 原始响应、Prompt、思维过程和完整 Trace 不进入主消息；必要的深层运行详情仍须保留在受控 evidence 数据中。

## 5. 结果语义

Backend 必须输出稳定的 `result_semantic`：

| 语义 | 判定 | 主界面行为 |
| --- | --- | --- |
| `VALUE` | 查询有行且主指标为非 null、非零值 | 正常展示结论、KPI、图表、明细 |
| `ZERO` | 查询有行且主指标真实为数值 0 | 明确显示“当前条件下结果为 0”；不得视作无数据 |
| `NO_ROWS` | 查询成功但 `row_count=0` | 显示“没有匹配记录，并不代表指标为 0”；不生成伪图表或因果洞察 |
| `NULL_VALUE` | 查询有行但主指标为 null | 显示“查询到记录，但指标字段为空”；不得转为 0 |
| `FAILED` | SQL、权限、模型、数据源、执行或校验失败 | 显示可公开错误和重试入口；不得伪装为无数据 |

主界面用“查询执行已校验”表示 Guard/Oracle 检查通过，不再显示“查询可信度 100%”。完整检查只在查询依据抽屉展示。

## 6. 文件所有权矩阵

同一时刻同一文件只允许一名写入代理负责。

| 负责人 | 独占写入范围 | 禁止写入 |
| --- | --- | --- |
| `IMPLEMENT_UI_SHELL` | `frontend/src/pages/AskExperience.tsx`、`frontend/src/pages/ask.css`、新建 `frontend/src/pages/chat-ui/**` | API client、全局类型、Backend、测试、文档 |
| `IMPLEMENT_STREAM_AND_COMPOSER` | `frontend/src/api/chat.ts`、`frontend/src/types/api.ts`、新建 `frontend/src/chat/**`、`frontend/src/test/chat-stream.test.ts` | `AskExperience.tsx`、`ask.css`、Backend、E2E、文档 |
| `IMPLEMENT_ANSWER_CONTRACT` | `backend/app/api/routes/chat.py`、`backend/app/streaming/**`、`backend/app/services/chat.py`、新建 `backend/app/services/answer_composer.py`、会话/Query/Oracle/Insight/ModelGateway 所需后端文件及对应 backend tests | 全部 Frontend、E2E、文档 |
| 主控 | 本目录文档、跨边界集成、最终状态/决策/发布文档 | 代理运行期间不与其独占文件并行写入 |
| `QA_E2E_AND_VISUAL`（阶段 4） | 新建或修改 Chat UI 专项测试与截图脚本 | 核心业务代码 |

如需越界，代理必须停止并返回 `CROSS_BOUNDARY_CHANGE_REQUEST`，包含路径、理由、建议内容和依赖。

## 7. 测试与门禁

定向集成门禁：

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest tests/test_v21_streaming_protocol.py tests/test_phase2_auth_chat_attachments.py -q

cd ..\frontend
npm run typecheck
npm test -- --run
npm run build
```

最终门禁：Backend 全量、Frontend lint（若仓库无 lint script 则如实记为 N/A）、TypeScript、Vitest、build、Playwright 全量、Golden、RAG、Multi-Agent、附件/图片、RBAC、Workspace 隔离、Compose 生产产物浏览器 smoke、Docker 连续两次停止态启动。

专项测试至少覆盖：规范 SSE 多 delta/单调序号/唯一终态/取消/持久化一致；五类结果语义；新会话延迟创建；会话搜索/分组/重命名/删除/折叠；Enter/Shift+Enter/IME；上传/拖放/粘贴/进度/失败；三视口无横向溢出、抽屉默认关闭、Composer 不覆盖、问题只出现一次、无语音/麦克风。

## 8. 禁止事项

- 禁止前端逐字符动画或固定 timer 制造假流式。
- 禁止固定问题到固定答案/SQL 映射。
- 禁止将 null 转为 0、失败转为无数据，或以空行结果生成成功业务洞察。
- 禁止展示模型内部推理、原始 Provider 响应或默认暴露 Agent/工具内部名称。
- 禁止前端直连数据库或接收数据库/模型密钥。
- 禁止破坏登录、RBAC、Workspace/用户/会话/附件隔离。
- 禁止新增语音或麦克风。
- 禁止新增通用 Agent/RAG/知识库/插件平台。
- 禁止通过跳过测试、降低断言或删除用例制造 PASS。
