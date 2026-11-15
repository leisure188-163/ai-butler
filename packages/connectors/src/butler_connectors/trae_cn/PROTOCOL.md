# PROTOCOL · Trae CN（trae_cn 连接器协议字典）

> 本文件是**逆向结论的归宿**（A0-01 §2.1）：端点 / 加密 / 幂等 / 业务码。
> 实现全新写在 `declarative/provision.run.yaml` + 共享声明式运行时；
> 行为验收 oracle = 旧仓库 `auto-signin-kit`（同输入同结果，A0-01 §2.2）。
> 每条结论附取证日期；**适配器代码里不允许出现本文没有的端点**。

## 1. 身份与凭据

| 项 | 事实 | 取证 |
|---|---|---|
| 产品 | Trae CN（字节跳动 AI IDE，桌面端 Electron） | 2026-10-21 |
| 凭据位置 | `%APPDATA%`（Win）/ `~/Library/Application Support/{Trae CN,Trae}`（mac，CN 区优先）/ `~/.config/{Trae CN,Trae}`（Linux）→ `User/globalStorage/storage.json` | 2026-10-21 |
| 认证信封键 | `iCubeAuthInfo://icube.cloudide`（值 = **base64 字符串**；解码后为 SS_AES 信封字节） | 2026-10-21 |
| 设备号 | 键名 `iCubeAuthInfo://icube-dc:<8-20 位纯数字>` 承载 Aha 数字设备号——**claim 必须发这种数字号**，发 UUID 形态的 `telemetry.devDeviceId` 会触发 9074 风控 | 2026-10-21 |
| 兜底键 | 信封键缺省时容对待任意 `iCubeAuthInfo://` 前缀键（不含 icube-dc:） | 2026-10-21 |
| 辅助字段 | `iCubeLastVersion`（客户端版本，UA 指纹观察项；未用于 M1 请求头——不发未取证的头） | 2026-10-21 |

### 1.1 SS_AES 信封（byteCrypto，与 DPAPI 无关、系统无关）

```
value(base64) ──b64decode──▶ raw bytes
raw = [116,99,5,16,0,0] ++ master(32B) ++ AES-CBC密文
盐    = GLE ⊕ ZLE            （两段 64B 常量，见 ssaes.py；从 byteCrypto.js 逆向）
派生  = sha512(sha512(master) ‖ salt)   → 前16B = key，次16B = iv（AES-128）
明文  = 前64B = sha512(body) 校验和 ++ body(JSON, UTF-8, PKCS7 填充)
body  = 登录态 JSON：{ "token": <Cloud-IDE-JWT>, ... }
```

- 校验和不符 / 头不符 / 填充不合法 → 显式拒绝（协议已变探测点）
- token 是标准 JWT：`exp` claim 即凭据有效期（入 vault.expires_at 用）

## 2. 端点族

| 端点 | 方法 | 说明 |
|---|---|---|
| `https://api.trae.cn/trae/api/v2/ug/checkin_credits/status` | POST | 窗口状态查询：`{"code":0,"checked_in":true|false,"credits":…,"extra_credits":…}` |
| `https://api.trae.cn/trae/api/v2/ug/checkin_credits/claim` | POST | 领取：body `{"req_source":1}`；**受理响应不回显领取结果**，以 status 复查为准 |

公共约定：

- 鉴权头 `Authorization: Cloud-IDE-JWT <token>`
- 区域头 `X-User-Region: cn`（与桌面端指纹对齐；缺省 UA/区域头为风控观察项）
- **claim 必带 `x-device-id: <Aha 数字设备号>`**，否则业务码 9004（2026-10-21 复核；status 不校验设备头）
- 客户端原进程还附 x-device-brand 等五件套——**M1 未发**（取证未证实缺它会拒绝；勿编造）

## 3. 业务码与结果翻译（ADR-004 方言 `trae_cn`）

| 原始码 | 语义 | → Status | 备注 |
|---|---|---|---|
| `0` | 成功 | （ok 约定值，非方言项） | status/claim 共用 |
| `1001` | 服务端无法认证（令牌失效） | NO_AUTH | 修复 = 桌面端重新登录后重新停靠 |
| `9004` | 请求缺设备头（我方缺陷） | FAILED | 修复 = 重新停靠（dock 会补 device_dn） |
| `9074` | 活动期限流 | PENDING | **可退避重试 30/60/120s**；耗尽如实 PENDING，不算失败 |
| 未知码 | 协议可能已变 | FAILED + PROTOCOL_CHANGED 事件 | ADR-004 机制兜底 |

