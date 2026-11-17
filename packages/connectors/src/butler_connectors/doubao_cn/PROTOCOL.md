# PROTOCOL · 豆包 CN（doubao_cn 连接器协议字典）

> 本文件是**逆向结论的归宿**（A0-01 §2.1）：端点 / CDP 编排 / 判定 / 已知风险。
> 来源 = 旧仓库取证笔记 NOTE-04（2026-11-02~11-08）+ 本机 spike 实证（2026-11-11，
> Windows，豆包 2.35.8 / Chromium 147）；实现走 **CDP 界面通道端口实现**
> （ADR-007），不搬代码。每条结论附取证日期；
> **适配器里不允许出现本文没有的端点与编排**。

## 1. 身份与凭据

| 项 | 事实 | 取证 |
|---|---|---|
| 产品 | 豆包电脑版（字节跳动，Electron/Chromium 147 壳） | 2026-11-02 |
| 权益面 | 签到领额度（每日 +200，周一翻倍）+ 任务/里程碑奖励（12 tasks + 3 milestones，M2 清扫） | 2026-11-11 |
| 数据目录 | `%LOCALAPPDATA%/Doubao/User Data/{Default,Profile N}`（登录态 = Chromium Cookie，分库存放；活动面板 webview 用 `Profile N`，运行期独占锁读不了，`Default` 常为过期旧会话） | 2026-11-02 |
| Cookie 加密 | 标准 Chromium v10（DPAPI + AES-256-GCM）+ **32 字节应用层前缀剥离**；macOS 文件解密未破解（如实 UNSUPPORTED）——但本设计**不读文件库**（见 §6 通道裁决） | 2026-11-02 |
| **会话本质** | 界面通道下**没有可注入的凭据**——会话 = 运行中的客户端进程本身（签名 `a_bogus`/`msToken` 由客户端 JS 生成）；vault 零凭据申报 | 2026-11-11（ADR-007 裁决） |
| 客户端定位 | exe 候选：`HKCU\...\Uninstall\Doubao` 的 `DisplayIcon` 父目录 + `app\Doubao.exe`（本机 `D:\software\ai-tools\Doubao\app\Doubao.exe`；`%LOCALAPPDATA%\Doubao\Application` 为空，勿用）；进程名 `Doubao.exe`。**实测定稿（2026-11-11 验收）**：条目匹配按**子键名** `Doubao*` 优先，DisplayName 是中文 `豆包`（非 `Doubao` 开头，勿按 DisplayName 前缀匹配）；`DisplayIcon` 带引号且指向 `icon.ico`（如 `"D:\...\Doubao\icon.ico"`）——剥引号后取父目录 | 2026-11-11 |
| 版本来源 | Windows：卸载注册表 `DisplayVersion`（匹配口径同上：子键名 `Doubao*` 或 DisplayName `Doubao*`/`豆包`，本机 `2.35.8`；环境变量 `DOUBAO_VERSION` 可覆盖）；macOS：`Info.plist CFBundleShortVersionString`。读不到**显式报错**——旧值正是故障本身（写死版本在客户端升级后回 710010702） | 2026-11-11 |
| version_code | `主*10000+次*100+修订`（2.35.8 → 23508，本机实证有效）；exe 文件版本是 Chromium 内核号（147.0.7727.149），**不是**应用版本 | 2026-11-11 |
| CDP 端口 | `--remote-debugging-port`，默认 9222；`DOUBAO_CDP_PORT` 覆盖口保留 | 2026-11-02 |

### 1.1 本机 spike 实证（2026-11-11，Windows / 豆包 2.35.8）

- 杀无端口实例 → 带 `--remote-debugging-port=9222` 重启 → `/json/version` 通；
  `Browser` 字段只报 `Chrome/147.0.7727.149`——**probe 不得按它校验身份**（旧版
  曾报 doubao 字样，以 target URL 域过滤保身份）
- `Target.createTarget` 开活动页成功；`/json/new` 不可行（会被客户端吞）
- 活动页 target **type = `webview`**（客户端自开面板）与 `page`（createTarget 所开）
  并存——目标匹配**按域 `doubao.com` 不限 type**；`doubao://` 内部页必须排除
