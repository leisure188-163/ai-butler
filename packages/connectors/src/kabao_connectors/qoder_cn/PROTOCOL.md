# PROTOCOL · Qoder CN（qoder 连接器协议字典）

> 本文件是**逆向结论的归宿**（A0-01 §2.1）：端点 / 凭据解锁 / 风控头 / 判定。
> 来源 = 旧仓库取证笔记 NOTE-02（2026-10-21，客户端 0.4.8）+ 旧实现只读提炼；
> 实现按 ADR-004 走**声明式扩展**，不搬代码。每条结论附取证日期；
> **适配器/声明里不允许出现本文没有的端点与头**。

## 1. 身份与凭据

| 项 | 事实 | 取证 |
|---|---|---|
| 产品 | Qoder CN（阿里系 AI IDE，桌面端 Electron） | 2026-10-21 |
| 积分面 | **只有 campaigns 一条领取链**——无签到/任务/抽奖/宠物接口（桌面宠物是纯 UI 玩偶） | 2026-10-21 |
| 数据目录 | `%APPDATA%\com.qodercn.app*`（glob 扫描） | 2026-10-21 |
| 凭据文件 | `auth.v1.dat`：**DPAPI（CryptUnprotectData）+ AES-256-GCM（CNG BCrypt）双层**；密钥在 `Local State` | 2026-10-21 |
| token 有效期 | 解密产物 `expiresAt` ISO 时间——入 vault.expires_at；**过期直接 NO_AUTH 提醒重登，不碰 refresh token**（不与桌面端争抢令牌轮换） | 2026-10-21 |
| 机器身份 | 客户端自带 `resources/umid/runtime-info` 组件产出 8 头组：`Cosy-Version / ClientType / MachineOS / MachineToken / MachineCode / MachineType / MachineId / MachineHostname` | 2026-10-21 |
| 组件定位 | Windows：`QODER_UMID_EXE` 环境变量 → `{LOCALAPPDATA,ProgramFiles,ProgramFiles(x86)}/Qoder CN|Qoder` → 卸载注册表 `Qoder*` 条目（**子键为 GUID 型**；`InstallLocation` 常缺失，`DisplayIcon` 指向安装目录的 .ico——取其父目录）。macOS：`/Applications/Qoder*.app/Contents/Resources/umid/runtime-info`（M1 暂缓） | 2026-11-11 |

### 1.1 真机取证补记（2026-11-11，客户端 0.4.8 / Windows）

- **runtime-info 无参运行**即输出一行 JSON：`{machineToken, machineType, machineCode,
  vmInfo{isVm,brand,percentage,vmTypeCode}}`——`--account-stdin` 模式实测报
  `accountOutcome: "invalid_input"`（stdin 格式未公开），实现用**无参模式**
- **8 头映射确认**（与旧系统 risk.py 一致）：`Cosy-MachineToken/Code/Type` =
  runtime-info 输出三字段；`Cosy-MachineId` = 数据目录 `auth.machine-id`（36 字符
  UUID）；`Cosy-Version` = 安装根 `build-manifest.json` 的 `productVersion`；
  `Cosy-MachineOS` = `{x86_64|aarch64}_windows`（SDK 口径，非平台原生写法）；
  `Cosy-MachineHostname` = 本机 hostname；`Cosy-ClientType` = 静态 `"10"`
- **会话 JSON 形状**（auth.v1.dat 解链产物）：`{token, refreshToken,
  refreshTokenExpiresAt, expiresAt, schemaVersion, user}`——`token` **非 JWT**
  （`dt-` 前缀不透明串），有效期只认 `expiresAt`（ISO，真机样例 2026-12-04）；
  实现不碰 refreshToken（不与桌面端争抢轮换）

## 2. 端点族

Base：`https://openapi.qoder.com.cn`

| 端点 | 方法 | 说明 |
|---|---|---|
| `/sash/api/v1/me/campaigns` | GET | 活动列表（uid/showCampaign/claimable/campaignUrl/campaigns[]） |
| `/sash/api/v1/me/campaigns/{campaignId}/claim` | POST | 逐项领取；**无请求体**；服务端幂等（重复领取不重复计） |

公共约定：

- `Accept: application/json`、`User-Agent: Qoder/claim`、`Cosy-ClientType: 10`、
  `Authorization: Bearer <token>`——全部**静态头**
- **缺 `Cosy-ClientType` 服务端返回空活动列表**（表现为"没有可领的活"而非报错，
  静默陷阱）；**缺机器身份头组则不返回可领取的日常活动**（同陷阱）——
  新系统对两者都显式化（ADR-004 §4），绝不静默降级
- **响应无外壳业务码**（2026-11-11 真机取证）：HTTP 200 即 ok，顶层直接是业务字段
  `uid / showCampaign / claimable / campaignUrl / campaigns[]`——声明 `code_path: ""`
- 列表项形状（真机取证 2026-11-11）：`campaignId`（36 字符主键）/ `campaignKey`
  （`act-YYYYMMDD-NNN`）/ `actionType`（`CLAIM_BENEFIT`=领取型、`VIEW_DETAILS`=促销
  详情不可领取）/ `startAt`/`endAt`（**epoch 秒**，每日领取窗口 ≈24h）/
  `claimStatus`（枚举）/ `benefit{kind,amount,...}` / `placements[]`

## 3. 结果判定（结构化字段，非数字码）

