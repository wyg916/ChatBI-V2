# ChatBI V2 V1 RC 候选验收报告

## 结论

`DAY_3_STATUS=PASS`，`DAY_3_GATE=PASS`，`V1_RC_STATUS=PASS`。产品闭环、Golden、安全、迁移、E2E、两次冷启动和 Git 发布门禁均已通过，RC Tag 为 `chatbi-v2-v1-rc1`。

## 产品 Gate

| Gate | 结果 | 证据 |
|---|---:|---|
| Ask → Chart → Narrative | PASS | Backend 85/85、Chart tests 19/19 |
| Answer → Dashboard | PASS | Day 3 E2E-09～11 |
| Evaluation → Golden20 | PASS | SQL/Result/Semantic 20/20 |
| MySQL compatibility | PASS | Execution/Result 5/5 |
| SQL safety | PASS | Dangerous SQL 38/38、真实写入 0 |
| UI14 / 三视口 | PASS | 14/14 x 3，运行时错误与异常 HTTP 0 |
| Migration | PASS | 单 head、upgrade/base/upgrade |
| Secret Scan | PASS | 匹配文件 0 |
| 两次冷启动 | PASS | 两次均从 Compose 完全停止状态构建并启动，Backend/Frontend healthy |
| Commit/Merge/Push/Tag | PASS | main 与 origin/main 同步；annotated `chatbi-v2-v1-rc1` 指向发布提交 |

## Golden 硬门槛

- Count：20（要求 ≥20）
- SQL Execution：100%（要求 ≥95%）
- Result Value：100%（要求 ≥90%）
- Dangerous SQL Block：100%（要求 100%）
- Manifest SHA-256：`d40bb690a4208240ecf347abe47e045cd74c8eb89b9162d5d53890ecf24bc282`

## 发布判定

满足 Day 3 / V1 RC 的全部硬门槛，允许发布 annotated Tag `chatbi-v2-v1-rc1` 并进入 Day 4 Quality Hardening。

## 执行说明

Playwright 首次并行探测为 33/34：并发 Schema Sync 与查询共享同一本机元数据目录时，单个 Join 查询在瞬间空 allowlist 上被安全拒绝。该查询随后独立通过；按共享状态套件的发布方式使用单 worker 重跑全部 34 项并全部通过，Day 3 19/19、必选 E2E-01～15 与 UI14 三视口均 PASS。此并发测试隔离问题保留为 Day 4 非阻塞加固项。
