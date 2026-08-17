# Phase 2 真实问答、认证与多模态验收证据

验收日期：2026-08-18（Asia/Shanghai）
任务：`CHATBI_V2_PHASE2_REAL_CHAT_AUTH_MULTIMODAL_CLOSURE`

## 结论

- 范围：P0，服务 ChatBI 主链路；没有引入通用 Agent、知识库平台或长期记忆。
- 固定答案运行路径：0。生产代码没有完整问题到固定答案/SQL 的映射；示例问题与普通输入进入同一个 `/api/v1/chat/stream`。
- 统一路由：DATA、KNOWLEDGE、HYBRID、COMPLEX、GENERAL、FILE、MULTIMODAL、CLARIFICATION、UNSUPPORTED 全部进入正式运行时。
- 数据问题继续经过 Semantic Context、NL2SQL、SQL Guard、只读 Executor 与 Result Oracle；显式 SQL 也先进入 DATA_QUERY，再由 Guard 精确允许或拒绝。
- 登录使用服务端会话，数据库只保存 Token 哈希；浏览器仅持有 HttpOnly/SameSite Cookie。匿名请求不再合成管理员，`X-ChatBI-Actor` 不再作为认证凭据。

## 开放式 60 题实测

命令：`backend/.venv` 环境执行 `backend/scripts/phase2_runtime_acceptance.py`；每题均创建真实会话并调用正式 Backend、数据库、RAG 或外部模型链路。

| Gate | 实测 |
| --- | ---: |
| 总题数 / 分布 | 60；15 Data、10 Knowledge、10 Hybrid/Complex、10 Follow-up、5 General、5 File、5 Image |
| OPEN_ENDED_REQUEST_RUNTIME_RATE | 1.0 |
| QUESTION_ROUTE_COVERAGE | 60/60 |
| TRACE_COMPLETE | 60/60 |
| FOLLOW_UP_CONTEXT_PASS | 10/10 |
| DATA_SQL_EXECUTION_RATE | 1.0 |
| DATA_RESULT_VALUE_ACCURACY | 1.0 |
| KNOWLEDGE_CITATION_ACCURACY | 1.0（7 个需引用问题均有受控引用） |
| FILE_RESULT_ACCURACY | 1.0 |
| IMAGE_QUESTION_ACCURACY | 1.0 |
| UNSUPPORTED_REQUEST_HALLUCINATION | 0 |
| 状态分布 | SUCCEEDED 58、REFUSED 1、PARTIAL 1 |

60 题冻结清单为 `evaluation/golden/phase2-open-ended-60.json`；包含新问法、同义改写、错别字、省略、信息不足、越权、无关问题、文件和图片问题。期望只用于评分，不被生产运行时读取。

## 会话、交互与附件

- 多轮序列“华东 → 华南 → 两者差距 → 月趋势 → 最大差距月 → 知识规则解释”槽位继承 6/6；冻结 Follow-up 总计 10/10。
- Playwright 验证 100dvh、底部 composer、独立滚动区、Enter、Shift+Enter、中文 IME 防误发、停止、重试、恢复/切换/删除、三视口和运行时错误。
- 后端真实解析 `.csv/.xls/.xlsx/.parquet/.pdf/.docx/.txt/.md/.png/.jpg/.webp`；不支持的 `.exe` 返回 415。
- MIME、扩展名、文件签名、大小、行数和文本资源均受限；附件只返回 ID，不返回宿主机路径，并按用户、Workspace、会话隔离及 TTL 清理。
- 浏览器 E2E 完成 CSV 计算与同附件追问、真实图片上传与视觉问答；后端格式测试覆盖其余文件解析器。

## 认证与启动

- 无痕受保护页跳转 `/login`；匿名 API、无效会话返回 401；跨 Workspace/跨用户资源返回 403；真实登录和 logout 当前会话撤销均通过。
- 一键启动脚本不创建用户、不登录、不生成或写入浏览器 Token、不拼接 Token URL。
- 首次冷启动验收发现旧 `scripts/verify.ps1` 匿名访问已受保护 API 后收到正确 401，却把它误判为启动失败；验证脚本已改为只检查公开健康端点，并要求 5/5 受保护端点匿名返回 401。
- 修复后从 `docker compose down` 状态连续启动两次：20.09 秒、18.98 秒；两轮 Backend、RAG Runtime、Frontend 最终均 healthy。
- 独立发布冷启动在临时 PostgreSQL Schema 完成 build、迁移 `20260818_0009`、真实登录、PostgreSQL/MySQL 同步、Ask + Oracle、Golden50、三家模型配置和清理，48.8 秒 PASS；结构化证据见 `cold-start-isolated.json`。
- Compose 数据库服务 0、数据库 volume 0；继续使用本机 PostgreSQL 主验证和 MySQL 兼容验证。

## 预提交门禁结果

- Backend：134/134 PASS（106.88 秒）。
- Frontend：TypeScript PASS；Vitest 10 files / 29 tests PASS；Vite production build PASS（734 modules）。
- Migration：单一 head；隔离 PostgreSQL Schema `upgrade → base → upgrade` 1/1 PASS（110.41 秒）。
- Playwright：串行 55/55 PASS（2.2 分钟）；包含 Phase 2 登录、会话、附件、多模态和 UI 三视口场景。
- 浏览器意外 console error、page error、blocking request error：0。页面切换或显式停止触发的 SSE 主动取消不计为阻断错误。
- 最终提交后仍需在 clean worktree 上复跑关键发布门禁；最终 SHA 和 clean 状态以交付输出为准。

未创建 Final Tag。
