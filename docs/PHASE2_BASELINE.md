# Phase 2 现场基线

采集时间：2026-08-18（Asia/Shanghai）
任务：`CHATBI_V2_PHASE2_REAL_CHAT_AUTH_MULTIMODAL_CLOSURE`

## 范围判断

本任务直接补齐自然语言问数、受控 RAG/有限编排、会话、附件、多模态与认证主链路，属于 P0。不得以 P1/P2 能力替代，也不得创建 Final Tag，直到全部 Phase 2 硬 Gate 在同一最终 SHA 通过。

## Git 基线

- 分支：`main`
- HEAD：`23c6be78dd0c83dd81c5b4559ddab9dc77ff6fbd`
- 上游：`origin/main`
- 初始工作树：clean
- 远端：`https://github.com/wyg916/ChatBI-V2.git`
- 最近发布标签：`chatbi-v2-v1.0.1`

## 运行基线

- `backend`、`rag-runtime`、`frontend` 三个 Compose 服务均为 healthy。
- Compose 中没有 PostgreSQL/MySQL 容器或数据库 volume；项目继续使用本机 PostgreSQL（主验证）和 MySQL（兼容验证）。
- 一键启动由 `一键启动-ChatBI-V2.cmd` → `scripts/launch.ps1` → `scripts/start.ps1` 驱动，只负责依赖检查、Compose 启动、健康检查、验证和打开前端。
- `.env` 为本机忽略文件；现场只核验配置项存在性，没有读取或记录任何密钥/密码正文。

## 修改前测试

- Backend pytest：完成且退出码 0（原配置为 quiet，仅输出进度点；最终阶段将用显式统计格式重跑）。
- Frontend Vitest：10 files / 27 tests PASS。
- Frontend production build：PASS；TypeScript 校验包含在 build 中。
- Playwright E2E：51/51 PASS，耗时约 1.3 分钟。

上述结果只证明第一阶段回归基线通过，不代表 Phase 2 Gate 通过。

## 修改前安全复现

在不带 Cookie、Bearer Token 或身份头的情况下：

- `GET /api/v1/datasources` → HTTP 200（期望 401）。
- `GET /api/v1/security/overview` → HTTP 200（期望 401）。
- 直接访问 `/datasources` → HTTP 200，前端无统一认证守卫。

这些结果构成认证绕过的现场证据。

## 关键配置来源

- 元数据库、只读数据源、RAG 签名和模型凭据：本机 `.env` → Docker Compose server-side environment。
- 浏览器不应获得数据库或模型凭据。
- Phase 2 将新增独立应用会话与附件资源限制配置；一键启动不得生成会话 Token、写浏览器存储或拼接带 Token URL。
