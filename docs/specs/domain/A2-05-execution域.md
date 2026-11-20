# A2-05 · 执行域（execution）

> 状态：**生效 v1.0（2026-11-14）**　总纲：[A2-01](A2-01-领域模型与动作模型.md)
> 用户词：**领取**（Claim）。本域是"管家替你干活"的核心：动作定义、执行记录、幂等。

## 1. 职责与边界

- 管：Action 定义、Run 生命周期、幂等键、时间预算、结果词汇的消费出口（Result）。
- 不管：何时触发（scheduling 域）、执行所需的凭据事实（accounts 域端口读取）、
  连接器怎么做（A2-02，适配器不做语义决策）。

## 2. 实体与不变量

```
Action = (kind, target, params)
  target = 应用 + 账号编址（多账号，A2-01 §2）
Run = id / action / account_id / idempotency_key / started_at / budget
  → Result(status ∈ 七字面量, kind 谓词, evidence[], repair_hint?)
```

不变量：
1. **幂等键 = (kind, account_id, 签到窗口)**——同键重复触发必须命中回放，
   绝不二次领取（继承旧系统已验证语义，测试钉死）
2. 时间预算超限 → 立即停止并如实上报 FAILED/部分证据，不静默截断
3. `dry_run=True` 只报告不领取；Connector 申报不支持 dry_run → 用例层拒绝，
   **绝不静默降级**（红线 5 的用例级落点）

## 3. 端口（execution/ports.py）

- `ProvisionPort`：capabilities() 如实申报（dry_run / 多账户 / 幂等窗口）+
  run(ProvisionRequest) → 结构化 RunResult（不返回退出码）
- `RunRepoPort`：Run 记录持久化与幂等回放查询
- `GatewayRoutesStore`（R4-G6，ADR-012 裁决 6）：网关路由表文件存储——
  load（缺失 = 空表合法初始态）/ save（整表替换 + 原子写）；校验**单源**在
  `gateway_routes.RouteTable.from_dict`（server 写入与网关装载共用，永不漂移）

## 3.1 路由表模型（execution/gateway_routes.py，R4-G6）

- `RouteRule` = (model, accounts: 有序元组)——**账户顺序即优先级**，失败转移
  由网关调用方按序重试（ADR-012 裁决 5，M1 精确匹配）
- 校验不变量：routes 数组必在；model/accounts 非空；模型重复 = 歧义配置显式
  拒绝（ValueError 逐条中文报错，红线 5）；`to_dict/from_dict` 对称往返
- 落点 = 数据根 `gateway-routes.json`（engine `gateway/routes_file.py` 实现
  端口，原子写防半截文件）；server 管理面写（PUT /gateway/routes）、网关
  进程只读装载（M1 启动时装载一次，变更重启生效）

## 3.2 网关上游解析（apps/gateway，ADR-033 后续）

- 解析顺序：`upstream_for(platform_code)` 静态适配器优先（连接器申报的推理通道，
  `upstream.register_upstream` 注册）；未注册时回落平台册 `origin=user` 的接入源。
- 接入源适配器 `provider_upstream.ProviderUpstream`：连接事实全部读平台册
  （`base_url/protocol/credential_kinds`），不复制配置；密钥走 vault 默认槽现取；
  `provider_url` 按协议拼端点（已带 `/chat/completions` 或 `/messages` 则原样使用）。
- 协议互译（`protocol_translate.py`）：OpenAI ↔ Anthropic 双向支持文本、system、
  工具调用/结果、`max_tokens`、temperature/top_p/stop、tool_choice、usage 与
  stop_reason；同协议直通不复制。图片/多模态、`n>1`、`top_k`、`thinking`、
  `response_format` 等无法无损映射的字段显式抛 `TranslationError`，由上游适配器
  按客户端协议回 400（请求形状问题）或 502（上游响应形状问题），不静默丢弃语义。
- `gemini` 未开工：forwarder 记 `skipped:provider_protocol_unsupported`，不猜形状。
- 凭据只支持 `api_key`/`token`（Bearer；anthropic 用 `x-api-key`）；
  其他 kind 记 `skipped:provider_credential_unsupported`，不拿 cookie 冒充 Bearer。
- 上游 4xx/5xx 仍以 `UpstreamReply` 原样回传，沿用既有转移规则（401/403 失效凭据、
  429/5xx 转下一候选）；connect/timeout 抛 `UpstreamFailure`。
- HTTP 客户端由网关 lifespan 建一个 `httpx.AsyncClient` 注入，关闭时统一 `aclose()`；
  测试经 `_transport_factory` 注入 MockTransport，不碰真网络。

## 4. 用例

| 用例 | 语义 |
|---|---|
| `execute_action` | 校验能力申报 → 幂等查询 → 时间预算内执行 → 结构化 Result + RUN_FINISHED 事件 |
| `manage_gateway_routes` | `replace(data)` 先校验后落盘（非法绝不写盘）；`current()` 只读装载 |

## 5. 事件联动

- Run 终态发 `RUN_FINISHED`（通知/台账/统计统一入口）；成功 = silent，
  `is_attention` 才可见（A2-01 §5）。

## 6. 禁止

- ❌ kind 枚举在 core 外扩展（新 kind 走 ADR 立项）
- ❌ 触发调度逻辑混入本域（属 scheduling）
- ❌ 适配器内维护结果映射表或解析日志文本定语义（端零映射红线 2）
