# ChatBI V2 对话界面优化回滚说明

## 回滚目标

把本轮 Chat UI、canonical SSE、Answer Composer、Message Parts、会话重命名和相应测试作为一个完整变更单元回退，同时保留基线 `6cd05aaf7f558fee53fe83b1ccf82aeb98bf2a6f` 之前的产品能力与数据。

本轮没有数据库迁移、Docker 数据库服务、Docker volume、第三方依赖或凭据变更，因此代码回滚不需要修改本机 PostgreSQL/MySQL 数据，也不得删除用户数据库。

## 推荐方法（正式集成分支）

1. 保留 `main`、Source branch 和全部公开 Tag；禁止 force push、reset 或删除数据库。
2. 在 `codex/v2.1-final-integration` 按逆序 revert merge 之后的证据/测试修复提交（包括 `758de13`、`15291e6` 和最终证据提交），保留审计历史。
3. 对 merge commit 使用主线父 1：`git revert -m 1 8676c07cc3144026fbbd282f54d318ae3cc2f546`。不得对该 merge commit 使用缺少 `-m 1` 的普通 revert。
4. 重新构建 Backend/Frontend，停止后启动服务，并至少复验认证、问数据、会话列表、附件、DATA/RAG/Agent 路由和原有 Playwright 发布门禁。
5. 核验受保护 API 仍为服务端会话鉴权，前端仍只经 Backend API 访问数据；核验本地、tracking 与 `ls-remote` 相等。

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
- `main`、Source branch 与全部既有 annotated Tag object/peeled SHA 保持不变。
