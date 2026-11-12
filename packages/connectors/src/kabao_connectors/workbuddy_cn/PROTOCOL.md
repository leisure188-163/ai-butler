# PROTOCOL · WorkBuddy CN（workbuddy_cn 连接器协议字典）

> 本文件是**逆向结论的归宿**（A0-01 §2.1）：凭据解密链 / 端点 / 判定 / 已知风险。
> 来源 = 旧仓库取证笔记 NOTE-01（2026-10-21~10-22）+ 旧仓库源码（da396d7^）
> 逐行核对 + 本机实况核查（2026-11-11，Windows，WorkBuddy AI 5.9.4 /
> WorkBuddy 5.9.3 双版本并存）；实现走**端口实现 + 加密凭据解密链**
> （ADR-006），不搬代码（helper.js 例外：协议契约原样搬运禁改）。
> 每条结论附取证日期；**适配器里不允许出现本文没有的端点与编排**。

## 1. 身份与凭据

| 项 | 事实 | 取证 |
|---|---|---|
| 产品 | WorkBuddy（腾讯系，CodeBuddy 桌面端登录后写凭据；endpoint `https://copilot.tencent.com`） | NOTE-01 2026-10-21 |
| 权益面 | M1 = 每日签到（`{"credit":100}` / 日，连签奖励）；成长中心（旅行/任务/补登/兑换/盲盒）= 后续批次（ADR-006 决策 1） | 2026-11-11 |
| 凭据源 | 桌面端登录后自动写出的 JSON 文件；定位优先级 = `WORKBUDDY_AUTH_FILE` 覆盖（路径不存在显式报错）> 平台默认扫描：Windows `%LOCALAPPDATA%\CodeBuddyExtension\Data\Public\auth\workbuddy-desktop.info`；macOS `~/Library/Application Support/CodeBuddyExtension/Data/Public/auth/workbuddy-desktop.info`；Linux（CLI）`$XDG_DATA_HOME/CodeBuddyExtension/Data/Public/auth/Tencent-Cloud.coding-copilot.info`（旧路径/兜底扫 `~/.config/…`、`~/.workbuddy/auth/workbuddy-desktop.info`） | NOTE-01 §2 + 本机 2026-11-11 实证（文件在，同目录另有带时间戳的轮换历史 `.info`） |
| 文件锁 | 客户端刷新 token 时短暂独占文件 → `PermissionError` 重试 3 次 × 2s 间隔 | NOTE-01 §2 |
| 凭据 JSON | 必备形状 `{auth:{accessToken,…,domain?,endpoint?}, account:{uid, enterpriseId?}}`；本机实况含大量多余字段（accounts/allAccounts/refreshToken/expiresAt…）——**解析只取申报字段，多余忽略**；`auth.endpoint` 存在且为合法 https 才覆盖默认 base | NOTE-01 §3 + 本机 2026-11-11 |
| accessToken 两形态 | 旧版**明文**字符串（正则 `[A-Za-z0-9._~+/-]+=*`，1~32768 字符）；新版 **`$wbEncrypted` 信封**：`{"$wbEncrypted":1,"envelope":"<base64(JSON)>"}`，信封内 `{suite:1, keyId:<16位hex>, nonce:<12B b64>, authTag:<16B b64>, ciphertext:<b64>}`——**本机实况 = 信封形态**（accessToken/refreshToken/nickname/phoneNumber 全信封），明文路径为兼容保留 | NOTE-01 §3/§4 + 本机 2026-11-11 实证 |
| 解密链 | helper JS 在**客户端自带 Electron 运行时**子进程内执行：`ELECTRON_RUN_AS_NODE=1` 跑客户端 exe → stdin `{version:1, operation:"decrypt", value:<信封对象>}` → 内部绑定 `process._linkedBinding('electron_browser_workbuddy_storage').loggerGet()` 取 `atRestSecretKey` → `key = sha256(atRestSecretKey 字符串)`，`keyId = sha256(key) hex 前 16 位` 校验 → AES-256-GCM（nonce 12B / authTag 16B，AAD 固定拼接见 helper.js）→ stdout `{version:1, ok:true, accessToken}` / 失败 `{version:1, ok:false, reason}` 且退出码 1 | NOTE-01 §4 + helper_js.py 逐行核对 2026-11-11 |
| helper 管道契约 | 超时 10s（与剩余预算取 min）、输入输出各 65536B 上限；helper 子进程可回 reason 白名单七值：`INVALID_FORMAT / UNSUPPORTED_ENVELOPE / RUNTIME_UNAVAILABLE / KEY_MISMATCH / DECRYPT_FAILED / HELPER_TIMEOUT / HELPER_PROTOCOL`（前五个 + HELPER_PROTOCOL 为 JS 侧可能值，HELPER_TIMEOUT 由 runner 超时侧产生）；`RUNTIME_NOT_FOUND / INVALID_RUNTIME_PATH` 由 runtime 定位器产生、`MISSING_SESSION` 由会话校验产生——全部收敛为 NO_AUTH 语义，人话文案沿旧仓库 AUTH_REASONS；子进程环境剥离 `NODE_* / ELECTRON_* / WORKBUDDY_*` 前缀后强制 `ELECTRON_RUN_AS_NODE=1`；token 一律不进异常文本 | NOTE-01 §4 + session.py 核对 2026-11-11 |
| `probe` 操作 | 同管道发 `{version:1, operation:"probe"}` → `{ok:true, electron:<版本>}`：离线探测运行时能力（dock/诊断用，不解密不联网） | NOTE-01 §4 |
| 客户端定位 | 优先级 = `WORKBUDDY_EXE` 显式指定（路径无效显式报错，不当"未安装"）> 默认目录探测（`%LOCALAPPDATA%\Programs\WorkBuddy\WorkBuddy.exe`、`%ProgramFiles%\WorkBuddy\WorkBuddy.exe` 等常见根）> 卸载注册表（HKCU/HKLM，含 32/64 位视图）。**实测定稿（2026-11-11）**：本机两条目 `WorkBuddy AI 5.9.4`（HKCU）/ `WorkBuddy 5.9.3`（HKLM），`InstallLocation` **均为空**——exe 必须从 `DisplayIcon` 取：剥引号 + 按 `,` 截断剥图标索引后即主 exe 本体（`D:\software\ai-tools\WorkBuddyAI\WorkBuddyAI.exe` / `D:\software\ai-tools\WorkBuddy\WorkBuddy.exe`）；条目匹配 = **DisplayName `WorkBuddy` 前缀**（大小写不敏感，兼容 `WorkBuddy AI` 变体——旧仓库正则 `WorkBuddy(\s+\d+…)?` 匹配不上 AI 变体，**勿沿用**） | 2026-11-11 |
| 多版本并存 | 双版本并列为常态：候选 runtime 按顺序尝试解密，`KEY_MISMATCH` 换下一个；全败 → NO_AUTH + hint「用 `WORKBUDDY_EXE` 指定与凭据匹配的客户端」（ADR-006 决策 6） | 2026-11-11 |
| 鉴权头 | `Accept: application/json`、`Authorization: Bearer <token>`、`Content-Type: application/json`、`X-User-Id: <uid>`、`User-Agent: WorkBuddy`；`X-Domain: <domain>`（本机 `www.workbuddy.cn`，凭据里存在才带）；`X-Enterprise-Id` + `X-Tenant-Id`（企业号 `enterpriseId` 存在才带） | NOTE-01 §3 |
| token 生命周期 | `expiresIn 2592000`（30 天），客户端自动刷新并**重写凭据文件**——Kabao **现用现取**，绝不入库持久化（ADR-006 决策 3）；本机 `lastRefreshTime` 证明轮换在发生 | 本机 2026-11-11 |

