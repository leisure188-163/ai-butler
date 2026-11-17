---
name: adr-017-doubao-zero-bare-request
description: doubao detail 只读接口由连接器裸 httpx POST 改活动页上下文 fetch，全链路零裸请求。TRIGGER when 实现/评审 doubao 连接器、讨论签名/指纹风险或新增豆包出站请求时
version: "1.0.0"
level: must
---

# ADR-017 · doubao detail 改页面上下文 fetch，全链路零裸请求

- **状态**：Accepted
- **日期**：2026-11-17
- **决策者**：架构会话（用户当日拍板「今天做零裸请求改造」）
- **关联**：ADR-007（决策 3 本条修订其「唯一保留裸接口」口径）、
  doubao_cn PROTOCOL.md §1.2/§2/§2.1/§6、旧仓库 NOTE-04 §4.2–4.5（机理出处）

## 背景

ADR-007 当时保留 detail 只读裸 HTTP（「实测无害」）的依据是：受限会话下
detail 仍 `code=0`，且签名校验只针对写操作。三个后续事实推翻了「无害」：

1. **2026-11-16/17 账号级 702 事故链**：`710010702`「系统错误」连日不解，
   重装不复位、异机同号同败、同机他号成功——定性账号级服务侧写路径故障。
2. **旧 kit NOTE-04 §4.3 机理（亲证链）**：裸 HTTP 缺 `a_bogus`/`msToken` 签名
   → 服务端判异常流量 → 先会话级受限（重装可解）→ 反复裸请求**升级为账号级**
   （重装无效）→ 上次恢复靠「停裸请求 + 等待」，不是重装。
3. **升级路径可行性双机实证**：2026-11-16 Windows + 2026-11-17 mac（重装后
   环境）spike——活动页上下文里注入 `fetch`，请求 URL 被客户端网络栈自动补
   `msToken`/`a_bogus`（页面 JS 可见层之下签名，注入请求一视同仁），detail
   `code=0` 满数据。

结论：连接器每次 run 发 1–4 次裸 detail（全链路唯一非客户端指纹流量）是
会话受限→账号受限升级链的诱因之一，只读也不该留。

## 决策

**detail 只读查询改活动页上下文 fetch**（`Runtime.evaluate` +
`awaitPromise=True`，`ui_js._DETAIL_FETCH_JS`），流程要点：

1. 连接器只拼 URL 查询参数与 body（`campaign_group_code`），**不拼任何头**：
   Cookie/Origin/Referer/UA 由浏览器原生自带；`msToken`/`a_bogus` 由客户端
   网络栈自动补签——连接器零凭据处理面（原 `Network.getCookies` 现取路径删除）。
2. **非 2xx 语义保持**：JS 以哨兵键 `butler_http_status` 回传状态码，Python 侧
   转 `CdpError`——与旧裸 HTTP「非 2xx = 传输层失败」同语义；业务码判定只对
   2xx JSON 生效（PROTOCOL §2 不变）。
3. detail 与点击同生命周期：活动页不可达 = detail 不可发（PENDING/FAILED 如实
   落账）——**绝不退回裸请求兜底**（红线 5，PROTOCOL §3 既有语义）。
4. build_port 契约签名保留 `transport` 形参（registry 统一传参），但豆包端口
   不再使用（同 `vault` 先例）。

**明确排除项**：

- `usage.py`（M2 用量端口）的 quota/records 裸读**本条不改**（未投产、未裁决）；
  若 M2 落地生产，须同法走页面 fetch 或届时另裁（PROTOCOL §7.3 已记约束）。
- 签到写操作（checkin）维持界面受信任点击——客户端 JS 自己发写请求，本条
  不涉及。

## 后果

**正面**：

- 全链路四类业务流量全部客户端指纹：probe（本机 CDP HTTP）/ detail（页面
  fetch 自动补签）/ checkin（客户端自发）/ 复查（同 detail）——升级链诱因清零
- 零凭据面更彻底：连接器不再读 Cookie、不再拼 UA/头，凭据明文不进任何
  连接器代码路径
- `NO_AUTH` 判定更真实：登录态过期由页面会话的业务码直接反映，不再依赖
  手工拼接的 Cookie 头形状

**负面/约束**：

- detail 依赖活动页可达（与点击同生命周期）——活动页建页失败时 detail 一并
  不可用，无裸 HTTP 兜底（设计意图，不是缺陷；兜底 = PENDING/FAILED 如实落账）
- 页面 fetch 结果经 `returnByValue` 序列化回传——detail 大 payload（数十 KB）
  序列化有毫秒级开销，25s 求值上限（`_DETAIL_WAIT_SECONDS`）实测余量充足
- 极端风控理论上可从「输入管线合成事件」分辨 CDP 点击——但 702 事故证据链
  （本人手工点同败 / 他号同机成功 / 重装不复位）已排除点击方式为肇因
