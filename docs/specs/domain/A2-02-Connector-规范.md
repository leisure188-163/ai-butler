# A2-02 · Connector 规范

> 一个 AI 产品 = 一个 Connector 包。本文定义包结构、能力声明、三级扩展、
> 沙箱边界与 PROTOCOL.md 模板。M1 首批四个 Connector 按本文实现。

## 1. 包结构

```
packages/connectors/src/butler_connectors/<id>/
├── manifest.yaml      # 身份 + 能力矩阵声明（唯一入口，注册表据此发现）
├── PROTOCOL.md        # 协议字典（版本化）：端点/加密/幂等/业务码——逆向结论的归宿
├── declarative/       # 三级扩展之一：声明式能力（仅 L1）
│   └── provision.run.yaml
└── adapter.py         # 三级扩展之二：Python 适配器（实现 core 端口）
```

三级扩展之三（独立进程 Adapter）放 `apps/gateway/` 的 app 插件（R4；
进程边界/通信/栈见 ADR-012——gateway 进程内直调 butler_core，只做转发与计量）。

## 2. manifest.yaml

```yaml
id: trae_cn
display: Trae CN
capabilities:
  provision.run:                  # 能力 id：动词.名词（provision/usage/session/health）
    kind: declarative             # declarative | adapter | gateway
    entry: declarative/provision.run.yaml
  usage.read:
    kind: adapter                 # 复杂能力用代码
credential:
  kinds: [ss_aes]                 # 支持的凭据类型
  unlock: local-client            # 解锁方式: local-client | vault | manual
schedule:                         # 调度声明（cron 缺省值，用户可在 UI 改）
  provision.run: ["09:05", "13:05", "19:05", "23:05"]
retired: false                    # 可选：退役连接器不进入平台名册/一键接入（代码保留）
```

规则：
- 注册表只读 manifest，不 import 业务代码；能力未声明 = UI 不渲染该能力的入口
- `display` 用产品名（用户语言），`id` 是稳定技术标识
- `retired: true` 仅用于已下线但仍需保留代码/审计的连接器；账户与历史应另行清理

## 3. 三级扩展与适用边界

| 级别 | 适用 | 谁写 | 约束 |
|---|---|---|---|
| 声明式 YAML | 纯 HTTP：登录态文件直读 + 接口签到（trae） | 用户/社区 | **仅限 L1**；五段式：auth / status / claim / business_codes / schedule |
| Python 适配器 | 需解密/客户端交互/CDP（qoder、doubao、workbuddy） | 官方 | 实现 core 端口；按 PROTOCOL.md 重写，不抄旧代码 |
| 独立进程 Adapter | 高并发反代 app（R4） | 官方 | 禁止声明式；只做转发与计量 |

**kind 收敛原则（扩展判据，2026-11-11 裁决）**：应用接入面 = **声明 + 可枚举
kind 的组合**，一套运行时 + N 份数据——绝不 per-app 平行代码（历史项目教训：
domains/trae 与 domains/qoder 各写一份 service/api/auth，同一签到逻辑 N 遍）。
- 协议特殊性（凭据解锁/动态请求头/签名算法）只允许以 **kind** 形态扩展：
  新 kind = 引擎加一个处理器，所有同 kind 应用共享；出现在"这个应用专用"的
  位置 = 违规
- per-app 代码仅剩一种合法形态：**core 端口实现**（协议复杂到声明表达不了时，
  如 CDP 编排），且只准实现 `capabilities()` + `run()`——dock/vault/幂等/
  调度/审计仍是底座的，不许自带平行件
- 判据口诀：这段逻辑换成另一个应用还能用吗？能 → 做 kind；不能且只有这一个
  应用要 → 先问是不是协议没取证全，取全了还特殊 → 端口实现

### 3.1 用户自定义平台（2026-11-18）

内置清单之外的平台由用户在管理台「＋ 自定义平台」自建。它不是一行登记记录，
而是**一份落到自定义连接器目录的声明式连接器**——所以它真的会被排班、真的会发
请求（与"纯登记式新建"那种看着能签到、实际永不执行的死平台本质不同）。