## 2. 端点族（M1 签到最小集）

Base：`https://copilot.tencent.com`（凭据 `auth.endpoint` 覆盖规则见 §1）

| 端点 | 方法 | 说明 |
|---|---|---|
| `/v2/billing/meter/checkin-activity-status` | POST | 查活动状态（只读）：`active` / `today_checked_in` / `streak_days` / `total_credits` / `is_streak_day` / `next_streak_day` / `activity_name` |
| `/v2/billing/meter/daily-checkin` | POST | 领取今日积分（幂等）：成功 `{"credit":100}`；已领返回 `null` 或 HTTP 400 `{"code":10001}` |

- 两接口均**幂等**（状态查询只读；领取对已领日不重复发）→ 适配器单次调用
  如实上报，重试交给调度高密度触发（旧仓库重试语义收敛为调度兜底）
- 请求体：POST 空体（旧仓库 net.post 无 payload 直发）

### 2.1 成长中心端点速查（后续批次，M1 禁止出现）

17 端点（`/v2/activity/growth/` 下：buddy/travel×4、tasks×3、streak、heatmap、makeup-cards、redeem×2、lottery×2、buddy/quota+open、energy）已核对存在（NOTE-01 §6 附表）。实现批次立项时按「每步独立 try、任务奖在抽奖前、补登在兑换前」的顺序纪律在本文件扩节定稿；其中写路径（补登/抽奖/开盒/兑换）**不可逆不重试**，`client_token` 缺失必 400。

