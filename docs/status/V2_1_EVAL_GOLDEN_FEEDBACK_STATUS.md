# ChatBI V2.1 Evaluation / Golden / Feedback 并行任务状态

`TASK_STATUS=PASS`（以分支内实现与隔离验证为准；不代表已合并 main 或创建 Final Tag）。

## 已完成

- IBM-compatible EvaluationAdapter：execution-based evaluation、Multiple Ground Truth、Result Compare、Error Analysis。
- 评测中心：创建、执行、Case 证据、五维 Profile 比较、八类准确率 Dashboard、Release Gate。
- Golden 50：Metric、Dimension、Time、Filter、Join、Result Value、Chart、Narrative 全覆盖。
- SQLBot 参考闭环：术语库、SQL 示例、正确/错误反馈、人工修正、审核、Verified SQL、版本、相似召回、正式安全链路、Oracle、回归。
- CI：确定性 Backend/Frontend gate，以及指向隔离 Backend 的 live Golden/Feedback release gate。

## 实测数字

- Backend：130/130 PASS。
- Frontend：29/29 PASS；Vite build PASS（732 modules）。
- 专项 E2E：2/2 PASS。
- PostgreSQL Golden：执行/结果/语义 50/50。
- MySQL compatibility Golden：执行/结果 10/10。
- `SQL_EXECUTION_RATE=1.0`。
- `RESULT_VALUE_ACCURACY=1.0`。
- `DANGEROUS_SQL_BLOCK_RATE=1.0`（38/38）。
- 八类准确率全部 `1.0`。
- `FEEDBACK_REPLAY_RATE=1.0`（3/3）。

## 隔离与边界

- Worktree：`E:/ChatBI-V2-wt-eval-feedback`。
- Backend/Frontend：`18080` / `15173`。
- Metadata：本机 PostgreSQL 独立 schema `chatbi_eval_feedback_v21_0818`。
- Docker/Compose：未启动、未修改。
- 未修改核心 Question Router、Query Executor、Auth、Session、Conversation、Chat UI、Attachment API、Migration、Docker Compose 主文件或 Tag。
- 核心缺失的 per-run Provider/Prompt/Engine 注入与专用表 Migration 已记录在 `docs/integration_requests/EVAL_FEEDBACK_INTEGRATION_REQUEST.md`。
