# 评测数据集配置

评测引擎读取 `CHATBI_EVALUATION_MANIFEST_PATH` 指向的服务端 JSON 文件。使用 Compose override 将该文件只读挂载到 Backend，再配置容器内路径。未配置时返回明确的配置错误，已有评测记录仍可查看。

顶层字段：`frozen` 为 true；`cases` 为非空数组；`manifest_sha256` 为校验和。每个 case 必须有唯一字符串 `id`、字符串 `question`、字符串 `expected_sql` 和对象数组 `expected_result`。可选语义预期包括 `expected_metrics`、`expected_dimensions`、`expected_filters`、`expected_entities` 和 `expected_time_range`。

计算校验和时将 `manifest_sha256` 置为 null，再使用 Python `json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))` 编码 UTF-8 并计算 SHA-256。

数据集应对应当前工作区已发布的语义模型和只读数据源。文件由部署者审核与维护，禁止包含凭据。评测仍经过正常查询、安全与结果校验链路。