## 4. 幂等与窗口

- **claim 服务端幂等**：同窗口重复领取安全（重复触发不产生副作用）
- 以 status 复核为权威：`checked_in=true` 即本窗口已领（`did_checked_in` 语义）
- 领取窗口：积分每日 **00:00**（本机墙钟）结算；**签到日 ≠ 自然日**——
  00:00 前发起的领取属于前一日业务窗（core `claim_window` 单源）
- 引擎幂等键 = `(provision.run, account_id, 窗口)`：status 显示已领 → ALREADY（回放语义合一）

## 5. 行为对照验收

> **2026-11-11 Windows 真机验收（oracle = auto-signin-kit `client_signin run --app trae_cn`）**：
> dock 成功（凭据解锁 + device_dn 提取）→ 手动补给 CLAIMED（积分入账）→
> 同窗口二触发回放同 Run id（台账单条）→ oracle 对同账号报 ALREADY
> （今日已签到 100 Credits，token_expires_at 与新系统 vault.expires_at 一致）。
> 验收即抓三 bug：paths 宏展开缺 return（dock 全落空）、create_run 漏 import
> timedelta、未接入 target 裸 KeyError 500（应 404）——oracle 价值实证。

| 场景 | 期望 | 结果 |
|---|---|---|
| 已领过窗口内再触发 | ALREADY（不重复领取） | ✅ 新系统台账回放；oracle ALREADY |
| 令牌过期 | NO_AUTH + 待处理清单可见修复提示 | ⚪ 未自然发生（exp 2026-11-17）；离线 mock 覆盖，到期扫描 11-14 起预警 |
| claim 9074 | 退避后成功 → CLAIMED；耗尽 → PENDING | ⚪ 未自然发生；离线 mock 覆盖（test_decl_runtime） |
| 同窗口双触发（调度 + 手动） | 第二次回放首次台账记录 | ✅ 同 Run id |
| mac/Windows 双端停靠 | 凭据均可解锁且 x-device-id 正确 | ✅ Windows 侧；发错设备头即 9004，领取成功反证正确 |

## 6. 已知风险与观察项

- UA / 五件套指纹：未带头有 9074 观察记录；若行为验收出现，把头补进
  声明式 `dynamic_headers`（改 YAML 不改代码——机制设计目标）
- Linux 数据目录按惯例推定（`~/.config`），无取证——候选路径更长就用它
- `req_source: 1` 的其他取值语义未取证（保持 1，与桌面端对齐）

## 7. 用量取证（2026-11-12，M2 真机只读 spike，客户端 2.3.102035 / Windows）

> 01-M2-用量取证清单 §2 四项全落；只读取证（storage.json/state.vscdb 只读打开，
> API 试探最小头一次），token/凭据未进任何记录。

### 7.1 API 用量接口（主通道，鉴权复用 M1 凭据链验证通过）

`POST https://api.trae.cn/trae/api/v2/pay/ide_user_ent_usage`，Cloud-IDE-JWT 头，
body `{"require_usage": true, "req_source": 1}`：

- `req_source` 是**数字枚举**（TS enum xYe）：OfficialSite=0 / IDE=1 / Lite=2 /
  SoloWeb=3…——传字符串 "IDE" 得 400 Bad Request（首探踩坑实证）
- 响应 `usage_summary{consumed_amount, consumption_ratio, total_amount}`：
  **聚合用量**（已用/比例/总额度）
- 响应 `user_entitlement_pack_list`：**29 包分账本**（逐包面额/余量/过期日）；
  签到包 **31 天滚动过期、按最早过期优先消耗**；月度登录包 500/月

### 7.2 本地数据源

- `%APPDATA%\Trae CN\User\globalStorage\storage.json`：SS_AES 信封键（M1 凭据链）
  + `iCubeServerData` entitlementInfo 旁证
- `state.vscdb` ItemTable（347 键，只读拷副本）：`monthlyGranted` 横幅键
  （8/9/10/11 月）= **月度重置实证**；`usageOver70` 横幅键 = 用量告警 UI 痕迹
- logs/：只有 CPU 遥测，无用量数据

### 7.3 逐调用用量：双通道 UNSUPPORTED

