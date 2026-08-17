# Model Provider 配置

ChatBI V2 通过项目自有 `ModelProviderAdapter` 接入外部模型。当前命名 Provider 均使用 OpenAI Chat Completions 兼容协议，API Key 只从 Backend 进程环境读取，不写入元数据库，也不返回给浏览器。

| Provider | `CHATBI_MODEL_PROVIDER` | 默认 Base URL | 默认 Model ID | 认证 |
| --- | --- | --- | --- | --- |
| Moonshot Kimi | `kimi` | `https://api.moonshot.cn/v1` | `kimi-k2.6` | Bearer |
| Xiaomi MiMo | `mimo` | `https://api.xiaomimimo.com/v1` | `mimo-v2.5` | `api-key` |
| DeepSeek | `deepseek` | `https://api.deepseek.com` | `deepseek-v4-flash` | Bearer |
| 本地确定性语义运行时 | `deterministic` | 无 | `deterministic-semantic-v1` | 无 |

官方接口说明：

- Kimi：`https://platform.kimi.com/docs/api/overview`
- MiMo：`https://mimo.mi.com/docs/zh-CN/quick-start/summary/first-api-call`
- DeepSeek：`https://api-docs.deepseek.com/zh-cn/`

## 本机配置

在 Git 忽略的根目录 `.env` 中设置对应变量：

```dotenv
CHATBI_KIMI_API_KEY=
CHATBI_MIMO_API_KEY=
CHATBI_DEEPSEEK_API_KEY=
```

默认仍使用：

```dotenv
CHATBI_MODEL_PROVIDER=deterministic
```

需要把 NL2SQL 路由切到某一家时，只把该值改为 `kimi`、`mimo` 或 `deepseek`，随后重启 Backend。未配置或配置不完整时，路由安全回退到本地确定性语义运行时。

## 安全边界

- 前端只调用 `GET /api/v1/model-providers` 获取配置状态、模型 ID 和当前路由；响应固定声明 `secrets_exposed=false`。
- 浏览器没有 API Key 输入、保存或回显能力。
- 日志、测试证据和 Git 跟踪文件不得包含密钥值。
- Kimi、MiMo、DeepSeek 的参数差异由 Adapter 封装；三家均关闭思考模式并要求 JSON Object，返回内容继续经过 `SQLPlan` 强校验和 SQL Guard。
- 外部 Provider 不绕过只读账号、SQL AST Guard、Result Oracle、查询超时或审计。

## 验证

Provider 合约测试使用 `httpx.MockTransport` 验证 URL、认证头、模型标识、JSON 模式和供应商专属 Token 参数，不产生外部费用。Live smoke 只验证模型列表与最小 JSON Chat Completions；证据仅记录状态码和布尔结果。
