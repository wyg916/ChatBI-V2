# 安装与运行

## 前置条件

- Docker Engine / Docker Desktop、Docker Compose 和 PowerShell。
- 可从容器访问的 PostgreSQL 元数据库与专用应用账号。容器访问宿主机数据库时使用 `host.docker.internal`。
- 业务数据源账号仅授予查询所需的只读权限。不要使用数据库超级管理员运行应用。

## 初始化

复制 `.env.example` 为 `.env`，填写 `CHATBI_DATABASE_URL`。确认数据库连接可用后执行：

```powershell
.\scripts\start.ps1
```

启动流程生成服务端随机凭据、构建镜像、执行迁移和工作区初始化，再检查服务。默认前端 `http://localhost:5173`，后端 `http://localhost:8000`。

管理员登录名为 `admin@chatbi.local`，密码为本机 `.env` 中的 `CHATBI_BOOTSTRAP_ADMIN_PASSWORD`；分析员对应 `analyst@chatbi.local` 与 `CHATBI_BOOTSTRAP_ANALYST_PASSWORD`。请妥善保管该文件，不要提交到 Git。

首次登录后在数据源页面添加自己的数据库，同步 Schema，建立并发布语义模型，再进入问数据。知识检索需配置组织自己的知识内容。评测需由部署者配置已批准的数据集，格式见 [评测配置](docs/deployment/EVALUATION.md)。

## 运维

```powershell
.\scripts\doctor.ps1
.\scripts\status.ps1
.\scripts\verify.ps1
.\scripts\stop.ps1
```

根目录的一键启动和停止命令调用相同的标准脚本。更多内容见 [配置](docs/deployment/CONFIGURATION.md)、[备份恢复](docs/deployment/BACKUP_RESTORE.md) 和 [故障排查](docs/deployment/TROUBLESHOOTING.md)。
