# ChatBI V2 对话界面优化回滚说明

## 回滚目标

把本轮 Chat UI、canonical SSE、Answer Composer、Message Parts、会话重命名和相应测试作为一个完整变更单元回退，同时保留基线 `6cd05aaf7f558fee53fe83b1ccf82aeb98bf2a6f` 之前的产品能力与数据。

本轮没有数据库迁移、Docker 数据库服务、Docker volume、第三方依赖或凭据变更，因此代码回滚不需要修改本机 PostgreSQL/MySQL 数据，也不得删除用户数据库。

## 推荐方法

1. 在正式集成前，直接放弃任务分支即可；不要修改 `main`、正式集成分支或公开 Tag。
2. 合入后若需回滚，针对本轮最终提交执行非破坏性的 `git revert <CHAT_UI_COMMIT_SHA>`，保留审计历史；禁止 force push。
3. 重新构建 Backend/Frontend，停止后启动服务，并至少复验认证、问数据、会话列表、附件、DATA/RAG/Agent 路由和原有 Playwright 发布门禁。
4. 核验受保护 API 仍为服务端会话鉴权，前端仍只经 Backend API 访问数据。

## 兼容回滚开关

前端 SSE 客户端保留受约束的旧协议内部适配，可在服务端分批回滚时避免立即白屏；该适配不向 UI 暴露旧事件，也不允许把旧的一次性结果标记为本轮“真实流式”通过。完成回滚后应按正式版本统一前后端，不把混合协议长期保留为发布状态。

## 数据与持久化

- 会话正文仍存入既有 Conversation/Message 资源；Message Parts 使用现有响应载荷，不需要 Alembic downgrade。
- 回滚不会删除本轮测试创建的业务会话。若需要清理，只能按现有 Workspace/用户隔离 API 精确删除测试前缀会话，不得直接清空元数据库。
- 优化前后截图与测试报告是证据，不参与运行时回滚。

## 回滚验收

- Backend、Frontend、Playwright 最小发布门禁通过。
- Docker Compose 从停止状态启动成功，且仍不包含数据库服务或数据库 volume。
- 本地分支、remote tracking 与 `ls-remote` 指向预期回滚提交。
- 工作树 clean；没有遗留 stash、临时分支、未跟踪运行产物或公开 Tag 变更。
