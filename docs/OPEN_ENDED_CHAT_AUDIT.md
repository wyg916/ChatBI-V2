# 开放式问答与会话审计

采集基线：`23c6be78dd0c83dd81c5b4559ddab9dc77ff6fbd`

## 搜索结果

任务书列出的固定答案候选名称均未发现生产代码命中：`fixedQuestions`、`presetQuestions`、`sampleAnswers`、`mockAnswers`、`demoAnswers`、`fallbackAnswer`、`questionAnswerMap`、`verifiedQuestionMap`、`goldenQuestionMap`。

等价路径审计发现：

- `frontend/src/pages/AskExperience.tsx` 定义 `DEFAULT_QUESTION`，空输入会被替换为该问题。
- 示例问题与追问都通过 URL 参数重新进入单轮 `/ask`，没有 `conversation_id`、`parent_message_id`、历史摘要、业务槽位或附件上下文。
- `QuestionRouter` 只有 DATA/KNOWLEDGE/HYBRID/COMPLEX 四类；未命中知识/复杂关键词的问题一律归入 `DATA_QUERY`。
- 生产路由中不存在 Conversation 模型或 Attachment 上传端点。
- 前端只有单个结果页，不具备消息列表独立滚动、底部固定 composer、IME 防误发、停止生成或附件闭环。

## 根因

问题不是“固定问题到固定答案”的映射，而是更底层的等价限制：前端默认问题替换 + 单轮 URL 状态 + 四类启发式路由 + 没有真实通用模型聊天/澄清/文件/多模态能力。确定性 NL2SQL 本身按语义对象组合 SQL，不是完整问题字符串映射，应继续作为 DATA_QUERY 的可验证离线路径，但不能承担 GENERAL_CHAT、FILE_QUERY 或 MULTIMODAL_QUERY。

## 修复边界

- 建立一个统一 Chat API，以 Conversation/Message 为主资源；DATA_QUERY 仍复用 QueryPipeline，KNOWLEDGE/HYBRID/COMPLEX 仍复用受控 AnalysisService。
- 增加 GENERAL_CHAT、FILE_QUERY、MULTIMODAL_QUERY、CLARIFICATION、UNSUPPORTED；模型不可用时返回明确错误码。
- Verified SQL 只保留为 Context Builder 候选，不做答案短路。
- Trace 只保存路由、模型、Prompt/语义版本、证据、工具、SQL、错误与耗时，不保存模型内部推理。
- 示例问题只能调用同一统一入口。