- **目录**：`BUTLER_CUSTOM_CONNECTORS` 环境变量优先，否则
  `%APPDATA%\butler\connectors`（Windows）/ `~/.butler/connectors`。
  目录结构与内置连接器同构：`<code>/manifest.yaml` + `<code>/declarative/*.yaml`
- **能力边界**：自定义目录**只允许 `kind: declarative`**——这些文件不由本项目
  维护，放开 adapter 等于放开任意代码装载，装载期显式拒绝；`entry` 路径必须
  位于连接器目录内（不许 `../` 越界）
- **不覆盖内置**：自定义 id 与内置 id 撞车 = 装载期 `ManifestInvalid`，
  落盘前的完整装载校验就会拦下（连文件都不写）
- **凭据形态**：首批只支持 `browser_cookie`（本机 Chrome 登录态，与内置网页
  连接器同一条捕获链路），因此自定义平台天然是 `kind: web`；
  `auth.domain` + `auth.cookies`（必需名单）由用户填
- **用户填什么**：状态查询（先问"今天领过没"）、领取请求、判定方式（业务码
  `code_path`+`expect_ok` 或布尔 `checked_in_path`）、登录域名与 cookie 名、
  调度时间。server 渲染成五段式声明（`auth/status/claim/business_codes/window`），
  缺省业务码方言 `{401: EXPIRED, 403: NO_AUTH}`（ADR-015）
- **落盘前校验**：临时目录完整装载一遍（manifest schema + 声明式 schema + 主凭据
  交叉校验 + entry 路径校验），通过才写正式目录（坏文件不进运行期）
- **热加载**：保存/删除后 `reload_connectors()` 重装端口（`replace=True`）→
  名册同步（`plat_platform`）→ 调度条目重排；删除后名册自动落 `deprecated`，
  历史台账保留。会话扫描源只准装配一次（ADR-013），重载时不重装

## 4. 声明式 schema（升级自旧 STD-07：从"只能声明签到"到能力矩阵）

```yaml
# declarative/provision.run.yaml
auth:
  kind: session-file              # 凭据来源（vault 负责解锁）
  reauth_status_codes: [401, 403] # 登录态失效判定（ADR-015；缺省=不申报）
  paths: ["%APPDATA%/Trae CN/User/globalStorage/storage.json"]
status:                           # 查询接口：判断"今天领了吗"
  request: { method: GET, url: "https://…/api/xxx", headers: {…} }
  expect: { field: "data.today", equals: true }
claim:                            # 领取接口
  request: { method: POST, url: "https://…/api/claim" }
business_codes:                   # 业务码 → core 结果词汇（唯一翻译点）
  "2000": CLAIMED
  "2001": ALREADY
  "401":  NO_AUTH
window: { refresh_at: "00:00" }   # 签到窗口（签到日 ≠ 自然日）
```

规则：business_codes 是声明式与 core 的**唯一翻译边界**；声明里出现
schema 外字段直接报错（`extra=forbid`，继承旧仓库"显式报错不静默兜底"的教训）。

**登录态失效申报（ADR-015）**：
- `auth.reauth_status_codes` 显式列出"哪些 HTTP 码代表登录态失效"，默认空 =
  不申报；连接器申报后才启用该判定，禁止引擎对任意 401/403 自行猜测。
- 运行时命中申报码 → `NO_AUTH` + 证据「鉴权被拒（HTTP xxx）——登录态已失效」+
  `RepairHint(action_id="relogin")`；未申报的 4xx/5xx 仍 `FAILED`。
- 健康判定 `invalid/expired` 后，butler 自动撤销自己的本地副本（ADR-016）；
  `load` 命中撤销 → `CredentialRevoked`，连接器仍按 `NO_AUTH` 处理，
  不感知"撤销/缺失"差异。
- 新接入应用必须在 PROTOCOL.md §2「认证与凭据」写明失效码，再回填本字段。

## 5. 沙箱边界（L7 市场的前置条件，M1 起就执行）