- `Network.getCookies` 现取 30 cookie（sessionid 等全齐）；WebSocket 握手必须
  `suppress_origin=True`（Chromium 111+ 拒绝带 Origin 的 CDP 握手）
- detail 只读全链通：`code=0`、`checked_in_today=true`、`last_checkin_date=2026-11-11`、
  `continuous_days=5`（跨设备会话同步——mac 端已领，Windows detail 如实反映）

### 1.2 页内 fetch 取证（2026-11-16，Windows / 豆包 2.36.8，CDP Network spike）

- **页面 fetch 拦截器自动签名实证**：活动页上下文里裸 `fetch` 发 detail，线上
  抓到的实际请求 query 自动追加了 `msToken` + `a_bogus`（我们没传）——页面级
  拦截（`byted_acrawler` 全局存在）对 doubao API 请求自动签名。**ADR-007 §6
  预留的「页面内 Runtime.evaluate 同源 fetch」升级路径可行性坐实**：签名由
  页面 JS 自产，evaluate 的 fetch 即合法签名请求。签到写接口（landing/checkin）
  的请求形状尚待取证（取证当日点击已生效、按钮消失，未捕获写请求）——取证后
  可评估「evaluate fetch 签到」替代受信任点击
- **Runtime.evaluate 必须 `awaitPromise=True`**：async 表达式不传该参数，
  `returnByValue` 把未落定的 Promise 序列化成 `{}`（cdp.py `evaluate` 已加
  `await_promise` 形参，默认 False 向后兼容）
- **复查时序实证（当日 FAILED 误判根因）**：点击送达、签到接口回 code=0，
  3s 落定后复查 `checked_in_today=false` 判 FAILED；spike 首次点击实际已签上
  （按钮随后消失、复查 `continuous_days=10`）——**点击生效但状态翻转有延迟**。
  处置 = 点击后复查退避 3 次（3s/5s/8s，`_RECHECK_DELAYS`）再判 FAILED

## 2. 端点族

Base：`https://www.doubao.com`

| 端点 | 方法 | 说明 |
|---|---|---|
| `/alice/ug/campaign/v3/detail/` | POST | 活动详情（**只读，M1 唯一裸 HTTP 接口**）：`{"campaign_group_code": "pc_incentive_task_mvp_v3"}`；权威判定源（§3） |
| `/alice/ug/campaign/landing/checkin/` | POST | 签到（幂等）——**M1 不发**（界面通道由客户端 JS 自己发） |
| `/alice/ug/campaign/item/reward/claim/` | POST | 任务奖励领取——**M2 清扫再裁**（裸写有会话受限风险） |

公共约定（detail 用）：

- 公共查询参数**缺一不可**：`version_code=<派生>&language=zh&device_platform=web&doubao_device_platform=web&aid=497858&real_aid=497858&pkg_type=release_version`；`version_code` 写死会在客户端升级后回 710010702（旧系统 NOTE-04 §4.5 复盘）
- 头：`Cookie`（CDP 现取，按 name 去重）、`Content-Type: application/json`、`Origin`、`Referer: https://www.doubao.com/pc/agent-explore`、`User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) … Chrome/147.0.0.0 Safari/537.36 SamanthaDoubao/<version>`（spike 实证串）
- 业务码：`0`=ok；`2`=campaign not found（**活动换季**——更新声明的 campaign 常量）；`710012001`=登录过期 → NO_AUTH（旧系统按 `710012*` 前缀判过期）；`710010702`=system error（**三义**：请求不合法/会话被降权/服务端故障——界面通道下签名合法仍 702 = 后两者，不猜，指引手工点一次判定）。**2026-11-17 真机补证**：客户端自己右侧「立即签到」发出的 XHR 也返回 `710010702`（`version_code=20800`、`aid=582478`，带完整 `msToken/a_bogus`），说明 702 不是本连接器页面通道/参数导致；遇到 702 停止连续点击，等平台恢复或重启客户端后再试。
- **detail 判定字段路径**：`data.tasks[]` 里 `campaign_code=="daily_signin"` 的项 → `.daily_checkin` 子结构：`checked_in_today`（布尔权威）/`reward.reward_amount`/`continuous_days`/`last_checkin_date`（2026-11-11 旧仓库 oracle 提炼 + spike 实证）
- 本机 127.0.0.1 的 CDP HTTP 探测必须**绕系统代理**（旧系统实测：系统代理开着时 urllib 会把调试端口请求发给代理，直连失败）

