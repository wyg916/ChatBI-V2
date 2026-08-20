# ChatBI V2 V1.2.0 Release Notes

V1.2.0 是向后兼容的 MINOR 发布，在 V1.1.0 的可验证 ChatBI 主链路、受控 RAG 与受限 Multi-Agent 基础上，正式冻结新的 Chat-first 对话体验。

## 核心新增

- ChatGPT 风格单列对话界面，同时保留原紫色品牌体系和六个一级模块。
- 会话搜索、分组、重命名、删除、延迟创建和跨会话流隔离。
- 真实 canonical SSE Streaming、增量 Provider 输出、显式服务端停止生成、失败重试和持久化一致性。
- Enter 发送、Shift+Enter 换行、中文 IME 防误发、文件上传、拖拽附件、图片粘贴、上传进度与失败恢复。
- 自动滚动、用户上滚暂停跟随、回到最新消息。
- 默认关闭的右侧查询依据 Drawer，只展示 SQL、数据口径、公开阶段和校验结论。
- Answer Composer 与 Text/KPI/Chart/Table/Citation/Evidence/Artifact/Follow-up Message Parts。
- `VALUE`、`ZERO`、`NO_ROWS`、`NULL_VALUE`、`FAILED` 五态结果语义；0、无匹配记录、空值和失败不再互相混淆。
- Assistant 外层透明简化、真实 ECharts、复制回答和可审计重新生成。

## 保留并回归通过的能力

- NL2SQL、SQLGlot Guard、只读 Query Executor、Result Oracle。
- PostgreSQL 主路径、MySQL 兼容路径、Semantic Model 与 Verified Answer。
- 受控 RAG、固定五角色/六工具 Multi-Agent、Citation/Answer Guard。
- SQL、Chart、File QA、Image QA、RBAC、Workspace Isolation、多轮会话和持久化。
- 答案库、看板、评测中心、Data Workspace 与审计链。

## 安装与启动

首次安装按 `INSTALL.md` 初始化本机 PostgreSQL/MySQL。日常使用直接双击仓库根目录 `一键启动-ChatBI-V2.cmd`；命令行等价入口为 `scripts/start.ps1`，自动化无浏览器入口为 `scripts/launch.ps1 -NoOpen`。

## 兼容性与安全

- Docker Compose 只运行 Backend、RAG Runtime 和 Frontend，不创建数据库容器或数据库数据卷。
- 浏览器只访问 Backend API，不保存数据库凭据或模型密钥。
- V1.2.0 没有新增数据库迁移、第三方依赖或许可证范围；V1.2.0 SBOM 重新从发布容器和前端锁文件生成。
- 原始 Playwright HTML/trace/storageState/auth Cookie 不进入 Git；发布证据只保留脱敏文本、截图和哈希清单。

## 非阻塞 P2

- ECharts 独立懒加载 chunk 为 555.48 kB，仍触发 Vite 500 kB warning。
- “重新生成”按当前审计契约新增一条同文 user turn 和一条 assistant turn。
- Docker Desktop 冷启动可能受本机镜像与 Build Cache 体量影响；项目脚本不自动执行 prune。

## 发布身份

- Version：`V1.2.0`
- Annotated Tag：`chatbi-v2-v1.2.0`
- Release SHA：通过 `git rev-parse chatbi-v2-v1.2.0^{}` 解析，并必须与 local/tracking/remote `main` 一致。
