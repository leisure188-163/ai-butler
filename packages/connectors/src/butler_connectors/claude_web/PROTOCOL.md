# claude_web 协议字典 v1.0.0

> 来源：A1-04 §4.1 本机取证（2026-11-12）+ 2026-11-13 未登录态 curl 取证。
> **cookie 名单待登录态环境补证**（A1-04 §8.3 挂账）——本机两 profile 均未登录。

## 1. 端点清单

| method | path | 认证 | 验证状态 |
|---|---|---|---|
| GET | `https://claude.ai/api/auth/session` | Cookie（next-auth 会话令牌） | 2026-11-13 未登录态实取：HTTP 403（region，见 §6）——登录态 200 形状待补证 |

## 2. 认证与凭据

- 凭据 kind：`browser_cookie`（信封 JSON，A2-03 §1）
- cookie 名单：**待补证**。首批按 next-auth Secure 惯例声明
  `__Secure-next-auth.session-token`；真名以有登录态真机取证为准
- 有效期：名单内 cookie 最早 expires_utc → 凭据 expires_at

## 3. 关键请求形状

- 探针 = 纯 GET + `Cookie` 头；无签名/设备头申报
- 遇风控挑战如实 `NO_AUTH`，无对抗绕过（A1-04 §6）

## 4. 业务码字典（探针 = HTTP status，A2-03 §3）

| HTTP | 语义 | core Status |
|---|---|---|
| 200 | 会话有效 | （ok_status，映射 `ALREADY`） |
| 401 | 会话令牌被拒 | `EXPIRED` |
| 403 | 挑战/风控/区域 | `NO_AUTH`（区域阻断经 evidence 摘要区分，§6） |
| 其余 | 未注册 | UnknownEngineCode → FAILED + PROTOCOL_CHANGED |

## 5. 幂等与重试

- 探针只读无幂等键；导入可重复扫，重导 = 覆盖式重存 + 复用卡位

## 6. 已知风险

- 本机无 claude.ai 登录态：2026-11-14 mac 真机查证，Chrome 双 profile
  （`Default`、`Profile 1`）cookie 库均无 claude.ai 行——最小 cookie 名单
  补证维持挂账（换有登录态环境取证）

- **区域阻断（2026-11-13 本机实取）**：未登录/受限网络 GET 均得
  `403 + {"type":"error","error":{"type":"permission_error","details":{"error_code":"region_unavailable"}}}`
  ——探针映射 `NO_AUTH`，evidence 摘要带出 `permission_error/region_unavailable`
  区分「区域不可达」与「会话失效」；受限网络恒 NO_AUTH（A2-03 §7.2）
- 导入面不受影响（读本机 Chrome 库，零网络）

## 7. 取证记录

- 2026-11-12（mac 本机，A1-04 §4.1）：两 Chrome profile 均无 Claude 会话
  cookie（「未登录」天然样本）→ 导入语义 = 如实落榜不注册
- 2026-11-13：`/api/auth/session` 未登录态 = 403 region_unavailable（curl，
  只读取证，响应体已删）
- 2026-11-13（**Windows 真机验收**，Chrome 运行中）：与 chatgpt_web 同批次
  （A2-03 §7.3/§7.7）——现代布局候选补齐、活动库锁死如实出账、钥匙/GCM 腿
  真机 PASS；本机 profile 无 claude.ai cookie（未登录语义真机复证）；
  v20 应用绑定加密平台定性同见 chatgpt_web 取证记录
