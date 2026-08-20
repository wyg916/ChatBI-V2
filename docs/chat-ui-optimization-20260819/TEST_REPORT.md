# ChatBI V2 对话界面优化测试报告

日期：2026-08-20
基线 SHA：`6cd05aaf7f558fee53fe83b1ccf82aeb98bf2a6f`
Source 分支：`codex/chat-ui-chatgpt-style-20260819`（`31530f30972b0dc773112e2b1fabf61834ba7310`）
正式集成分支：`codex/v2.1-final-integration`

## 真实性声明

本报告只记录实际执行结果。HTTP 200、页面可打开或单独 SQL 可执行不替代结果值、Workspace 隔离、流式一致性和浏览器错误检查。最终串行 Playwright、两次停止态启动与原始日志均已在当前工作树完成；Git/远端 SHA 以任务最终返回和远端核验为准。

## 优化前基线

- Backend：209 tests collected，`pytest -q` 退出码 0。
- Frontend：12 files / 33 tests PASS；TypeScript 与 Vite build（738 modules）PASS。
- Playwright 首轮：68/69；`evaluation overview` 首次 5 秒加载断言失败，隔离复跑 1/1 PASS。因此优化前完整 E2E 如实记为非全通过。
- 三视口截图：`artifacts/chat-ui-optimization-20260819/baseline/`。

## 当前稳定代码门禁

| 门禁 | 实际结果 | 备注 |
| --- | --- | --- |
| Backend 全量 | 223/223 PASS | 含 canonical SSE、宽表载荷、Workspace 术语隔离 |
| Backend Chat/stream 专项 | 31 PASS | 500 行表格部件压缩、原 execution 不截断 |
| Backend feedback 专项 | 5/5 PASS | 双 Workspace、重复业务键、稳定顺序 |
| Frontend TypeScript | PASS | `tsc --noEmit` |
| Frontend Vitest | 13 files / 50 tests PASS | Ask 16、stream 10，含会话/附件竞态 |
| Frontend build | PASS | 741 modules；保留既有 EChart 555.48 kB warning |
| NL2SQL/RAG/Agent/File/Workspace 六组 | 105 PASS | 独立复核从 `backend/` 正确工作目录运行 |
| Chat UI 真实 Playwright 专项 | 13/13 PASS | 新增复制/重新生成/无语音和 ZERO/NULL 用户态覆盖 |
| Playwright 定向门禁 | 52/52 PASS | 1 worker，4.7 分钟 |
| Playwright 全量发布门禁 | 82/82 PASS | 1 worker，5.9 分钟；修复后完整重跑 |
| Frontend lint | N/A | `package.json` 没有 lint script；TypeScript/build/unit/E2E 均单独执行 |

## 已执行的浏览器探测

- 6-worker 并发探测：67 passed / 13 failed。共享数据库和 fixture 互相覆盖，不作为 ADR-022 发布门禁；失败被保留用于发现测试隔离问题。
- 首轮 1-worker 串行：66 passed / 14 failed。它命中了修复前的 5175/8011 常驻进程，并发现旧 DOM 断言、auth-state 输出目录清理、Feedback 重复 key 等问题；不作为最终门禁。
- 正式定向：同时重启独立 Frontend 5175 与 Backend 8011、探测当前源码后，`--workers=1` 运行 50 项，50/50 PASS（3.9 分钟）。
- 最终发布门禁：同一当前工作树环境以 `--workers=1` 完整运行 80 项，80/80 PASS（5.1 分钟）。Console error、page error、unexpected request failure、unexpected blocking 4xx/5xx 均为 0；预期的匿名/越权/无效请求 401/403/415/422 不计为意外阻断。
- 正式集成门禁：生产 Docker 栈上定向 52/52 PASS（4.7 分钟）。首轮全量 81/82 暴露 pending Assistant DOM 早于服务端事务提交的测试竞态；改为 API 持久化轮询后隔离 1/1 PASS，最终完整串行 82/82 PASS（5.9 分钟）。没有删除测试、跳过失败或降低 21 条消息断言。
- 正式集成浏览器监听覆盖 console、pageerror、requestfailed 和非 allowlist HTTP `>=400` response；最终异常计数均为 0。

## 已验证的核心契约

- canonical 九事件、`seq` 单调、阶段成对、唯一末尾终态。
- 长回答至少两个真实 delta；拼接正文等于终态与持久化正文。
- reader 在完成、取消和协议异常路径均 cancel/release。
- `VALUE/ZERO/NO_ROWS/NULL_VALUE/FAILED` 五态分离，`ZERO` 不等于无数据。
- `ZERO/NO_ROWS/NULL_VALUE` 用户态均不得展示“可信度 100%”或仅“—元”；失败不伪装空结果。
- 成功回答复制到剪贴板、成功重新生成、原紫色 RGB 和无语音/麦克风入口由真实浏览器强断言覆盖。
- 新会话懒创建、快速双击防重、创建期间导航失效、B→C 逆序响应隔离、空态首传附件采用同一会话。
- 会话切换立即取消旧 Run，迟到 delta/terminal 不进入新会话。
- Evidence Drawer 默认隐藏，Tab/Shift+Tab 焦点陷阱、背景 inert、Escape/关闭回焦。
- 三视口无横向溢出，composer 不覆盖消息；图表 DOM 高度不小于 240px 且 canvas/SVG 可见。
- 匿名、跨用户会话/流/附件 fail closed；术语查询按 Workspace 隔离。

## 停止态启动

- 正式集成 Run 1：确认 `docker compose ps -a` 为空后，`scripts/start.ps1` 完整重建并启动；Backend、RAG Runtime、Frontend 均 healthy，命令退出码 0。
- 正式集成 Run 2：再次停止并确认 Compose 为空后，`scripts/start.ps1 -SkipBuild` 在 33.794 秒内启动；三项服务均 healthy，命令退出码 0。
- 两轮均验证 Frontend/Backend HTTP 200、受保护 API 5/5 返回 401、本机元数据 PostgreSQL READY，以及本机 PostgreSQL/MySQL 端口可达。Compose 服务只有 Backend、RAG Runtime、Frontend，数据库服务和数据库卷均为 0。

## 截图与报告路径

- 优化前：`artifacts/chat-ui-optimization-20260819/baseline/`
- 优化迭代：`artifacts/chat-ui-optimization-20260819/optimized/`
- Source 最终三视口、结果态与抽屉态：`artifacts/chat-ui-optimization-20260819/final/`
- 正式集成截图、脱敏文本日志和 SHA-256 manifest：`artifacts/chat-ui-optimization-20260819/final-integration/`。
- Playwright HTML/trace 与临时 auth state 可能包含会话 Cookie，已安全删除且不提交；可审计结果保留为纯文本与 `commands.json`。

## 最终结论

正式集成代码、浏览器、Secret scan 和两次停止态启动门禁均 PASS。最终 Git SHA、push、tracking/`ls-remote` 一致性、clean worktree 与 Tag 未变化由包含本报告的最终提交推送后核验，准确值见最终交付输出。
