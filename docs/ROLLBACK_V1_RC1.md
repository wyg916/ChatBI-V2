# ChatBI V2 V1 RC1 回滚说明

当前 RC1 由 annotated Tag `chatbi-v2-v1-rc1` 标识；以下步骤用于发布后的受控回滚。

1. 停止 Backend/Frontend 并备份 ChatBI 元数据库。
2. 记录当前镜像、Commit、Alembic revision 和冻结 Manifest SHA-256。
3. 将应用代码切换到已验证的前一 Tag `chatbi-v2-ui14-baseline-20260817` 或 Day 2 Tag。
4. 若必须回退数据库结构，在确认已备份 AnswerVersion、DashboardCard、EvaluationRun/CaseResult 后，从后端环境执行 `alembic downgrade 20260817_0004`。该操作会移除 Day 3 持久化字段/表，存在数据丢失风险，不得无备份执行。
5. 从停止状态启动两次并重新验证 Day 2 Golden20、MySQL 5 条、危险 SQL 38 条和三视口 UI。
6. 保留失败运行、日志、查询签名和回滚验证证据，不修改冻结 Expected Result。

本机业务 PostgreSQL/MySQL 数据不得通过 Docker volume 删除；回滚只操作明确的应用版本和已备份元数据库迁移。
