# v2.1 Integration Input Matrix

本矩阵只登记最终主控已正式收到并核验的输入。未提供的 SHA、Tree SHA、状态和 READY 值保持为空，禁止根据本地分支名、工作树或口头进度推断。

## P0 Phase 2

```text
P0_PHASE2
STATUS=PASS
SHA=6cdbf12f6c2e8494afe21262fd092795c4f784c3
TREE_SHA=c96b4da813b17b8ab2e0dee4a33a01b114a6f644
READY=YES
```

## B Eval / Golden / Feedback

```text
B_EVAL_GOLDEN_FEEDBACK
STATUS=READY
CANONICAL_SHA=5690d9d0ec04be0b21dfd642e0d8802ae1d5142a
TREE_SHA=a805ccfa23db8231bca894bfee8a8856a14de347
SOURCE=REMOTE
CI=PASS
INTEGRATION_METHOD=MERGE
BLOCKERS=NONE
```

## C Data Workspace

```text
C_DATA_WORKSPACE
STATUS=
SHA=
READY=
```

## E Data 10M / Performance

```text
E_DATA10M_PERFORMANCE
STATUS=
SHA=
READY=
```

## A Semantic

```text
A_SEMANTIC
STATUS=
SHA=
READY=
```

## D RAG / Agent / File

```text
D_RAG_AGENT_FILE
STATUS=
SHA=
READY=
```

## Required intake package for each workflow

最终主控开始集成前，B/C/E/A/D 每项都必须提供：

- 正式状态：PASS、PARTIAL 或 BLOCKED。
- Canonical commit SHA；B 还必须提供 Tree SHA，其余输入建议同时提供。
- 来源分支或只读 ref，不以工作树目录作为身份。
- `git status --short` 为 clean 的证据。
- 相对 Phase 2 的 changed-files 清单和 `--stat`。
- 与 [PHASE2_FROZEN_FILES.json](PHASE2_FROZEN_FILES.json) 的交集及 HIGH_CONFLICT 说明。
- 已执行测试、真实数字、未执行项和 blocker。
- 第三方代码、许可证、版本和 `THIRD_PARTY_NOTICES.md` 影响。
- 数据库迁移 head、回滚路径和对本机 PostgreSQL/MySQL 的影响。
- 明确声明未修改 `origin/main`、未创建 Final Tag。

## Current readiness

```text
B_INPUT_STATUS=READY
C_INPUT_STATUS=NOT_PROVIDED
E_INPUT_STATUS=NOT_PROVIDED
A_INPUT_STATUS=NOT_PROVIDED
D_INPUT_STATUS=NOT_PROVIDED
READY_TO_MERGE=NO
```
