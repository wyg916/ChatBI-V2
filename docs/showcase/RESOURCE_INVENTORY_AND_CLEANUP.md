# 资源盘点与清理记录

日期：2026-08-27～28（Asia/Shanghai）
任务：`JOB_SEARCH_SHOWCASE`

## 删除前门禁

- GitHub API 确认 `main` 为 `52db955fd67ebe592c289399a135528c13cb3e3d`。
- annotated tag `chatbi-v2-v1.3.0` 的 tag object 为 `0cba661b1c0834371a849dfe4e5822e9a93748cb`，peeled commit 为 `52db955…`。
- GitHub Release `ChatBI V2 v1.3.0` 已发布且非 draft/prerelease。
- 根仓库初始存在 20 个 tracked 生成产物修改与 `docs/plans/` 未跟踪文档。
- 所有 dirty 内容、全部 refs、本地独有 commit 和不可达 WIP commit 在删除前完成外部备份并校验。

安全备份：

```text
<external-safety-backup>
```

包含：

- `chatbi-v2-all-refs.bundle`：56 refs，`git bundle verify` 通过。
- `root-dirty-tracked.patch`：binary patch，反向 apply check 通过。
- `root-untracked-docs-plans.zip`：2 个文件，ZIP 条目验证通过。
- IBM 临时 checkout bundle 与 dirty patch。
- 两枚原不可达 WIP commit 的安全 refs：`758dd716…`、`028e22f…`。
- 并发出现的 Enterprise WIP：tracked patch、19 个 untracked 文件 ZIP，以及阶段性 `5af33ee`、`e316e7f`、`a359641`、`febc1df` bundle。并发任务最终停在 clean `656496a`（相对 main 6 个提交、远端分支不存在），删除 worktree 前重新生成完整历史 `enterprise-productization-final-656496a.bundle`；SHA-256 为 `D0A2D0BCDF546E6CFB3DE378C2308B5787055407725F1FE5C63A2E0A8976C00B`，`git bundle verify` 通过。
- Codex temp/tmp 中 58 个 IBM/回归日志、JSON、JUnit、脚本与 bundle 的复制清单；`MANIFEST.csv` SHA-256 为 `61BBD08D46DE51F7DEBC4329D8736E78A05A9A311E3CED71C8C69C902D843FA2`。
- 仓库内被忽略的 `tmp/phase3-edit` 临时快照（无 `.git`，14,771 文件、273,824,495 bytes）完整归档为 `workspace-tmp-phase3-edit.tar.gz`；归档 16,518 entries、77,622,288 bytes，SHA-256 为 `9E85246736CB01B40B1D2B85800FAB20F1C462587008C42018F3931A81B36D3E`，`tar -tzf` 校验通过后才删除源目录。

## 初始 Git 资源

- 1 个主仓库：`<project-root>`，当时位于历史 V1.2 分支且 dirty。
- 首轮 8 个历史 worktree 加 2 个后续并发 worktree；最终二次盘点的 8 个注册路径中 7 个 clean，`v1.3-next-enterprise-productization` 含 tracked/untracked WIP，先独立备份后才进入清理。
- 2 个 clean 的 Phase 6 审计 clone。
- 1 个未完成空 Release clone。
- 16 个本地分支，其中若干对 V1.3.0 存在独有提交；全部由 bundle 保存后才允许删除。
- stash：0。

## 初始 Docker 资源

- ChatBI 容器：15（10 个 running healthy、5 个 exited）。
- ChatBI image tags：103；unique image IDs：95。
- ChatBI volume：1（`chatbi-ibm-uv-cache`，不含数据库数据）。
- ChatBI network：9。
- PostgreSQL/MySQL 均为本机 Windows service，不属于待删 Docker 资源。

首轮清理后历史 ChatBI 容器、image tags、volume、network 均为 0；随后只允许由唯一正式目录重建 canonical `chatbi-v2` Compose 项目。

## 实际清理结果

