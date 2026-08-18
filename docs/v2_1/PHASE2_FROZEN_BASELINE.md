# Phase 2 Frozen Baseline

> 这是 v2.1 集成前的保护基线，不是 v2.1 Final PASS。Phase 2 历史、证据和 PASS SHA 不得改写。

## Scope

本任务属于 P0 基线保护与集成治理。它只冻结已经通过的真实问答、认证、会话、附件、多模态和查询主链路，不开发新业务能力。

## Canonical Git baseline

```text
PHASE2_SHA=6cdbf12f6c2e8494afe21262fd092795c4f784c3
PHASE2_TREE_SHA=c96b4da813b17b8ab2e0dee4a33a01b114a6f644
BASE_REMOTE_MAIN=23c6be78dd0c83dd81c5b4559ddab9dc77ff6fbd
LOCAL_AHEAD=3
SOURCE_BRANCH=main
SOURCE_WORKTREE_CLEAN=YES
PHASE2_PROTECTION_BRANCH=codex/phase2-pass-6cdbf12
FINAL_INTEGRATION_BRANCH=codex/v2.1-final-integration
FINAL_INTEGRATION_BASE_SHA=6cdbf12f6c2e8494afe21262fd092795c4f784c3
MERGE_EXECUTED=NO
MAIN_PUSHED=NO
FINAL_TAG_CREATED=NO
```

保护分支必须始终准确指向 `6cdbf12f6c2e8494afe21262fd092795c4f784c3`。集成分支从该 SHA 创建；本目录中的准备文档允许形成后续独立提交，但不能改变其 merge-base。

## Frozen acceptance results

```text
BACKEND_TEST=PASS (134/134)
FRONTEND_TYPECHECK=PASS
FRONTEND_TEST=PASS (29/29)
FRONTEND_BUILD=PASS
MIGRATION_TEST=PASS (1/1 upgrade-base-upgrade)
E2E_TEST=PASS (55/55)
COLD_START=PASS (isolated 48.8s)
CONSECUTIVE_START=PASS (20.61s,19.11s)
OPEN_ENDED_CHAT=PASS (60/60; runtime rate 1.0; trace 60/60)
SHORT_TERM_MEMORY=PASS (follow-up context 10/10)
AUTH=PASS (anonymous 401; cross-workspace 403; login/logout pass; bypass 0)
FILE_QA=PASS (accuracy 1.0)
IMAGE_QA=PASS (accuracy 1.0)
HARDCODED_ANSWER_PATHS=0
CONSOLE_ERRORS=0
PAGE_ERRORS=0
BLOCKING_REQUEST_ERRORS=0
```

## Frozen capabilities

- Question Router 和九类正式路由。
- `/api/v1/chat/stream`、`/api/v1/analysis/stream` 与 DATA Query 主链。
- General、Data、Knowledge、Hybrid、Complex、Clarification、Unsupported、File、Multimodal。
- Conversation、Message、短期槽位与摘要、会话持久化。
- 服务端 Auth Session、RBAC、Workspace/资源范围与审计。
- Chat Composer、Enter/Shift+Enter/中文 IME、停止/重试、SSE。
- Attachment API、结构化文件、文档解析、图片与 Vision。
- 一键启动的公开健康检查与匿名 401 认证验证。
- Alembic `20260818_0009` Phase 2 migration。

真实路径和每个文件在 Phase 2 SHA 上的 Git blob 锚点见 [PHASE2_FROZEN_FILES.json](PHASE2_FROZEN_FILES.json)。

## Evidence

- [Phase 2 evidence](../evidence/phase2/README.md)
- [Authentication runtime audit](../AUTH_RUNTIME_AUDIT.md)
- [Open-ended chat audit](../OPEN_ENDED_CHAT_AUDIT.md)
- [Isolated cold-start evidence](../evidence/phase2/cold-start-isolated.json)

## Freeze rules

1. 不得 rebase、squash、amend、reset 或删除 Phase 2 的三个本地提交。
2. 不得把 Phase 2 PASS 称为 v2.1 Final PASS。
3. 不得删除或改写冻结证据。
4. 任一输入触及冻结文件必须标记 `HIGH_CONFLICT`，逐文件集成，不得直接采用 incoming branch 覆盖。
5. 每合入一个工作流立即运行对应回归；禁止等全部输入合并后才首次测试。
6. 本任务不 push `origin/main`，不创建 Final Tag。