- 声明式 Connector 只能访问 manifest 内声明的域名（URL 白名单，加载期校验）
- Python Connector 进程内运行但凭据经 vault 注入（拿不到别的账号的凭据）
- 凭据最小授权：Connector 申报用哪几种凭据，vault 只解密注入那几种
- 第三方 Connector（非官方目录）默认降级运行：无 shell/无任意路径读，违规即卸载

## 6. PROTOCOL.md 模板

```markdown
# <id> 协议字典 v<semver>
> 来源：逆向结论 / 官方文档。每条结论附验证日期与环境。
## 1. 端点清单        method / path / 认证方式 / 已知变更历史
## 2. 认证与凭据      凭据类型 / 解锁协议 / 有效期与刷新
## 3. 关键请求形状    必需头（如设备风控头）/ 签名算法 / 请求体
## 4. 业务码字典      码 → 语义 → core 结果词汇映射
## 5. 幂等与重试      哪些操作重试安全 / 领取是否幂等 / 窗口语义 / **写动作复查退避**（见下方红线）
## 6. 已知风险        触发风控的条件 / ToS 边界
```

规则：PROTOCOL.md 是 Connector 的**唯一事实来源**——适配器代码里不允许出现
文档没有的端点/魔法值；发现新协议先改文档再改代码。

**写动作判定红线（2026-11-16 豆包误判事故全连接器继承，实证 PROTOCOL doubao §1.2）**：

1. **「请求送达 + 服务端成功信封」≠ 业务成功**——写动作成败必须以权威复查接口
   （如 detail 的 `checked_in_today`）判定，禁止以返回码或界面现象单点定论
2. **复查必须退避重试**——状态翻转有服务端延迟（豆包实证：点击生效后 3s 即查
   仍 false、稍后实为已签），单次即查即判 = 把成功误判成 FAILED；退避次数/间隔
   写进该连接器 PROTOCOL §5
3. **判 FAILED 前必须留诊断证据**——复查全 false 时把页面文本/响应码等入
   evidence，禁止无证据裸判（否则下次同类事故又无从取证）

## 7. 实现顺序（M1，由简到繁验证底座）

1. trae_cn（纯声明式）→ 2. qoder_cn（声明式 + 设备风控头）→
3. doubao_cn（CDP 编排）→ 4. workbuddy_cn（签到最小集，ADR-008 收敛）

**硬标准**：每个 Connector 不加特殊分支接入新模型；某个必须写例外 →
停下来改模型。每个完成后跑行为一致性对照（见 `../legacy/A0-01-旧系统知识资产.md` §4）。

## 8. 测试与 CI 边界（M1 起执行）

CI 只在 ubuntu 跑——平台特有调用（Windows DPAPI / macOS Keychain）与真浏览器
（CDP）在 CI 里**测不了**，测试体系按可注入性设计，规则四条：

1. **连接器测试必须离线**：HTTP 一律经 Transport 端口注入剧本化 FakeTransport
   （逐次响应清单，零真网 IO）；凭据经 FakeVault 注入桩值。测试里出现真域名
   请求 = 打回。
2. **平台 API 走工厂注入**：DPAPI/Keychain 等系统调用收敛在 adapter 模块，经
   工厂/runner 注入；非 Windows/非 macOS 环境用假 api 单测（CI 照跑，本仓
   `credman_windows` / `keychain_macos` 即此模式）。
3. **CDP 测试不起浏览器**：探测逻辑与浏览器操作分离；浏览器交互层用假 page
   对象测（M1 doubao_cn 落地时照此拆分）。
4. **真上游验证 = 行为对照验收，手动真机跑**：PROTOCOL.md 附脱敏响应样本；
   样本含真实 token/uid 不得入库——先脱敏再提交。


## 9. 多账号 dock/import 取证结论（ADR-003 §3，2026-11-14 重写 P5）

core/engine/server 已按 ADR-003 支持"一应用 N 账户"（`account_code`、
`PlatformOut.account_ids`、一键领取逐账户发起）。连接器侧取证结论如实登记如下，
**不虚报未验证能力**（红线 5）：

