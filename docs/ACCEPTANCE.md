# ChatBI V2 验收标准

V1.0.0 Final Release 的本次执行报告见 [`docs/status/DAY5_STATUS.md`](status/DAY5_STATUS.md) 与 [`docs/releases/V1_FINAL_MANIFEST.md`](releases/V1_FINAL_MANIFEST.md)。只有 Final Manifest 中的功能、正确性、安全、迁移、冷启动、两次正式启动、回滚和 Git 发布 Gate 全部通过，才允许创建 annotated Final Tag。Day 3 RC 历史报告保留在 [`docs/ACCEPTANCE_REPORT_V1_RC.md`](ACCEPTANCE_REPORT_V1_RC.md)。

## 产品主链路

- 数据源连接、Schema 同步、语义模型发布、自然语言问数、SQL 校验、查询执行、结果验证、图表、洞察、答案保存、看板和评测全部可用。

## 安全

- 只读账号、单语句、SELECT/CTE allowlist、超时、行数限制、敏感字段控制和完整审计。
- DDL、DML、多语句、系统表越权、文件访问和外部程序全部被拒绝。

## 质量

- Day 3：Golden 20；SQL 执行成功率 ≥95%；结果准确率 ≥90%。
- Day 5：Golden 50；SQL 执行成功率 ≥98%；结果准确率 ≥95%。
- Backend、Frontend、E2E、Migration、Docker 连续启动全部 PASS。
- 浏览器 console error、page error、blocking request failure 为 0。
- Docker Compose 中数据库服务数为 0；项目数据实际存在本机 PostgreSQL/MySQL。
- PostgreSQL 主验证链必须 PASS；MySQL 辅助连接与 Schema 同步必须 PASS。

## UI

- 1440×900 为设计基准；1366×768 与 1920×1080 可用。
- 六个一级模块导航清楚；问数据为默认首页。
- SQL 和技术细节折叠展示；业务结论优先。

## 工程

- 工作树 clean；主仓库唯一；无重复 clone、长期 worktree 和未说明 stash。
- 文档、迁移、测试、许可证和一键启动脚本齐全。
- 前端只能通过 Backend API 访问数据库；任何前端直连数据库或暴露数据库凭据均为 FAIL。
