# Day 1 开源参考内部映射

本文件记录 Day 1 对冻结参考仓库的只读研究结果。没有复制第三方源码、资源或品牌。

## ChatBI 自有语义模型

- `SemanticModel` 独立保存数据源、状态和版本；发布产生可追踪版本。
- `Entity` 绑定源表、主键和默认时间维度。
- `Metric` 保存表达式、聚合、过滤和归属实体。
- `Dimension` 保存源字段、类型与语义类型。
- `Relationship` 使用结构化左右实体、连接类型、基数和连接键，避免开放任意 SQL 条件。
- `BusinessTerm` 通过术语、同义词、定义和映射对象建立业务口径。
- 元数据使用 `datasource + schema + table + column` 完整限定名，避免跨表同名字段碰撞。

## SemanticEngine 边界

业务代码只依赖 ChatBI 的 `SemanticEngine` 接口和 DTO。Day 1 的 `LocalSemanticEngine` 提供真实验证；
`WrenSemanticAdapter` 只负责将 ChatBI 语义快照转换为 Wren Manifest 边界，并明确报告 runtime 是否可用。
ORM、API Schema 和业务服务不得导入 Wren 内部类。

## 参考实现吸收范围

- WrenAI：研究 MDL Model、Column、Relationship、Cube 与 Python runtime 接口，保留 Adapter 隔离。
- SuperSonic：仅吸收 Metric/Dimension/Identifier 分层和 Schema Mapper 证据化匹配思想，不复制实现。
- OpenChatBI：参考 Inspector 元数据采集、Catalog Store 和候选表缩减输入，Day 1 不进入完整 NL2SQL。

## Day 2 输入

- Wren runtime 容器可用性、MDL JSON Schema 与跨对象校验。
- PostgreSQL/MySQL 类型映射、复合键、派生指标依赖和循环检测。
- Schema Mapper 多路召回、FQN 去碰撞、候选表白名单与证据化排名。
- SQL Guard、只读限制、超时、行数限制和 Result Oracle。

## 已检查路径

- `WrenAI/core/wren-mdl/mdl.schema.json`
- `WrenAI/core/wren-core-base/src/mdl/`
- `WrenAI/core/wren-core-py/src/`
- `SuperSonic/headless/api/` 中 semantic schema/model/metric/dimension DTO
- `SuperSonic/headless/chat/` 中 Schema Mapper 接口
- `OpenChatBI/openchatbi/catalog/`
- `OpenChatBI/openchatbi/text2sql/schema_linking.py`