| 字段事实 | → Status | 备注 |
|---|---|---|
| 列表筛选（`claimStatus == "CLAIMABLE"` 且 `actionType == "CLAIM_BENEFIT"`）后有项 | 可领取 → 逐项 claim | 窗口语义；时间窗由服务端折算进 claimStatus |
| 全部项 `CLAIMED` | ALREADY | 本期已领（2026-11-11 真机实测状态） |
| `claimStatus` 其它值 | PENDING | 服务端处理中，可退避 |
| 筛选后列表双空（无可领也无可领标记） | PENDING | 活动未开始/已结束，如实上报 |
| claim HTTP ok | 受理 → status 复查定论 | **响应无业务码**（replayed 回执形状非关键，§6 定性） |
| 未知形状（campaigns 缺失/非列表等） | FAILED + PROTOCOL_CHANGED 事件 | ADR-002 机制兜底 |

## 4. 幂等与窗口

- claim 服务端幂等：重复调用不重复计（`replayed` 回执）；引擎幂等键与 trae 同型
  （`(provision.run, account_id, 窗口)`）
- 多活动一次窗口可领多项：引擎逐项领取，结果聚合一条 Run（证据按项列 evidence）
- 刷新时间：**每日 10:00（本机墙钟）开新窗**（2026-11-11 真机取证：oracle
  status 的 window 字段 `"11-11 10:00 ~ 11-12 09:59"` ≈24h 滚动窗，startAt/endAt
  epoch 秒同证）——`refresh_at: "10:00"`（core `claim_window`：结算点前发起
  属前一业务窗，回放上一窗台账）。**10:00 前的触发位必然空跑**（服务端尚未
  刷出当天活动，status 呈昨日 CLAIMED → ALREADY 回放）——验收实录：09:59:46
  新系统 ALREADY，10:02 oracle 见 CLAIMABLE；调度缺省值对齐 10:05 起

## 5. 行为对照验收（A0-01 §2.2）

> **2026-11-11 Windows 真机验收（oracle = auto-signin-kit `qoder status` / `qoder auto`）**：
> dock 成功（DPAPI 解链验真 + umid 7 字段采齐，issues 空）→ 全已领 ALREADY（两轮：
> 09:59 旧锚点 + 10:06 新锚点）→ 同窗口二触发回放同 Run id（台账单条）→ oracle
> 对同账号同判 ALREADY（"本周期已领取 100 Credits"，token_expires_at 2026-12-04
> 与新系统 vault.expires_at 一致）。验收即抓 1 真 bug：**refresh_at 00:00 与服务端
> 每日 10:00 活动窗错配**——09:59 的 ALREADY 台账在 10:00 刷新后持续回放，当天
> 可领项静默漏领（oracle 10:02 见 CLAIMABLE、新系统 10:06 仍回放旧台账实证）；
> 已修（`refresh_at: "10:00"` + 调度首班对齐 10:05，改声明不改代码）。另修正
> 缺辅凭据语义：NO_AUTH → FAILED + 停靠 hint（ADR-004 §4 原裁决，重登治不了
> 没停靠）。CLAIMABLE 逐项领取当日未自然发生：10:00 刷新后桌面端分钟级内
> 领走（10:02 CLAIMABLE → 10:06 已 CLAIMED，期间两系统均未发 claim）。

| 场景 | 期望 | 结果 |
|---|---|---|
| 窗口内有 CLAIMABLE 活动 | 逐项 claim → CLAIMED（evidence 逐项） | ⚪ 当日未自然发生（桌面端抢领）；离线覆盖列表领取全语义（test_decl_list），10:05 调度窗自然验证 |
| 全部活动已领 | ALREADY（不发起无谓 claim） | ✅ 真机两轮 ALREADY 零 claim；oracle status/auto 同判 ALREADY |
| 无机器身份头（vault 无 umid kind） | FAILED + repair_hint（重新停靠），绝不静默空列表 | ✅ 真机抹 umid → FAILED + repair_action_id=dock |
| token 过期 | NO_AUTH + 待处理可见修复提示 | ⚪ 真过期未自然发生（exp 2026-12-04）；主凭据缺失真机 NO_AUTH + 修复提示，过期码离线 mock 覆盖 |
| 同窗口双触发 | 第二次回放首次台账记录 | ✅ 两轮回放同 Run id（台账单条） |

## 6. 已知风险与待取证

- **已回填（2026-11-11 真机只读取证 + 行为验收）**：响应无外壳业务码
  （`code_path: ""`）、campaigns 数组在顶层、列表项主键 = `campaignId`、
  startAt/endAt = epoch 秒、actionType 枚举（CLAIM_BENEFIT/VIEW_DETAILS）、
  claimStatus 枚举实测 CLAIMABLE（oracle 10:02 实录）与 CLAIMED——全部落进
  provision.run.yaml，本文件与声明一致
- **claim 响应 body 形状：非关键**（2026-11-11 验收定性）——旧实现只认
  HTTP code、不解析 body，定论靠 status 复查（`confirm_by_status: true` 同构）；
  `replayed` 回执字段是否存在留明早窗口顺手取证，不阻塞
- **桌面端竞速观察**：10:00 刷新后桌面端分钟级内领取（10:02 CLAIMABLE →
  10:06 CLAIMED，期间两系统均未发 claim）——新系统价值定位 = 桌面端未开时
  的兜底领取；若长期抢不到 CLAIMABLE 属预期行为，权益无损（服务端幂等）
- runtime-info 是外部进程依赖：安装目录变动/客户端升级会破坏定位——dock
  issue 必须列出候选路径与排查动作（`QODER_UMID_EXE` 环境变量覆盖保留）
- umid 头组有 30 分钟时效观察记录（旧系统缓存策略）——M1 dock 缓存进 vault，
  由 dock 重跑刷新，不做运行时缓存
- `QODER_TOKEN` 环境变量手动供 token 的逃生门：**不迁移**——绕过 vault 的
  凭据注入路径违反最小授权（A2-02 §5）；手动场景 = 手动停靠
