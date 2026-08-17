# 项目状态

## 2026-08-17

- Phase 0：PASS，GitHub 基线已建立。
- Day 1：基础工程、数据源、Schema Metadata、Semantic Layer MVP、14 个 UI 路由和一键启动已实现并通过本地门禁。
- 数据运行基线：本机 PostgreSQL 主、MySQL 辅；Docker 数据库服务与旧模拟数据卷均为 0。
- 当前范围保持 ChatBI-first；未进入 NL2SQL、Result Oracle、复杂 Dashboard、Agent、RAG 或长期 Memory。
- 详细证据与 Day 2 输入见 `docs/status/DAY1_STATUS.md`。
- 登录页已按 Figma 节点 `5:73` 与 `docs/ui/01_登录页.png` 完成高保真实现；Figma 光晕与开关资源已本地化，表单具备可访问标签、键盘焦点、记住登录交互，并在演示校验通过后进入“问数据”。
- 登录页专项验收：Vitest 2/2、Playwright E2E 1/1；1440×900、1366×768、1920×1080 三个目标视口均无页面级横向裁切，浏览器 console error/warn 为 0。