## 3. 结果判定（状态查询驱动，未签才领）

| 字段事实 | → Status | 备注 |
|---|---|---|
| 凭据文件缺失 / JSON 损坏 / 必备字段缺失 | **NO_AUTH** + hint | 「打开 WorkBuddy 客户端登录」/「重新登录客户端」 |
| 信封形态但 runtime 未找到 / 全候选 KEY_MISMATCH / 解密 reason 族 | **NO_AUTH** + hint | RUNTIME_NOT_FOUND→安装客户端；KEY_MISMATCH→指定 `WORKBUDDY_EXE`；其余见 reason 人话表（旧仓库 AUTH_REASONS 语义照搬） |
| HTTP 401 | **EXPIRED** + hint「重新登录客户端」 | 服务端拒绝认证 |
| HTTP 403 | **NO_AUTH** + hint「检查账号权限或活动条件」 | **不能据此判登录过期**（旧仓库原语义） |
| status `active == false` | **PENDING** | 活动未开启，中性如实上报（evidence 可带 `activity_name`），用户无可动作 |
| status `today_checked_in in (true, 1)` | **ALREADY** | 附 `streak_days` / `total_credits` 证据 |
| claim 返回 `null` / HTTP 400 且 `code==10001` / msg 含「已签」 | **ALREADY** | 服务端判定已领——复查 status 取最新证据（复查失败用首次 status 兜底，不致命） |
| claim 返回 `credit` | **CLAIMED** | 复查 status 组装连签/累计证据 |
| claim 返回**其他** `code` | UnknownEngineCode 上抛 | 用例层 FAILED + PROTOCOL_CHANGED 事件（红线 5，禁静默兜底） |
| TransportError（网络不可达/超时/响应非 JSON） | **FAILED** + evidence | transport 契约如实上报；调度高密度触发自然兜底 |
| HTTP 5xx | **FAILED** + evidence | 服务端故障如实上报 |

方言注册（装载期一次）：`{"10001": ALREADY}`——claim 400 已签码；401/403 是
HTTP 层判定**不进方言**。旧仓库 result 码映射对照：`CLAIMED/ALREADY` 直映；
`INACTIVE`→PENDING；`NO_AUTH/NO_SESSION/AUTH_ERROR/FORBIDDEN`→NO_AUTH；
`AUTH_REJECTED`→EXPIRED；`NETWORK/TIMEOUT/ERROR/UNKNOWN`→FAILED（evidence
带原始摘要）。

## 4. 易错契约（改判定前回看，每条都是旧系统踩过的）

- **token 脱敏**：token / `Authorization` 永不进日志、异常文本、evidence；
  解密明文缓冲用完即弃（helper.js 内部 finally 清零）；适配器对
  evidence 摘要统一过脱敏
