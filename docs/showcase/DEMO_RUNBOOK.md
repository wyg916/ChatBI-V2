# 本地 Demo 操作手册

## 唯一正式目录

从当前 clone 的仓库根目录运行以下命令；本文不绑定任何个人机器路径：

```text
<project-root>
```

其他历史 worktree/clone 不作为 Demo 入口。正式 Release 证据、Git bundle 安全备份和第三方参考源码不是可运行项目副本。

## 录屏前 5 分钟

1. 启动 Docker Desktop，并确认本机 PostgreSQL 5432、MySQL 3306 正在运行。
2. 在项目根目录执行：

   ```powershell
   .\一键重置-ChatBI-V2-演示数据.cmd
   ```

3. 等待浏览器打开 <http://127.0.0.1:15173/>。
   Showcase 会强制将 Frontend、Backend 与 RAG 的发布端口绑定到 `127.0.0.1`；固定演示账号不得用于任何对外网卡或生产部署。
4. 使用以下账号登录：

   ```text
   账号：admin@chatbi.local
   密码：ChatBI-Showcase-2026!
   ```

5. 浏览器保持 100% 缩放，推荐分辨率 1440×900 或 1920×1080。

## 启动、状态、停止、重置

```powershell
Set-Location -LiteralPath '<project-root>'

# 启动；默认 ProviderMode Auto，已有镜像时直接复用，没有镜像时自动构建
.\scripts\showcase.ps1 -Action Start

# 只检查状态，不打开浏览器
.\scripts\showcase.ps1 -Action Status -NoOpen

# 停止并删除本项目容器/网络，不删除本机数据库
.\scripts\showcase.ps1 -Action Stop

# 重建 ChatBI 元数据、演示账号、会话、答案/看板/评测种子，然后重新启动
.\scripts\showcase.ps1 -Action Reset

# 代码或依赖有变更时强制重建镜像
.\scripts\showcase.ps1 -Action Start -Rebuild
```

## 模型运行模式

- `Auto`（根目录一键启动默认）：只要 `.env` 或当前进程已配置 MiMo、DeepSeek、Kimi 中任一有效凭据，就使用 `quality` 能力路由，关闭 ChatBI 测试付费门禁，并取消三家的内部估算费用、Kimi 准入、候选数和重试数裁剪；三家均可在“系统设置 → 模型服务”中启用和真实测试。
- `Live`：要求至少配置一家 Provider，否则启动直接失败，适合强制验证外部模型链路。
- `Deterministic`：不发起外部付费请求，适合可重复录屏和免费回归。

```powershell
.\scripts\showcase.ps1 -Action Start -ProviderMode Live -NoOpen
.\scripts\showcase.ps1 -Action Start -ProviderMode Deterministic -NoOpen
```

启动器不会覆盖模型服务页面中的管理员启停选择。`Auto`/`Live` 可能产生真实供应商费用；Provider 账号自身的余额、配额、并发、限流和网络限制仍然有效，SQL/回答/Agent 安全门禁也不会被关闭。

双击入口与上述命令等价：

- `一键启动-ChatBI-V2.cmd`
- `一键停止-ChatBI-V2.cmd`
- `一键重置-ChatBI-V2-演示数据.cmd`

## 地址

| 用途 | 地址 |
|---|---|
| 产品 | <http://127.0.0.1:15173/> |
| Backend 健康 | <http://127.0.0.1:18080/health> |
| API 版本 | <http://127.0.0.1:18080/api/v1/version> |
| Swagger | <http://127.0.0.1:18080/docs> |
| RAG Runtime 健康 | <http://127.0.0.1:18081/health> |

## 稳定数据口径

- PostgreSQL 主数据：`chatbi_v2.demo_business`。
- MySQL 兼容数据：`chatbi_demo_business`。
- 固定 5 个区域、60 个客户、5 个产品、10 个站点、1095 笔订单、730 个充电会话、365×5 条日 KPI。
- 种子基准日固定为 `2026-08-17`，不会随录屏当天改变。
- 业务账号为只读；Showcase Reset 不重写业务 Schema，只重建可变的 ChatBI 元数据。
- 如果业务 Schema 被手工破坏，运行 `.\scripts\bootstrap-local-databases.ps1 -ResetDemoData`；该恢复需要再次输入本机数据库管理员口令。

## 推荐提问

正式主问题：

```text
2026年按地区按月统计已支付订单收入趋势
```

补充问题：

```text
按地区统计收入贡献度
按品类统计利润率
统计全部订单收入、成本和利润
说明收入与退款的业务口径，并给出可核验引用
```

危险 SQL 演示只在产品提供的安全测试入口或评测用例中使用：

```sql
DELETE FROM demo_business.orders;
```

应展示“数据库访问前拒绝”，不要在数据库客户端执行。

## 常见故障

- **5432/3306 不可达**：启动本机 PostgreSQL/MySQL 服务；不要临时加数据库 Docker 容器。
- **缺少 `.env`**：执行一次 `scripts/bootstrap-local-databases.ps1`；不要把 `.env` 提交到 Git。
- **端口占用**：先运行 `scripts/showcase.ps1 -Action Stop`，再确认占用进程是否属于其他项目。
- **镜像过期**：运行 `scripts/showcase.ps1 -Action Start -Rebuild`。
- **登录失败**：运行一键重置；启动器会轮换到本文档账号并撤销旧会话。
- **页面仍是旧资源**：`Ctrl+F5` 强制刷新；不要盲目删除本机数据库。

## 收尾

录像完成后执行：

```powershell
.\一键停止-ChatBI-V2.cmd
```

停止不会删除 PostgreSQL/MySQL 数据、`.env` 或 Git 文件。
