# ChatBI V2 V1 RC Candidate Manifest

```yaml
product: ChatBI V2
candidate_version: 1.0.0-rc1
release_status: V1_RC_PASS
base_commit: 15ae6cdc9e96cc391e5bbeafb35408172c80f835
delivery_branch: flex/day3-chart-insight-v1-rc
tag: chatbi-v2-v1-rc1
tag_type: annotated
release_branch: main
alembic_head: 20260817_0005
golden_count: 20
golden_sha256: d40bb690a4208240ecf347abe47e045cd74c8eb89b9162d5d53890ecf24bc282
backend_runtime: Python 3.11 / FastAPI / SQLAlchemy
frontend_runtime: React 18 / TypeScript 5.7 / Vite 6 / ECharts 6.1
metadata_database: local PostgreSQL
primary_datasource: local PostgreSQL read-only
compatibility_datasource: local MySQL read-only
compose_services: [backend, frontend]
compose_database_services: 0
compose_database_volumes: 0
p2_scope_added: 0
```

## Release Gate

功能、测试、Golden、安全、迁移、Secret Scan、两次冷启动、Git 远端同步和 annotated Tag Gate 均已通过。发布提交以 `chatbi-v2-v1-rc1^{}` 解析结果为准。