- **不碰 refreshToken**：不读、不解、不轮换——登录与续期归客户端（NOTE-01 §1 边界）
- **服务端日界**：`today_checked_in` 等判定以**服务端日期**为准（旧仓库活跃
  日历教训：本机时区会把月初/午夜算错一天）；Kabao 幂等窗口 `refresh_at
  "00:00"` 按自然日显式声明
- **claim 已领三形态全兼容**：`null` / 400+10001 / msg 含「已签」——服务端
  任一改版形态都判 ALREADY（NOTE-01 §5 实测）
- **复查失败不致命**：CLAIMED/ALREADY 之后的 status 复查失败 → 用首次
  status 组证据，不降级结果
- **协议失效症状**：某步稳定 400/404 或字段形状变（服务端改版最爱动细节，
  NOTE-01 §13）→ 当次更新本文 + 加离线 fixture，禁止静默兜底
- **解密失效症状**：稳定 `RUNTIME_UNAVAILABLE`（客户端改内部绑定）或批量
  `KEY_MISMATCH`（密钥体系换代）→ 重抓桌面端取证，更新 helper.js 与本文

## 5. 真机行为验收（2026-11-11，Windows / WorkBuddy AI 5.9.4）

验收实录（server :8010，`KABAO_DB=workbuddy-acceptance.db KABAO_SCHEDULE=0`；
NO_AUTH 演练走 :8011 第二实例 + `WORKBUDDY_AUTH_FILE` 覆盖，真凭据未碰）：

| # | 场景 | 预期 | 实测 | oracle 对照 |
|---|---|---|---|---|
| 1 | dock 体检 + 名册注册 | 四项全过 + 账号入册（幂等） | ✅ `accounts=["workbuddy_cn:main"]` `issues=[]`；复扫幂等同答。**首跑抓出注册表句柄 bug**（with 块关句柄后查值 → DisplayIcon 形态全丢）→ 修复 + 假 winreg 补句柄关闭语义回归钉 | dock 纯体检 = Kabao 新形态（旧仓库无 dock 概念）；体检项语义沿 §1 取证 |
| 2 | 已签窗口 run | ALREADY + 连签/累计证据 | ✅ `ALREADY` + `signal=ok` + 「今日已签过（今日 +100，连续 42 天，累计 4200 积分）」；3.2s 内含真解密子进程；同窗口复跑回放同 run id（台账幂等） | summary 组装语义 = 旧 `_already`（credit/streak/累计可选全带） |
| 3 | 未签窗口 run | CLAIMED + credit/连签证据 | ⚪ 验收日桌面客户端已签，无未签窗口——留下个 09:15 班次窗口回验；判定路径由 28 项离线测试钉定（含复查取证/复查失败兜底） | 判定表逐行 = 旧 checkin（三处刻意分歧见 §4/计划自审） |
| 4 | NO_AUTH 演练（`WORKBUDDY_AUTH_FILE` 指向不存在路径 / 空 JSON） | NO_AUTH + hint；**不碰真凭据文件** | ✅ 缺失路径：dock 出「未找到凭据文件…（检查过: 覆盖路径）」；run → NO_AUTH + `signal=attention` + repair→dock，evidence 只报覆盖路径不回落。空 JSON：run → NO_AUTH + MISSING_SESSION 文案（`{"auth":{}}` 映射 MISSING_SESSION 而非 INVALID_FORMAT——实测定性） | reason 人话文案 = 旧 AUTH_REASONS 逐条照搬 |
| ⚪ | 解密端到端（真 JS + 真 runtime） | 离线测不了；随场景 2/3 隐式覆盖（信封解密 → 真实调用成功即证） | ✅ 随场景 2 隐式覆盖：真信封 → `WorkBuddyAI.exe`（HKCU DisplayIcon 定位，KEY_MISMATCH 零发生）Node 模式解密 → Bearer 调用 `copilot.tencent.com` 成功返回全量 status 字段 | 解密链 = 旧 helper.js 逐字节（ast 提取非转抄） |

## 6. manifest 语义