## 3. 结果判定（detail 权威，不信签到接口返回）

| 字段事实 | → Status | 备注 |
|---|---|---|
| CDP probe 不可达 | **PENDING** + 指引（停靠可自动拉起） | 客户端没带调试端口跑——**绝不退回裸请求**（旧系统 auto 终态语义） |
| `tasks[daily_signin].daily_checkin.checked_in_today == true` | ALREADY | 权威判定；不发点击；evidence 可带连签天数 |
| false → 界面点击 → 退避复查（3s/5s/8s）任一次 true | CLAIMED | evidence 记点击按钮文案 + 复查第 n 次（2026-11-16：状态翻转有延迟，单次即查会误判） |
| false → 界面点击 → 退避复查 3 次全 false | FAILED | 点击未生效（旧系统同型话术：点击已送达但状态未变更——服务端/账号侧异常，可手工点一次确认） |
| detail `710012001` | NO_AUTH | 重开客户端重新登录后重新停靠 |
| detail `code=2` | FAILED + PROTOCOL_CHANGED 事件 | 活动换季，更新 adapter 的 campaign 常量 |
| detail `710010702` | FAILED + 指引 | 三义码不猜：手工点一次可判别"会话降权 vs 平台故障" |
| 未知形状 / 找不到按钮 / 建页失败 | FAILED | 协议事故显式报，绝不静默（红线 5）；evidence 带页面文本摘要（脱敏） |

方言注册口径（ADR-004 装载期）：`doubao_cn` 方言 = `{"710012001": NO_AUTH, "710010702": FAILED}`；
`code=2` **刻意不注册**——未知码走 UnknownEngineCode → 用例层统一转 FAILED + PROTOCOL_CHANGED
事件（与声明式连接器同一条协议变更探测路径）。

## 4. 幂等与窗口

- 签到按**自然日**结算（`checkin_date` / `last_checkin_date` = 日历日）——`refresh_at: "00:00"`
- CDP 点击是幂等安全操作（checked_in_today=true 时不点击，由 detail 复查把门）
- detail 只读无副作用；网络类失败可安全重试
- 引擎幂等键 = `(provision.run, account_id, 窗口)`，与 trae/qoder 同型（底座）

## 5. 行为对照验收（实现完成后执行，A0-01 §2.2）

| 场景 | 期望 | 结果 |
|---|---|---|
| 已签窗口内再触发 | ALREADY（detail 权威，不点击） | ✅ 2026-11-11：ALREADY，evidence「detail 权威判定：今日已签（连签 5 天）」（mac 签到跨设备同步可见），全程零点击（run 2ef5d7d8） |
| 未签 → 界面点击 | 点击 → 复查 → CLAIMED | ⚪ 留次日 00:00 后未签窗口验证（09:15 调度班次或手动）；判定表离线测试全覆盖（test_click_then_recheck_true_is_claimed 等） |
| CDP 不可达 | PENDING + 指引，零裸请求 | ✅ 2026-11-11：PENDING（signal=quiet）+ repair_action_id=dock + 端口指引（WinError 10061 如实上账）；当日 ALREADY 幂等回放命中，PENDING 用全新台账复验 |
| 登录过期 710012001 | NO_AUTH + 修复提示 | ⚪ 离线覆盖（真机需真实过期会话，难构造；判定路径 test_detail_710012001_is_no_auth_with_dock_hint） |
| 活动换季 code=2 | FAILED + PROTOCOL_CHANGED 事件 | ⚪ 离线覆盖（code=2 刻意不注册方言 → UnknownEngineCode → 用例层 FAILED + 事件，test_engine_publishes_protocol_changed_on_code_2 含引擎联动） |
| dock 体检（客户端没带端口） | 自动拉起 → probe 就绪 | ✅ 2026-11-11：杀尽退出后 dock → 注册表定位 exe → 带端口拉起 → probe 就绪 → accounts=["doubao_cn:main"] issues=[]。**验收抓 1 真 bug 已修**：DisplayName 是中文「豆包」且 DisplayIcon 带引号指 icon.ico——改按子键名 Doubao* 匹配 + 剥引号（9191182，PROTOCOL §1 定稿） |
| 点击后状态翻转延迟 | 退避复查命中 CLAIMED | ⚪ 离线全覆盖（test_click_recheck_retry_then_true_is_claimed / test_click_recheck_transport_error_then_true_is_claimed）；2026-11-16 真机事故根因（两次 FAILED 实为已签，复查过快）已按 §1.2 修复，待下一未签班次真机复验 |

