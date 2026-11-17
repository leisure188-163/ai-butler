---
name: adr-005-doubao-cdp
description: doubao 接入形状 = CDP 界面通道端口实现 + cdp_probe dock kind + 零凭据 vault；裸 HTTP 写操作禁令。TRIGGER when 实现 doubao/评估 CDP 类连接器/dock 形态裁决时
version: "1.0.0"
level: must
---

# ADR-007 · doubao 接入形状 = CDP 界面通道端口实现，dock = cdp_probe 体检

- **状态**：Accepted
- **日期**：2026-11-11
- **决策者**：架构会话（用户三项裁决：dock 体检 / 自动拉起 / 首期不做清扫）
- **关联**：A2-02 §3（端口实现合法形态）、§8（CDP 测试边界）、ADR-006（排除项
  "doubao dock 形态届时另裁"的落定）、doubao_cn PROTOCOL.md、旧仓库 NOTE-04

## 背景

豆包签到与 trae/qoder 形状根本不同：接口签名（`a_bogus`/`msToken`）只有客户端
JS 能生成，**裸 HTTP 写操作有实证危害**（连续裸请求把会话搞受限——连手工点击
都失败，唯一恢复 = 重装客户端；旧系统 2026-11-07/11-08 两次事故）。旧系统
终态策略 = 界面通道为主（CDP 受信任点击），客户端不可达 → PENDING 跳过。

本机 spike（2026-11-11）实证全链可行：exe 定位（HKCU 卸载注册表）→ 带端口
拉起 → CDP probe → createTarget 开活动页（type=webview）→ Cookie 现取 →
detail 只读 code=0。

## 决策

1. **接入形态 = core 端口实现**（A2-02 §3 唯一合法 per-app 形态）：
   `DoubaoCdpProvisionPort` 只实现 `capabilities()` + `run()`——dock/幂等/
   调度/审计/台账全是底座的。CDP 会话原语（probe / targets / createTarget /
   evaluate / 受信任点击 / 取 Cookie）下沉为 connectors 包通用模块 `cdp.py`
   （可注入端口，未来 Electron 类客户端共享）——豆包专属的只有编排
   （找按钮/点击/复查）。
2. **dock 形态 = 新通用 kind「cdp_probe」**（环境体检，零凭据入 vault）：
   probe `/json/version`（不按 Browser 字段验身份）→ 可达即过；不可达且声明
   `ensure_running` → 定位 exe（HKCU 卸载注册表 `Uninstall\Doubao`）→ 杀无端口
   实例 → 带 `--remote-debugging-port` 重启 → 轮询就绪（超时显式 issue）。
   **豆包登录态 = 运行中的客户端进程本身**，没有可注入凭据——vault 最小授权
   退化为零申报（`credential.kinds: []`）；Cookie 运行时 CDP 现取现用，
   绝不持久化。
3. **通道裁决**：首期只实现界面通道 + detail 只读复查（裸 HTTP 唯一保留接口，
   实测无害；签名校验若未来收紧 → 升级页面内 fetch，届时另裁）。**裸写禁令**：
   checkin/claim 一律不裸发——checkin 由客户端 JS 自己发（我们只负责把用户
   "点一下"），claim（任务清扫）M2 另裁（界面点击或取证后裸发）。
4. **结果语义**：CDP 不可达 = **PENDING** + 指引（不是 FAILED——客户端没跑是
   暂态，不是事故；旧系统 _skip_result 同语义）；detail 权威判定
   （`checked_in_today` / `task_status`），不信签到接口自己的返回。
5. **自动拉起**（用户裁决）：dock 承担"把客户端带进签到模式"——杀无端口实例
   前置条件 = 用户显式触发 dock；调度触发的 run() 绝不杀进程（只 PENDING）。
