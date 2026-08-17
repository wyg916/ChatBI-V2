# ChatBI V1.0.0 Rollback

## 基线

- Final Tag：`chatbi-v2-v1.0.0`
- Previous RC SHA：`b0616f653cdabcd45a9255707442004948aaed7b`
- Day 4 safe SHA：`d70125f6172dd170c419110fd75d47e87a7f121a`
- Day 4 migration：`20260817_0006`
- V1 final migration：`20260817_0007`

## 回滚前备份

停止写入元数据的管理操作，并使用部署环境自己的 Secret 管理方式执行 PostgreSQL 备份。不要把密码写入命令历史、文档或仓库。

```powershell
pg_dump --format=custom --file chatbi_v1_before_rollback.dump chatbi_v2
```

演示业务数据位于本机 PostgreSQL `demo_business` 与 MySQL `chatbi_demo_business`。它们不在 Docker volume 中；如需恢复，应使用数据库平台的备份/恢复流程，不得以 `docker compose down -v` 代替。

## 代码与迁移回滚

1. 关闭可选路径：`CHATBI_RAG_MODE=off`、`CHATBI_AGENT_MODE=off`。
2. 停止应用：`.\scripts\stop.ps1`。
3. 部署 Day 4 safe SHA 或已保留的 Day 4 镜像。
4. 确认可选路径为 off 后，执行 `.\backend\.venv\Scripts\python.exe -m alembic downgrade 20260817_0006`。
5. 启动 Day 4 版本并执行 Health、数据源连接、Ask、Result Oracle 和 Golden 50。

## 恢复 Final Candidate

```powershell
cd backend
.\.venv\Scripts\python.exe -m alembic upgrade 20260817_0007
cd ..
.\scripts\start.ps1
.\scripts\verify.ps1
```

随后验证 PostgreSQL/MySQL READY、Ask `SUCCEEDED`、Oracle `PASSED`、Golden 50 PASS、Model Provider 密钥不回显以及工作树/Tag 与发布基线一致。

## 已执行模拟

Day 5 使用独立临时 PostgreSQL metadata schema 执行：Final `0007` → downgrade `0006` → Day 4 SHA 启动/Ask/Golden50 → upgrade `0007` → Final 启动/Ask/Golden50。临时 schema 和临时源码均在验证后删除，真实项目数据未被修改。证据见 `docs/evidence/day5/rollback-simulation.json`。