- `provision.run: {kind: adapter, entry: adapter.kabao, budget_seconds: 120}`
  （1 次解密 ≤10s + 2-3 个请求，120s 留足余量；旧仓库 420s 收紧是因 Kabao
  无重试循环）
- `schedule.times` 4 班次（沿 doubao 节奏 `["09:15","13:15","19:15","23:15"]`）
  + `refresh_at: "00:00"` **显式声明**（adapter 连接器必须显式——declarative
  回落分支对 adapter 会 KeyError）
- 无 `credential` 段（现用现取零申报，ADR-006 决策 3）

## 7. 用量取证（2026-11-12，M2 真机只读 spike，WorkBuddy 5.9.3 / CodeBuddy CN 4.12.3 / Windows）

> M2-用量取证清单 §5 四项全落；只读取证（API 最小头试探，M1 凭据链原样
> 复用——$wbEncrypted 信封解链一次通过），token/凭据未进任何记录。

### 7.1 额度主通道：get-user-resource = 85 包分账本（额度雷达全量输入）

`POST /v2/billing/meter/get-user-resource`——客户端 `getAccountUsage` 的
个人分支（`getPersonalUsage`，enterpriseId 为空即走此分支；企业分支
get-enterprise-user-usage 个人账号不适用未探）：

- body `{PageNumber, PageSize, ProductCode: "p_tcaca", Status: [0, 3],
  PackageEndTimeRangeBegin/End}`——**时间戳必须是字符串**（Go 结构体
  string 类型，传数字 400 unmarshal 错误，首探踩坑实证）
- 响应 `data.Response.Data{TotalCount: 85, TotalDosage, Accounts[]}`：
  逐包 `CapacitySize/CapacityUsed/CapacityRemain` + `CycleCapacity*` 三件套
  + `*Precise` 字符串版（JS number 精度防御）+ `CapacityUnit: "credits"` +
  `CycleStartTime/CycleEndTime/ExpiredTime` + `PackageName/SubProductName`
  （包来源）+ `Status`（0=在用 3=已耗尽）
- **本机实况**：活跃 27 包 remain=1894 / used=31（裂变包 26 + 个人体验版 1，
  TotalDosage 1894 = 活跃剩余合计）；耗尽 58 包 used=5112；活跃包
  CycleEnd 2026-12-01 = **月度周期**
- `POST /v2/billing/meter/get-payment-type` → `{paymentType: "free"}`（套餐形态）

### 7.2 checkin-activity-status 全字段（M1 七字段之外新增 5）

`active / today_checked_in / streak_days / is_streak_day / next_streak_day`（M1）+
`daily_credit: 100` / `today_credit: 100` / `streak_bonus_days` /
`streak_bonus_credit` / **`checkin_dates[]`（43 天逐日签到日历）**。

### 7.3 成长中心 GET 三件语义（M1 §2.1 猜测定案）

- `GET /v2/activity/growth/heatmap`：`cells[{date, score, has_new_buddy}]`
  一年逐日——**活跃度日历，非用量图**（score 只认对话，与旧仓 NOTE-01 一致）
- `GET /v2/activity/growth/energy`：`{balance: 5, total_consumed: 110,
  total_earned: 115}` = **能量账本**（游戏化激励积分，非 API credits）
- `GET /v2/activity/growth/buddy/quota`：`{affordable: 0, balance: 5,
  cost_per_open: 10, max_open_count: 5}` = **盲盒配额**（cost 按 energy balance）
- `GET /v2/activity/growth/streak`：连签 `streak{days, month_total_days,
  month_consumed_days, next_tier…}` + `makeup_cards{balance, max}` +
  `redemption_status{tier_*_count/status}` 全形状

### 7.4 本地数据源：UNSUPPORTED（API 唯一通道）

WorkBuddy logs（daemon/AgentModelResolver 生命周期，无用量数据）；
CodeBuddyExtension Data = IDE 会话缓存（check-point/file-tree/history/
genie-cache），无用量文件。逐调用 tokens 双通道 UNSUPPORTED。