## 9. 切号协议与多账户身份（2026-11-16 初版 → 2026-11-17 修订，ADR-007 决策 7→8）

- **切号入口取证（2026-11-17 修订）**：双账户注册后，左下角账户 chip（头像
  img + 昵称按钮）点击 → Radix popper 弹层含**切换列表**（当前账户 + 其他
  已注册账户各行，行文本**精确等于**昵称，真机坐标 chip y≈836、行 y≈666/704）
  ——11-16「无一键切换列表」只在单账户时期成立，决策 7 前提已变化。弹层须先
  `Page.bringToFront` 聚焦窗口（失焦点击不开，11-16 实证）；「添加账号」仍
  直通独立登录页 target（`doubao://doubao-login/login?device_flow=enabled`，
  手机号/飞书/抖音/扫码四种方式），「退出登录」绝不触碰
- **单会话存活语义（2026-11-17 用户确认）**：切换后旧 chat target 消亡、新
  target 承载新会话——切号点击后旧连接即失效，翻转验证必须重枚举 targets
  重读身份；11-16 观测的「双 chat target 并存」属过渡态，非常驻
- **自动切号编排（switch.py，ADR-007 决策 8）**：resolve_target_identity
  （登记簿定位 sec_uid+昵称）→ switch_session（chip → 精确匹配昵称行 →
  受信任点击三连 → 20s 轮询身份翻转，超时显式 SwitchError）→ adapter 复核
  活跃身份与目标一致 → **旧活动页关净**（cdp.py 新原语 `Target.closeTarget`，
  target 已不在 = 关净达成同语义不报错）→ `_activity_conn` 开新页（Cookie
  现取 = 新会话）→ 正常编排。切号留痕进台账 evidence 首位
- **身份登记簿**：dock 采集后持久化 `~/.butler/doubao_identity.json`
  （`DOUBAO_IDENTITY_PATH` 可覆盖）：`main_sec_uid`/`main_nickname` +
  `others[{sec_uid, nickname, account_key}]`——非 main 账户的切号定位依据
  （account_key = SHA256 前 8 位前缀 `u`，单向不可逆）；采集为空不覆盖旧簿。
  本项目 main = 逍遥酒鬼（2026-11-16 用户确认），B = Leisure520
  （`doubao_cn:u66b1e22d`）
- **守卫语义（2026-11-17 修订）**：run 目标非活跃 → 自动切号 → 复核 → 通过
  才编排；切号失败/复核不符/旧活动页关不动 → PENDING（修复提示分语境：
  身份不符 ≠ 端口不可达），**绝不盲签**（A2-02 §6 红线）。main 基线命中任一
  chat target 即视为活跃（cookie 会话实证口径，不变）。dock/usage 维持
  只监控不切号
- **硬边界（不自动化，ADR-007 决策 8）**：登录态过期重登（扫码/手机号）与
  「添加账号」——人工参与；ADR-015 失效可见可修 + 停止自动重试语义不变

> oracle = 旧仓库 `auto-signin-kit doubao status/auto`（mac 上已验证可正常领取）。

## 6. 已知风险与通道裁决（ADR-007）