| 连接器 | dock 现状 | 多 profile 取证 |
|---|---|---|
| trae_cn | 单账号（首账号 `main`） | **已取证（2026-11-14 mac）**：`User/` 无 `profiles/`，登录态在共享 `globalStorage/storage.json`——客户端单登录态，无多账号形状（PROTOCOL §8） |
| qoder_cn | **多账号（CN `main` + Global `global-<hash>`，目录级 profile）** | **已取证（2026-11-17 Windows）**：`com.qodercn.app.stable`（CN，`openapi.qoder.com.cn`）与 `com.qoder.app.stable`（Global，`openapi.qoder.sh`）双数据目录、双 user id；token 跨 host 均 401，只有各自 host 200；dock 逐目录注册，2026-11-17 Global claim 写入 + status 复查通过（PROTOCOL §8.2） |
| doubao_cn | 单账号（CDP 单实例，端口单值 9222） | **已取证（2026-11-14 mac 运行态）**：app 级单实例锁——第二实例秒退 exit=0（独立 `--user-data-dir` 被客户端吞、端口不落地），多开不可行 → 多账号无据（PROTOCOL §8） |
| workbuddy_cn | 单账号（现用现取零申报） | **已取证（2026-11-14 mac）**：凭据 = 单文件 `workbuddy-desktop.info`——单会话文件即单账号，无多 profile 形状 |
| chatgpt_web | **多账户（ADR-011，每 profile 一槽）** | **已取证（2026-11-14 mac）**：Chrome 双 profile 均实存名单内会话令牌——多 profile 布局实证；账号同一性未验（不解密）；裁决 = 每 profile 一账户槽已接入 dock（browser.py，首个凑齐 = main 存量卡位，后续 = 目录名 slug） |
| claude_web | **多账户（同 ADR-011 通道）** | 本机无登录态（双 profile 均无 claude.ai cookie）——通道语义已就绪，名单补证维持挂账 |

**扩展点已落地**：`butler_core.accounts.ports.SessionSourcePort.enumerate_accounts()`
产出 `(account_code, account_name)`，`RegisterAccount.import_from_source()` 逐账号
入库，无需改 core/server 契约；browser_cookie 通道经 `CapturedProfile`
（browser.py）逐槽注册入库。桌面客户端连接器按各自 PROTOCOL.md"多 profile
目录形状"小节取证后接 dock；本机 Qoder 已有双账户数据源，其余桌面连接器
仍为单账号形状。

## 10. 调试端口归属（2026-11-18，ADR-026）

- **9222 归豆包客户端**（ADR-007 取证；`DOUBAO_CDP_PORT` 可覆盖），其他连接器
  不得假设该端口可用。
- 网页类连接器使用浏览器调试端口前必须调用 `web_ui.require_browser_port`：
  页面 target 出现客户端私有 scheme（如 `doubao://`）→ `PortNotBrowser`
  → 连接器显式失败（dock 进 issues / run 转 FAILED），**不往客户端窗口里开页**。
- 端口按连接器 env 覆盖（首个采用：agentrouter `AGENTROUTER_CDP_PORT`，缺省
  9222 仅为兼容旧契约）；非法值显式报错，不静默回缺省（红线 5）。

## 11. 只读采集不产生界面动作（2026-11-18，ADR-028）

- 用量/额度等只读采集的会话凭据走**浏览器级** `CdpChannel.storage_cookies(domain)`
  （`Storage.getCookies` + `/json/version` 的 `webSocketDebuggerUrl`）：不 `attach`
  页面、不 `open_activity`、不 `Target.createTarget`、不 `Page.bringToFront`。
- 历史事故：doubao 用量在无活动页时 `open_activity` 新建页面，客户端窗口被拉到
  前台——平台行「刷新」= `POST /platforms/{target}/import` 顺带 `collect_usage`，
  于是点刷新就跳豆包。
- 界面动作只属于用户显式触发的写路径：领取/签到、切号（`Page.bringToFront`）、
  dock 自动拉起（ADR-007 决策 5）。不得以「顺便采集」为由建页。
- Cookie 按连接器所需域过滤后再拼请求头；取不到会话 Cookie 显式报错（可能未登录），
  不静默空采。
- 保留导入顺带采集语义：修的是取 Cookie 的方式，不是删采集链路。
