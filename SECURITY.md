# Security Policy

## 支持范围

当前安全修复面向最新的 V1 正式发布分支与最新发布 Tag。更早的开发提交和 RC Tag 仅作为历史基线，不承诺独立维护。

## 私密报告漏洞

请使用 GitHub 仓库的 **Security → Report a vulnerability** 私密通道报告问题。不要在公开 Issue 中提交 API Key、数据库口令、SQL 结果、企业数据、访问 Token、私有证书或可直接利用的漏洞细节。

报告建议包含：受影响版本或 commit、可复现步骤与最小脱敏请求、影响范围、已验证的缓解方式，以及是否涉及凭据或真实业务数据。

## 安全边界

- 浏览器只访问 Backend API，不直连 PostgreSQL/MySQL。
- 数据源账号应为最小权限只读账号。
- 生成 SQL 只允许一条 `SELECT` 或 `WITH ... SELECT`，并经过 AST 授权、超时和行数限制。
- 外部模型和可选 RAG/编排密钥只允许来自 Backend Secret/环境变量。
- 普通问数必须经过 SQL Guard、Query Executor 与 Result Oracle；可选编排不得绕过这些组件。
- 会话 Token 只以 HttpOnly Cookie 或显式 Bearer 方式进入 Backend，数据库仅保存哈希；匿名、伪造、过期、撤销和越权请求必须失败。
- RAG 在检索前验证签名身份并执行 Workspace/场景 ACL；注入文档、无授权证据或伪造 Citation 必须 fail closed。
- 文件分析不执行用户或模型生成的 Python/Shell，不访问宿主机、数据库/Provider 凭据或不受限网络。

公开前请撤销测试凭据并对日志、截图、trace 和数据库导出进行脱敏。V1.1.0 主动攻击范围与结果字段见 `docs/SECURITY_REPORT.md`；依赖和许可证见 `docs/OPEN_SOURCE_LICENSE_AUDIT.md` 与 `docs/sbom/`。