- **通道裁决（本设计的根）**：①**裸 HTTP 写操作禁令**——缺 `a_bogus`/`msToken`
  签名的连续裸请求会把会话搞受限（连手工点都失败，重装才恢复；旧系统
  2026-11-07/11-08 两次事故），M1 绝不实现裸写通道；②detail 只读裸 HTTP
  实测无害（受限会话下 detail 仍 code=0），M1 唯一保留的裸接口——若未来
  detail 也强校验签名，升级路径 = 页面内 Runtime.evaluate 同源 fetch 或读界面；
  ③文件解 Cookie 不做（Profile N 独占锁 + Default 过期态 + 界面通道用不上）
- **自动拉起**（用户裁决 2026-11-11）：dock 体检发现客户端无端口运行 → 杀
  实例 → 带端口重启 → 轮询就绪；拉起失败/找不到 exe → 显式 issue 给指引。
  M1 自动拉起仅 Windows；mac probe 可达即过（手动带端口启动），不可达出
  issue 指引手动，不静默。**taskkill exit=128 = 进程已不在**（2026-11-13
  Windows 真机实证：探得与击杀间隙退出，taskkill 报「没有找到进程」）——
  杀净语义已达成不报错，与 mac 分支 ProcessLookupError 宽容同事实同语义
  （此前按失败抛出导致 dock 停靠扫描异常，已修）
- **点击编排 oracle**（2026-11-11 旧仓库 uiaction 提炼，语义对齐不搬码）：
  ① 按钮文案**精确匹配** `("立即签到", "今日签到", "签到")`——模糊匹配会误点
  "签到领额度"类标题；② 候选元素 `children.length <= 2` 且
  `pointerEvents !== 'none'`；③ 视口找不到时按 `innerHeight*0.7` 步进滚动
  扫找，命中后 `scrollIntoView({block:'center'})` 取中心坐标；④ **受信任点击
  三连**：mouseMoved → mousePressed(button=left, clickCount=1) → mouseReleased
  （前端若校验 isTrusted，合成事件会被忽略）；⑤ 点击后 settle ≥3s 等客户端
  SDK 发完请求，再 detail 复查——**复查退避 3 次（3s/5s/8s）**（2026-11-16
  实证状态翻转有延迟，单次即查误判 FAILED）；⑥ 找按钮重试 ≤3 次（活动页可能还在加载）
- **活动页优选**：target 匹配按域 `doubao.com` 不限 type（`doubao://` 内部页
  排除，2026-11-07 实测内部页同样含 "doubao" 字样）；多个命中时 url 含
  `campaign`/`agent-explore`/`incentive` 者优先，否则取第一个
- **Cookie 现取口径**：直接在活动页连接上 `Network.getCookies`，按 name 去重；
  会话过期与否由 detail 业务码判定（cookie 在不等于登录态有效）
- 换季预案：`campaign_group_code` 是 adapter 模块常量（`CAMPAIGN_GROUP_CODE`），
  服务端换 scene 时 detail 报 code=2 → FAILED + PROTOCOL_CHANGED 事件，更新
  常量即可
- 会话受限唯一恢复手段 = 重装客户端（新 session）；"手工点一次"是判别器
- msToken 等 cookie 有时效——每次运行时 CDP 现取，绝不持久化（零凭据入 vault）

## 7. 用量取证（2026-11-12，M2 真机只读 spike，客户端 2.36.6 / Windows）

> 01-M2-用量取证清单 §4 四项全落；只读取证（detail/quota-records 只读试探、
> CDP DOM 只读、IndexedDB 拷读），Cookie 现取未持久化。注：取证当日客户端
> 已从 2.35.8 自动更新至 2.36.6，请求形状无变化。

### 7.1 额度余额：detail 无余额字段，UI 无余额展示

- detail 全形状（data: campaign_code/example_cases/fission_campaign/
  milestones/progress/tasks）里**只有奖励面额**：
  tasks/milestones 的 `reward_summaries[]{reward_type: "quota_grant",
  reward_amount}`（任务 100/项，里程碑 1300/500/200）+ 活动总额度池
  `progress.total_amount`（= 累计可获得上限）——**无余额/已用量字段**
- 资源串全族（ai-views bundle 13 端点）无 balance/剩余额度端点；
  主聊天页 DOM 零额度元素；活动页 UI 只展示「累计获得额度 N 点」
  （= detail.total_amount）