UsageSample 本义字段（tokens_in/out / model / ts）本地与 API 均无——客户端
不落逐调用痕迹，服务端只给聚合。M2 spec 需按聚合口径重定义。

### 7.4 credits/extra_credits 语义（§2 清单首项）

签到 status 响应字段 = **签到奖励包面额级**，非账户余额；账户余额看 7.1 的
usage_summary / 包分账本。

## 8. 多 profile 目录形状（2026-11-14，mac 真机取证）

- 本机 `~/Library/Application Support/Trae CN/User/` 目录实存：`History` /
  `globalStorage` / `settings.json` / `snippets` / `workspaceStorage`——
  **无 `profiles/` 目录**，登录态在共享 `globalStorage/storage.json`
- 结论：客户端**单登录态**，无多 profile 目录形状可枚举；多账号 = 无据
  （与 A2-02 §9 表一致，未取证不推断）
- dock 扫描口径不变：`_scan_ss_aes` 首个现存候选获胜 → `main` 账号

## 9. 推理通道取证（2026-11-14，mac 资源串侧 · R4 G0）

> 结论：**推理通道形状清晰，反代上游候选一号**；真机网络观察与请求体
> 形状待验（Windows/运行态侧），未取证不推断（红线 5）。

- Agent 核心 = Rust `icube_server_rs/llm-client`（modules/ai-agent
  libai_agent.dylib）：**自带多协议 LLM 路由器**——OpenAI 形
  `/models/chat/completions`、`/v1/models`、Anthropic 形 `/v1/messages`
  共存（provider 名单含 openrouter/openai/anthropic/aws/gemini）
- 服务域：`api.trae.com.cn`（product.json `iCubeAgent`；账号面
  `api.trae.cn` = M1 已通）
- 端点串（libai_agent.dylib）：`api/ide/v1/llm_raw_chat`、
  `api/ide/v2/llm_raw_chat`（**raw 模型调用**）、`api/ide/v1/chat`、
  `api/ide/v1/get_model_list`、`api/agent/v3/llm_utils_chat`、
  `api/agent/v3/workflow/start`；鉴权线索 `x-ide-token` 头
- **响应自带逐调用 usage 结构**（NativeLLMUsage
  prompt/completion/total_tokens + Anthropic input/output_tokens 双形）——
  ADR-012 裁决 7（Meter 直读上游 usage）在本 provider 天然可行
- 余额面：`api/v1/commercial/check_estimated_balance`、
  `api/v1/commercial/get_session_usage`（Router 输入候选）
- 流式：遥测键 `icube_ai_agent_model_llm_stream` 证实 SSE/流式存在；
  请求体形状与头组待真机验证

## 10. 会话/工作区形状取证（2026-11-15，mac 真机只读 spike · R5 S0）

> 只读取证（ADR-013 裁决 1：首批只做 workspace kind）；数据根
> `~/Library/Application Support/Trae CN/`（VS Code 家族布局）。

### 10.1 workspace kind（本地可迁 ✅）

- `User/workspaceStorage/<hash>/workspace.json`（`folder` = `file://` 工作区
  绑定）+ `state.vscdb`（SQLite `ItemTable` KV）+ 扩展目录——**workspace
  绑定与工作区级状态**，R5 首批迁移对象；快照/还原 = 目录级拷贝
- 全局侧：`User/globalStorage/state.vscdb`（920K，311 keys）+
  `User/settings.json` + `User/snippets/` + `User/History/`
- **多账户隔离 = key 前缀**：`<账户数字id>:draft:session:*` /
  `<账户数字id>_ai-chat:sessionRelation:*`——同一 db 两套账户 key 并存，
  迁移/还原须按账户前缀过滤，不能整库拷贝（会串账户）

### 10.2 conversation kind（本地不可迁 ❌ → server 级）

- `chat.ChatSessionStore.index` 仅 26 字节（云端索引指针）；`ChatStore` 1KB；
  本地无对话正文——**trae 会话正文在服务端**，本地迁移不可行；
  对话级 = 官方导出/共享能力（server kind，裁决 4）或后续逐家取证

### 10.3 风险与边界

- `state.vscdb` 为 SQLite 活库（客户端运行中持锁）：快照须 `mode=ro` 读或
  客户端退出后拷贝；还原 = 客户端退出 + 目录级替换 + 前缀过滤
- `chatHistoryNeedToBeMigrated-<账户id>` key 存在——官方自身有历史迁移机制
  痕迹，后续 server 级取证时留意官方同步开关
