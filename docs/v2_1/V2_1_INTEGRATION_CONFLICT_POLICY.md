# v2.1 Integration Conflict Policy

## Current state

```text
BASE=6cdbf12f6c2e8494afe21262fd092795c4f784c3
MERGE_EXECUTED=NO
READY_TO_MERGE=NO
```

本文件只定义后续集成规则；本任务不执行 B/C/E/A/D 的 merge、cherry-pick、rebase 或内容复制。

## Fixed integration order

```text
BASE Phase2
→ E Data/10M/Performance
→ B IBM Eval/Golden/SQLBot
→ C Chat2DB/SQL Workspace
→ A Wren/OpenChatBI/SuperSonic
→ D RAG/Agent/PandasAI
→ Final Gate
```

- E 先建立统一测试数据和性能基准。
- B 在统一数据上集成评测、Golden 和反馈。
- C 在前两层稳定后接入数据工作台。
- A 会触及 DATA_QUERY、Semantic 和 Router，必须基于已稳定基线逐文件处理。
- D 会触及 RAG、Agent、File、Attachment 和 SSE，最后处理以减少对 Phase 2 的破坏。

## Conflict classification

- **HIGH_CONFLICT**：任何修改、删除、重命名或生成覆盖 [PHASE2_FROZEN_FILES.json](PHASE2_FROZEN_FILES.json) 中的路径。
- **HIGH_CONFLICT**：新增文件改变冻结路由、会话/Auth 数据模型、SSE 协议、迁移 head、附件存储或一键启动认证语义，即使没有同名文件冲突。
- **MEDIUM_CONFLICT**：冻结区外的共享依赖、构建配置或测试设施改动，可能间接改变 Phase 2 行为。
- **LOW_CONFLICT**：冻结区外纯新增且接口隔离的文档、测试数据或适配器，不改变现有契约。

Git 自动合并成功不代表业务低冲突；只要触及冻结区，仍按 HIGH_CONFLICT 处理。

## Intake and per-workflow integration procedure

1. 核验输入的正式 SHA、Tree SHA、clean 状态、测试数字与许可证说明。
2. 记录 `git diff --name-status 6cdbf12f6c2e8494afe21262fd092795c4f784c3...<INPUT_SHA>` 和 `git diff --stat 6cdbf12f6c2e8494afe21262fd092795c4f784c3...<INPUT_SHA>`。
3. 将 changed files 与冻结 JSON 精确求交；有交集即生成逐文件 HIGH_CONFLICT 清单。
4. 在独立集成分支上一次只处理一个工作流；禁止 `checkout --theirs`、整目录复制或无审查覆盖冻结文件。
5. 对每个 HIGH_CONFLICT 文件同时检查 Phase 2 blob、incoming blob 和目标契约，保留认证、Workspace、Result Oracle、Trace、SSE 与附件隔离语义。
6. 该工作流落地后立即运行基础回归和相应扩展回归，只有通过才提交单独 integration commit。
7. 前一工作流未通过或未记录 blocker，不进入下一个工作流。
8. 五个输入完成后再运行 Final Gate；此前不得宣告 v2.1 PASS 或创建标签。

## Minimum regression after every workflow

| Gate | Minimum command / evidence |
| --- | --- |
| BACKEND_SMOKE | `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_phase2_auth_chat_attachments.py backend/tests/test_security.py -q` |
| FRONTEND_BUILD | `npm --prefix frontend run build` |
| MIGRATION_HEAD_CHECK | `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_migrations.py -q` |
| AUTH_SMOKE | 两个认证用例：匿名/无效会话 401、跨 Workspace 403 |
| OPEN_ENDED_CHAT_SMOKE | `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_phase2_open_ended_manifest.py -q` |
| CONVERSATION_MEMORY_SMOKE | `test_multiturn_slot_inheritance_matches_required_sequence` |

## Extra regression for core Query changes

- QUESTION_ROUTE_COVERAGE：`test_question_router_covers_governed_data_knowledge_complex_and_general_routes`。
- DATA_QUERY：QueryPipeline、SQL Guard、Executor、Result Oracle。
- GENERAL_CHAT：`test_general_chat_persists_conversation_trace`。
- FOLLOW_UP_CONTEXT：短期槽位与 10 条追问上下文门禁。

## Extra regression for RAG / Agent / File changes

- KNOWLEDGE_QUERY：授权引用与 Citation Guard。
- HYBRID_ANALYSIS：只融合 Oracle 与 CitationVerifier 已验证结果。
- COMPLEX_ANALYSIS：固定角色/工具/预算/Trace。
- FILE_QUERY：结构化文件和文档解析准确性。
- MULTIMODAL_QUERY：真实图片上传与 Vision 问答。
- ATTACHMENT_ISOLATION：用户、Workspace、会话隔离和宿主机路径不泄露。

## Final Gate

所有输入完成后才允许执行：Backend 全量、Frontend typecheck/test/build、单一 migration head 的 upgrade-base-upgrade、Playwright 全量、60 条真实开放式会话、Golden 回归、隔离冷启动和连续两次一键启动。任何硬 Gate 未通过时，状态只能是 PARTIAL 或 BLOCKED。

## Prohibited actions

- 修改 Phase 2 PASS SHA 或保护分支指向。
- rebase、squash、amend、reset Phase 2 历史。
- 直接接受 incoming branch 覆盖冻结文件。
- 在所有正式输入到齐前合并 B/C/E/A/D。
- push `origin/main` 或创建 V1.1.0 Final Tag。
- 优化现有 ECharts 555.48 kB warning。
- 删除 Phase 2 证据或把 Phase 2 PASS 描述为 v2.1 Final PASS。
