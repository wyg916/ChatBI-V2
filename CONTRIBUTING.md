# Contributing to ChatBI V2

感谢参与 ChatBI V2。贡献必须服务于核心链路：数据源、Schema、语义模型、受约束 NL2SQL、只读查询、结果验证、图表/洞察、答案/看板与评测。

## 开始之前

1. 阅读 `AGENTS.md`、`docs/PRODUCT_CHARTER.md`、`docs/ARCHITECTURE.md` 与 `docs/ACCEPTANCE.md`。
2. 从最新 `main` 创建短生命周期分支。
3. 不提交 `.env`、API Key、数据库口令、日志、数据库 dump、构建目录或测试缓存。
4. 第三方代码或资产进入仓库前，必须核验许可证并更新 `THIRD_PARTY_NOTICES.md`。

## 本地验证

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts\run_day4_golden.py

cd ..\frontend
npm ci
npm run typecheck
npm test -- --run
npm run build
npx playwright test --workers=1
```

涉及共享状态、迁移、语义发布或评测的变更还应执行 5-worker E2E。不得通过 retry、固定 sleep 或降低 worker 数量掩盖竞态。

## Pull Request 要求

- 说明问题、范围、数据/安全影响、验证结果和已知限制。
- 新迁移必须支持升级、降级和恢复升级。
- SQL 能力必须继续经过 SQL AST Guard、只读账号、超时、行数限制和 Result Oracle。
- 前端不得直连数据库或保存 Backend 密钥。
- 不新增通用 Agent、通用知识库、复杂长期记忆、预测平台或插件市场。

提交贡献即表示你有权按仓库 `LICENSE` 提供该贡献。
