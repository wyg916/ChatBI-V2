# EVAL / Feedback 主控集成请求

## 范围与当前状态

并行分支 `codex/v2.1-eval-golden-feedback` 只修改评测与反馈边界，没有修改 Question Router、Query Executor、Auth、Session、Conversation、Chat UI、Attachment、Migration、`docker-compose.yml` 或 Final Tag。

本分支已在现有数据库契约上完成：

- EvaluationAdapter 的 execution-based compare、Multiple Ground Truth、错误分析和八类准确率；
- 评测创建、执行、五维 Profile 比较、Dashboard 和 Release Gate API/UI；
- 正确/错误反馈、人工修正、审核、Verified SQL、版本、相似召回、正式 QueryPipeline、Oracle 与回放；
- 独立 CI workflow、release-gate 脚本、Backend/Frontend/E2E 测试。

## 主控必须处理的接口请求

### IR-EVAL-001：按评测运行选择 Provider / Prompt / Engine

当前核心 `AskRequest` 和 `QueryPipeline` 没有每次运行可注入的 `model`、`prompt`、`SemanticEngineAdapter`、`NL2SQLEngineAdapter` 选择接口。并行分支遵守边界，没有修改核心契约。现状是每个评测运行会持久化并比较 `model / prompt / semantic_engine / nl2sql_engine / version` Profile；SQL 实际执行仍使用该 Backend 实例当前配置的正式 QueryPipeline。不同配置实例或不同版本产生的运行可以真实比较，但同一进程内不能安全切换核心 Provider/Prompt。

主控后续应提供 evaluator-owned、只读、显式 allowlist 的 `EvaluationPipelineFactory(profile)`，内部仍必须进入 SQL Guard、只读 Query Executor 与 Result Oracle。禁止把任意 Provider/Prompt 或 Connector 直接交给前端。

### IR-EVAL-002：专用 Evaluation Profile / Feedback Workflow 表

本分支禁止修改 Migration，因此 Profile 暂存于 `EvaluationRun.trend_points` 的类型化 metadata 项；八类准确率、result compare、error analysis 存于 `EvaluationCaseResult.actual`；修正、审核、召回和回放证据存于 `VerifiedAnswer.feedback` 与 `AnswerVersion.snapshot`。API 会过滤 metadata，不会污染趋势图。

主控统一 Migration 时建议新增专用表：

- `evaluation_profile` / `evaluation_run_profile`；
- `feedback_correction` / `feedback_review` / `verified_sql_replay`；
- 保留当前 JSON 读取兼容并提供一次性 backfill；
- 不覆盖现有 QueryRun、VerifiedAnswer、AnswerVersion 或 Evaluation 历史。

### IR-EVAL-003：Authentication 合并

本分支只复用当前 `require_permission("evaluation.read" | "evaluation.run" | "answer.manage")`，不修改 Auth。主控合并新 Authentication 后，需要把评测创建/执行/审核绑定真实用户与 Workspace，并确认 Reviewer 角色权限；不得信任浏览器提交的 reviewer 身份。

### IR-EVAL-004：前端路由合并

为避免修改主控正在变更的 `frontend/src/router.tsx`，反馈页位于现有一级模块的 `/evaluation?view=feedback`，由 `EvaluationOverviewPage` 内部切换。若主控拆分二级路由，应保持“评测中心”仍是唯一一级导航，并保留该 query URL 的兼容跳转。

## Cherry-pick 建议

1. 先合并主控 Auth/Runtime/Migration；
2. cherry-pick 本分支提交；
3. 解决 `frontend/src/types/api.ts` 与评测类型的机械冲突；
4. 实现 IR-EVAL-001/002 后运行数据 backfill；
5. 使用独立 metadata database、独立端口执行 `backend/scripts/run_v21_release_gate.py --require-feedback`；
6. 通过前不得 merge main、创建 Tag 或宣称 Final PASS。