6. **复查退避 + 页内 fetch 路径定档**（2026-11-16 修订，真机取证 PROTOCOL §1.2）：
   ①点击后复查改为**退避 3 次**（3s/5s/8s）再判 FAILED——当日真机实证点击
   生效但 `checked_in_today` 翻转有延迟，单次即查误判 FAILED；②页面 fetch
   拦截器**自动签名**实证（裸 fetch 被 `byted_acrawler` 拦截补 `msToken`/
   `a_bogus`）——决策 3 预留的「页面内 evaluate fetch」升级路径可行性坐实，
   签到写接口形状待下一未签班次取证，取证齐再裁是否替代受信任点击；
   **裸 HTTP 写禁令不变**（写操作仍在界面通道内）。
7. **切号不自动化，身份守卫纳管双账户**（2026-11-16，真机取证 PROTOCOL §9；
   **2026-11-17 经决策 8 修订：会话级切号改自动化，本条登录边界与守卫红线仍有效**）：
   客户端菜单无一键切换列表，「添加账号」直通登录页（手机号/扫码需人工参与）
   ——全自动切号不可行且不猜（用户确认非飞书账号）。裁决：**只监控不切号**——
   identity.py 只读身份判定（`sec_user_id` + chip 昵称），run/dock/usage 三处
   守卫，目标账户非活跃即 PENDING 提示人工切号，**绝不签错账户**；第二账户由
   dock 如实登记（account_key = sec_uid 派生）。双会话并存下 main 命中任一
   chat target 即放行（cookie 会话实证口径），B 在 main 在场时保守 PENDING。
8. **会话级自动切号放行，登录仍人工**（2026-11-17 用户裁决，真机取证 PROTOCOL §9
   修订）：双账户注册后头像菜单**存在切换列表**——决策 7 的「无一键切换列表」
   取证只在单账户时期成立，前提已变化；切换 = 单会话存活（用户确认：切号后旧
   target 消亡）。落地 switch.py：`Page.bringToFront` 聚焦 → 点头像 chip →
   **精确匹配昵称行**（同 §6 按钮纪律，杜绝误点「添加账号」/「退出登录」）→
   受信任点击 → 轮询身份翻转（20s 显式超时）→ adapter 复核活跃身份 →
   **旧活动页关净**（Target.closeTarget；残留旧账户 Cookie 的活动页附着即
   签错账户）→ 正常编排。切号失败/复核不符/旧页关不动 → PENDING 绝不盲签；
   切号留痕进台账 evidence。身份登记簿（main 基线 + others）持久化作切号
   定位依据，dock 采集维护（空采集不覆盖）。**硬边界**：登录态过期重登与
   「添加账号」直通登录页仍人工（扫码/手机号），ADR-015 失效可见可修不变。

## 排除项

- 任务清扫（tasks/milestones 领取）首期不做——裸 HTTP claim 有会话受限风险、
  界面点击编排复杂（按钮位置不稳定）；M2 结合用量采集另裁
- 文件解 Cookie（多 profile 合并 + 32B 前缀剥离）不做——界面通道用不上，
  且 Profile N 运行期独占锁、Default 常为过期态
- macOS 文件解密 UNSUPPORTED 维持（本设计不依赖文件解密，mac 天然同链路）

## 后果

**正面**：

- 零凭据入 vault = 攻击面最小化；会话生命周期跟随客户端，无过期轮换问题
- cdp_probe / cdp.py 是通用件——未来任何 Electron 客户端（如 CDP 类风控）
  复用同一套原语与 dock kind，kind 收敛原则保持
- 界面通道 = 用户手工能领的，工具就能领（签名/设备指纹由客户端 JS 自己生成）

**负面/约束**：

- 用户侧成本：豆包客户端须带调试端口常驻（dock 自动拉起缓解，但调度班次
  之间若用户手动关了客户端，当班 PENDING）
- detail 裸 HTTP 是唯一的签名校验风险敞口（只读、实测无害，升级路径已记）
- 自动拉起会重启用户客户端（丢窗口状态）——已限定在显式 dock 触发路径