### 7.2 新只读端点：quota/records = 入账流水

`POST /alice/ug/campaign/quota/records/`，body `{cursor: "", page_size: N}`：

- 响应 `data{has_more, next_cursor, records[]}`，逐条
  `{amount, create_time_ms, record_id, task_code, task_name, unit: "POINT"}`
- **amount 形状变迁（2026-11-12 真机复核）**：取证时为 JSON number，复检 16/16
  全为**数字串**（如 `'200'`）——适配器收编数字串（workbuddy *Precise 同款先例），
  非数字串仍显式拒绝
- 本机全量 15 条（has_more=false）**全为正值** = **入账 ledger**，无消耗记录；
  消耗量（tokens/credits 消耗）双通道 UNSUPPORTED
- 签到 +200 关系实证：`task_code: "daily_signin"` amount=200，
  **周一 400**（11-02/11-09 两个周一双实证），断签无补登记录
- cursor 为 base64 JSON `{"create_time", "id"}`

### 7.3 ADR-007 遗留三选一：裁决材料齐（倾向「detail 裸读，不做 CDP 读用量」）

CDP DOM/截图实证（agent-explore 活动页 + doubao-chat 主聊天页）：界面能读到
的额度信息只有「累计获得额度」（与 detail.total_amount 完全重复）——**CDP 读
用量无增量价值**；用量通道建议 = detail 裸读（面额/活动池）+ quota/records
裸读（入账流水），CDP 通道保留给签到点击（M1 既有）。

### 7.4 本地数据源

- IndexedDB `chrome_doubao-launcher_0.indexeddb.leveldb`：
  `context_window_usage`（per-session 上下文占用：
  `{system_prompt, messages, skills, tools, total_window_size: 256000}`）——
  语义与 qoder 同款（上下文仪表非计费）
- Local Storage 无结构化额度键（仅 `commerce_credit_config_enable` 开关、
  `quota_exhausted` 零散碎片）；credits 余额无本地存储

## 8. 多开取证（2026-11-14，mac 运行态实证）

> 结论：**客户端单实例锁为 app 级，多开不可行**——多账号 = 无据（红线 5，
> 未推断）；现行「单账号 `main` + CDP 端口单值」模型正确，无需改。

- 基线：本机豆包正以 `--remote-debugging-port=9222` 运行（主进程
  `/Applications/Doubao.app/Contents/MacOS/Doubao`，监听进程 = "Doubao
  Browser" helper）；默认数据目录 `~/Library/Application Support/Doubao/`
  单 profile（`Default/` + `Local State`，无 Profile N）
- 实验 ①：第二实例带**独立临时 user-data-dir** + `--remote-debugging-port=9223`
  → 秒退；临时目录只建 `sdk_storage`/`update_data`（**无 Chromium profile
  结构 = `--user-data-dir` 被客户端吞**），9223 不监听
- 实验 ②（对照）：第二实例沿用默认目录 + `--remote-debugging-port=9224`
  → 秒退 exit=0（单实例转发的典型语义：激活既有实例后自己退出），9224
  不监听；全程原实例 9222 应答如常、进程清单不变
- 推论：多账号需要「多实例各带独立数据目录 + 端口」——客户端两个前提都不
  成立；Windows 侧既有实证同型（dock 拉起前必须杀净无端口实例，§6）

## 9. 推理通道取证（2026-11-14，mac 侧 · R4 G0）

> 结论：CDP 通道已实证（ADR-007）可用作**UI 驱动的推理转发**；但发消息 =
> 写动作（消耗 credits），取证纪律禁触——转发可行性与流式形状的最终
> 验证归 G5，且需用户明确授权以其账户发测试消息。

- CDP 零凭据通道（端口单值 9222，§8 单实例锁）——网关可驱动：会话拉起/
  输入注入/回复 DOM 读取，与签到编排同款手法
- 网络层形状（HTTP API/签名）未观察：a_bogus 类签名 = 裸写 UNSUPPORTED
  （ADR-007），不重开
- 流式：回复 DOM 渐进渲染可读（结构与选择器未取证）
