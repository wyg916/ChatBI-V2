# 认证与一键启动运行审计

采集基线：`23c6be78dd0c83dd81c5b4559ddab9dc77ff6fbd`

## 现场结论

### 后端绕过

`backend/app/core/access.py:get_principal` 在缺少 `X-ChatBI-Actor` 时会合成 `admin@chatbi.local` / `ADMIN` Principal。权限依赖存在，但其身份源默认信任匿名请求，因此所有依赖该 Principal 的受保护接口均可匿名通过。现场已复现 `/datasources` 与 `/security/overview` 返回 200。

`X-ChatBI-Actor` 只是可伪造请求头，不是认证凭据，不能继续作为正式身份机制。

### 前端绕过

- 登录表单只调用 `navigate('/')`，没有向后端验证账号密码或建立服务端会话。
- 受保护路由直接挂载 `AppShell`，没有统一认证状态检查。
- API client 不携带 HttpOnly 会话 Cookie，也没有统一处理 401。
- 侧栏用户信息为固定展示文案，不来自当前会话。

### 一键启动

`一键启动-ChatBI-V2.cmd`、`scripts/launch.ps1` 与 `scripts/start.ps1` 没有生成 Token、写 localStorage、拼接 Token URL 或创建匿名用户。启动器只启动服务、检查健康、运行验证并打开普通根 URL。`ONE_CLICK_AUTO_LOGIN` 的根因不在启动脚本，而在应用匿名管理员回退和无守卫路由。

## 修复要求

- 使用后端生成的高熵不透明会话 Token；数据库只保存 Token 哈希。
- 浏览器只使用 HttpOnly、SameSite Cookie；不得把 Token 写入 localStorage/sessionStorage/URL。
- `/auth/login` 验证密码哈希，`/auth/me` 恢复会话，`/auth/logout` 立即撤销服务端会话。
- 所有受保护 API 从同一认证依赖取得用户与 Workspace；缺失/过期/撤销会话返回 401，跨 Workspace 返回 403。
- 前端统一路由守卫只改善交互；后端鉴权继续作为真实安全边界。
- 启动器保持纯启动职责。
