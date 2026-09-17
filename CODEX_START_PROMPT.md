# Codex 首轮执行指令

请接管当前新 ChatBI V2 仓库。首先读取仓库根目录 `AGENTS.md` 及 `docs/` 下的产品章程、架构、三至五天计划和验收标准。

本轮只执行 Day 1，不开发 Day 2/Day 3 功能：

1. 核对 Git、目录、运行环境和可复用旧项目资产。
2. 建立独立 ChatBI V2 工程骨架与统一一键启动。
3. 实现元数据库、演示业务库、PostgreSQL/MySQL 数据源连接测试与 Schema 同步。
4. 实现最小 Semantic Model 数据结构和 API。
5. 完成登录、问数据空态、数据源列表/详情、语义模型列表的高保真页面骨架。
6. 编写并执行 Day 1 Backend、Frontend、Migration 和启动测试。
7. 更新 STATUS、DECISIONS 和 Day 1 证据。

严禁开发长期记忆、通用 RAG、Agent 平台、预测、告警或大型报表功能。若发现旧项目组件与新架构冲突，优先保留新 ChatBI Core 的独立性，只通过 Adapter 迁移真正可复用能力。

最终只汇报实际完成项、测试数字、Git 状态、阻断项和 Day 2 可执行输入。
