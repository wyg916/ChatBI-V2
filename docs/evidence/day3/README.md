# Day 3 Evidence

- `golden-results.json`：Backend 持久化 Golden20 最新运行摘要与 Case 结果。
- `golden-compat-results.json`：PostgreSQL 20 条与 MySQL 5 条兼容回归。
- `security-results.json`：38 条危险 SQL 与两个真实只读写尝试。
- `migration-results.json`：隔离 PostgreSQL Schema 的单 head、upgrade/base/upgrade。
- `seed-idempotence.json`：连续两次 seed 计数一致。
- `test-summary.json`：Backend、Frontend、Playwright、UI、Golden 与依赖门禁汇总。
- `provider-smoke.json`：Local Runtime 与外部模型配置状态。
- `secret-scan.json`：凭据模式、私钥文件和被追踪运行环境文件扫描。
- `cold-starts.json`：两次从完整停止状态执行的一键构建、启动、健康检查与本机 PostgreSQL/MySQL 连接证据。

所有 PASS 数字来自本轮真实命令或持久化 API。共享元数据库的 Playwright 发布门禁使用单 worker 串行执行，完整 34/34 结果记录在测试摘要中。
