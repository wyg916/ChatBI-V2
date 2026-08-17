# Day 4 Evidence

本目录只保存脱敏、可复现的 Day 4 质量证据，不覆盖 `docs/evidence/day3/` 的 V1 RC 历史证据。

- `golden-50-results.json`：冻结 Manifest、原 Golden 20 回归、PostgreSQL 50 条与 MySQL 10 条逐 Case 结果。
- `parallel-e2e-summary.json`：共享状态根因、隔离策略和 5 workers 三轮结果。
- `semantic-version-summary.json`：V1/V2 Publish 与 V1→V3 Rollback 证据摘要。
- `rbac-audit-summary.json`：ADMIN/ANALYST 权限、授权资源、拒绝路径和审计覆盖摘要。
- `quality-gate-summary.json`：Backend、Frontend、Serial E2E、Migration、Security、UI14 与 bundle 汇总。
- `one-click-launcher.json`：两次完整停止后的 Docker 一键启动结果。
- `model-provider-live-smoke.json` / `model-provider-test-summary.json`：先前已完成的三家 Provider 脱敏证据；本轮未重复调用或暴露 Key。

最终 Day 4 结论以 `docs/status/DAY4_STATUS.md` 和远端 Git/Tag 实时核验为准。
