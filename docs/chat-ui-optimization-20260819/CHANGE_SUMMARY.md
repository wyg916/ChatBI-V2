# ChatBI V2 对话界面一日优化变更摘要

日期：2026-08-20
基线：`6cd05aaf7f558fee53fe83b1ccf82aeb98bf2a6f`
Source 分支：`codex/chat-ui-chatgpt-style-20260819`
正式集成分支：`codex/v2.1-final-integration`

## 结果概览

本轮把“问数据”调整为 Chat-first 单列对话体验，同时保留 ChatBI 的确定性数据查询、受控知识检索、有限多 Agent、文件/图片问答、Workspace/RBAC、SQL Guard、Result Oracle、图表与引用能力。界面不新增语音、麦克风、通用 Agent 平台或其他 P2 能力。

## 用户界面

- 登录后仍默认进入“问数据”，六个一级模块与紫色品牌保持不变。
- 全局导航、会话栏和单列消息区形成清晰三层信息架构；主阅读宽度受控，三种目标桌面视口不依赖横向滚动。
- 新会话先进入本地空态，首条消息或附件上传时才创建服务端会话，避免空会话污染。
- 会话支持搜索、时间分组、折叠、生成状态、重命名和删除确认，并过滤内部自动化测试标题。
- 用户问题只显示一次；Assistant 回答取消巨大外层卡片，按结论、KPI、图表、洞察、明细、引用、追问排列。
- SQL、数据口径、业务依据、公开分析阶段与校验结果进入默认关闭的右侧 overlay 抽屉；不显示 Agent 类名、工具名、Trace 或模型内部推理。
- 输入区保留 Enter、Shift+Enter、中文输入法保护、文件选择、拖拽、图片粘贴、上传进度、删除、停止、重试、复制、自动跟随暂停和“回到最新消息”。
- `VALUE`、`ZERO`、`NO_ROWS`、`NULL_VALUE`、`FAILED` 分开渲染，数值 `0` 不再落入无数据状态。

## 流式协议与答案契约

- `/chat/stream` 与 `/analysis/stream` 统一为九类 canonical SSE：`run.started`、`phase.started`、`phase.completed`、`answer.delta`、`artifact.ready`、`citations.ready`、`run.completed`、`run.failed`、`run.cancelled`。
- 每个事件包含 `seq`、`run_id`、`conversation_id`、`message_id`、`timestamp`、`event_type`；客户端拒绝倒序、重复、终态后事件和正文不一致。
- Provider Adapter 提供真实增量；确定性答案由 Answer Composer 基于真实结果逐部件产生，不用 `sleep` 或模拟打字。
- 客户端只以约 40ms 批量刷新已经收到的真实 delta；终态或异常前同步 flush。
- `run.completed.response.assistant_message.content`、Message Parts、持久化正文与客户端拼接 delta 保持一致；失败和取消各自只有一个末尾终态。
- Message Parts 结构化保存文本、KPI、图表、表格、引用、证据、Artifact 与建议问题；引用和 Artifact 只发布带真实身份/定位/结果签名的受控对象。
- 表格 Message Part 最多携带 UI 实际展示的前 20 行，`row_count` 和结果签名仍保留真实总量；原已验证 execution 结果不截断，避免宽表在多个事件位置重复放大网络载荷。
- 会话新增 Workspace/用户隔离的 `PATCH` 重命名，标题会清理换行和多余空白。

## 兼容性与边界

- `DATA_QUERY` 仍进入 Semantic/NL2SQL/SQL Guard/只读 Query Executor/Result Oracle。
- `KNOWLEDGE_QUERY`、`HYBRID_ANALYSIS`、`COMPLEX_ANALYSIS` 继续使用受控 RAG、验证后融合和固定五角色有限编排。
- 文件与图片仍使用既有附件、模型网关和授权 Artifact 链路；没有把前端改成直连数据库或保存数据库凭据。
- 评测反馈术语查询显式关联 Semantic Model 并按当前 Workspace 过滤；同工作空间按规范化术语/映射业务键稳定去重，避免跨 Workspace 术语混入与 React 重复 key。
- 未引入第三方代码或依赖，`THIRD_PARTY_NOTICES.md` 无需变更。

## 主要代码范围

- Frontend UI：`frontend/src/pages/AskExperience.tsx`、`frontend/src/pages/ask.css`、`frontend/src/pages/chat-ui/`
- Frontend stream：`frontend/src/api/chat.ts`、`frontend/src/chat/stream.ts`、`frontend/src/types/api.ts`
- Backend：`backend/app/api/routes/chat.py`、`analysis.py`、`backend/app/services/chat.py`、`answer_composer.py`、`backend/app/streaming/`、`backend/app/integration/model_gateway.py`
- Tests：`backend/tests/test_chat_answer_contract.py`、现有协议/附件回归、Frontend Vitest 与 Playwright 对话体验覆盖

最终门禁数字、截图、浏览器错误统计和 Git 状态见 `TEST_REPORT.md`。

## 正式集成差量

- 远端 Target 在集成开始时不存在；从远端 `main` 的 `094c81a` 创建后，以 merge commit `8676c07` 非破坏性合并 Source `31530f3`。双方互非祖先，故未伪装为 fast-forward。
- `docs/STATUS.md` 与 `frontend/e2e/day3-final-product.spec.ts` 自动合并，无冲突、无人工丢弃；目标侧有界等待与 Source 侧 Chat UI/SSE 契约均保留。
- `15291e6` 只补发布级交互与错误监听测试；`758de13` 只修复长会话刷新门禁的持久化竞态。
- 正式集成后覆盖从 50/80 提升为 52/82；最终定向 52/52、串行 82/82，产品代码与业务口径没有继续扩张。
- 详细 merge identity、证据哈希与推送/回滚约束见 `FINAL_INTEGRATION_REPORT.md`。
