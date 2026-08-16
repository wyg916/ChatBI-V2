# ChatBI V2 三至五天开发计划

## Day 1：立项与底座

- 建立独立仓库和 AGENTS.md。
- 创建 Web/API/Packages/Docs 目录。
- 接入本机 PostgreSQL 元数据库、迁移和模拟业务 Schema；数据库数据不放入 Docker。
- 以 PostgreSQL 为主、MySQL 为辅完成数据源连接测试、Schema 同步和字段浏览。
- 按真实经营关系生成至少 12 个月模拟数据写入本机两套数据库，前端仅通过 Backend API 使用这些数据。
- 完成最小 Semantic Model 数据结构和发布状态。
- 完成登录、问数据空态、数据源列表/详情、语义模型列表的页面骨架。
- Gate：本机数据库初始化、一键应用启动、两种数据源连接、Schema 同步、前后端构建全部 PASS。

## Day 2：问数主链路

- Context Builder：Schema、指标、维度、术语和 Verified SQL 检索。
- NL2SQL Router 与模型网关。
- SQL AST Guard、超时、行数限制、审计和错误恢复。
- Query Executor 与 Result Oracle V1。
- 完成问数据结果页、SQL 依据、反馈和答案保存。
- Gate：至少 20 条 Golden Question；SQL 执行成功率不低于 95%，结果准确率不低于 90%。

## Day 3：产品闭环与 V1 发布

- Chart Planner、Narrative、推荐追问。
- 答案库、看板保存和评测中心总览。
- 完成核心 E2E、连续两次一键启动、README、部署文档和 V1 Tag。
- Gate：主链路完整，核心页面无阻断错误，Golden Set、Backend、Frontend、E2E 全部 PASS。

## Day 4：质量加固（兜底）

- 语义模型编辑器、第二方言、细粒度权限、审计和错误分类。
- Golden Set 扩展到 50 条；结果准确率提升到不低于 95%。
- 修复性能、兼容性和 UI 细节。

## Day 5：最终发布收口

- 全量回归、许可证清单、Final Manifest、Release Notes、Rollback。
- 验证冷启动、备份恢复、安装流程和示例演示脚本。
- 生成 Final Tag 并冻结 V1。