- `git worktree list` 清理并 prune 后只保留主目录；最终 Enterprise worktree 在并发任务转为空闲、HEAD clean 且最新 bundle 验证通过后移除。
- 18 个本地历史/任务分支全部在 exact tip 可从全 refs bundle、Enterprise final bundle 或冻结 main/tag 恢复的前提下删除；本地只保留 `main`。远端分支未批量删除，避免把本机资源清理扩大为远端协作变更。
- 两个 Phase 6 audit clone、未完成 release clone、Enterprise Evidence 中 5 个 fresh clone 均在 clean/backup 检查后移除；Evidence 的 dump、manifest、日志和 source tar 保留。
- 仓库外的历史审计 venv/runtime 与旧 final-integration 链接目录已清理；个人机器绝对路径不在公开记录中保留。
- Codex `temp/tmp` 下 ChatBI 目录、根文件、IBM checkout/venv、DB probe、successor bundle 和 run artifact 在外部 Evidence 复制并生成哈希清单后移除。
- 仓库内历史 `tmp/phase3-edit` 在完整归档后移除；最终全仓 `node_modules`、`.venv`、`__pycache__`、`.pytest_cache`、`test-results`、`playwright-report` 目录匹配数为 0。
- 6 组旧 ChatBI Uvicorn（端口 `18003～18006、18155、18156`）共 12 个父/子 Python 进程停止，旧端口监听数为 0；正式 `15173/18080/18081` 不受影响。
- 正式本机 PostgreSQL/MySQL 服务、仓库外 Evidence、Release Baselines、第三方参考项目和 Safety Backup 均保留。
- 最终 Docker 只保留 canonical 5 个 healthy 容器、3 个 image tags、3 个 network、0 个 ChatBI volume；一次性测试镜像和 Enterprise image tags 已删除。

## 最终验证

- Backend：679 collected，672 passed、7 个条件性 skip、0 failed；测试在一次性带 Git 的 Backend 测试镜像中运行，生产镜像仍不安装 Git。
- Frontend：Vitest 15 files / 60 tests 全通过；Vite production build 994 modules 成功。
- Playwright：`day2-query-flow + day3-product-loop + day5-rag-multiagent` 共 45/45，通过数据主链、内容闭环、RAG、固定 Agent、SSE、安全拒绝和三视口检查。
- 本地 Reset：元数据 Schema 重建、Alembic、固定 seed、登录、Frontend→Backend 代理、RAG、五组匿名 401 门禁全部通过。
- Docker Compose：从完全停止状态连续启动 2/2，通过 5/5 healthy、登录和状态验收；最终保持运行态。

## 文件系统资源分类

保留：

- `<project-root>`：唯一正式可运行项目。
- `<external-evidence-root>`、`<external-release-baselines>`：正式证据/基线，不作为项目 clone。
- `<external-reference-root>`：第三方参考仓库集合，不是 ChatBI V2 clone。
- `<external-safety-backup>`：清理前可恢复备份，不是可运行项目。

清理范围：

- 历史 ChatBI worktree、重复 audit/release clone。
- 旧 root `.venv`、`backend/.venv`、`frontend/node_modules`、`dist`、Playwright/test-results、pytest 与 Python cache。
- 仓库外历史审计 venv/runtime 和临时 venv/cache/checkout。
- 清理前检测到的独有非缓存日志/文档先进入安全备份。

## 最终验收字段

现场验收：

```text
ONE_CANONICAL_LOCAL_PROJECT=YES
LOCAL_DEMO_READY=YES
ONE_CLICK_START_READY=YES
README_SHOWCASE_READY=YES
VIDEO_SCRIPT_READY=YES
INTERVIEW_TALK_TRACK_READY=YES
JOB_SHOWCASE_MAINTENANCE_MODE=YES
```

V1.3.0 tag 和 GitHub Release 不移动；main 上的 Showcase 变更属于 POST_RELEASE 提交。
