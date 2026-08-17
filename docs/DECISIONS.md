# Architecture Decisions

## ADR-001：Day 1 使用模块化单体

前后端分别保持单体部署，后端按 API、Connector、Metadata、Semantic、DB 分层。当前主链路不引入分布式微服务。

## ADR-002：第三方语义引擎必须经过 Adapter

业务模型、ORM 和 API DTO 保持 ChatBI 自有定义。`LocalSemanticEngine` 承担 Day 1 真实校验；`WrenSemanticAdapter` 只转换快照并明确暴露 runtime 可用性，不让业务代码依赖 Wren 内部类。

## ADR-003：元数据使用完整限定名

Schema、Table、Column 使用 datasource、schema、table、column 组合或稳定 ID，避免跨数据源和跨表同名字段碰撞，为后续 Schema Linking 提供可检索目录。

## ADR-004：模拟业务数据写入本机数据库且应用连接只读

本机 PostgreSQL/MySQL 保存两套同构经营数据，覆盖超过 12 个月。PostgreSQL 是主开发/主测试数据库，MySQL 是辅助兼容数据库。初始化管理员仅在交互式引导进程中用于建库授权；ChatBI 保存和使用 `chatbi_reader` 只读账号。Docker Compose 不创建数据库容器或数据卷。

## ADR-005：Day 1 不伪装 Wren runtime 集成

Wren runtime 未进入 Day 1 运行镜像。Adapter 的 capabilities 明确报告不可用，深度集成、MDL Schema 校验与 Semantic SQL 转换列为 Day 2 输入。

## ADR-006：前端不直接连接数据库

真实模拟数据必须通过 `Frontend → Backend API → Connector → Local Database` 使用。浏览器直连数据库会暴露凭据并绕过只读、审计和后续 SQL Guard，因此明确禁止。

## ADR-007：登录页不伪装生产认证

Day 1 登录页只承担进入 ChatBI 工作空间的高保真界面与前端演示路由。表单通过原生必填校验后进入默认“问数据”页，但不在前端伪造令牌、用户会话或 SSO/OIDC 成功状态；页面中的 SSO/OIDC 文案属于批准设计内容，不作为认证能力已完成的验收证据。真实认证接入必须由后端身份能力、会话安全与审计共同实现。
