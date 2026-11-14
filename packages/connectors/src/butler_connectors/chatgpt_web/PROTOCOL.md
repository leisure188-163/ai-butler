# chatgpt_web 协议字典 v1.0.0

> 来源：A1-04 §4.1 本机取证（2026-11-12，macOS 24.3.0 / Chrome 157）+ 公开
> next-auth 惯例。每条结论附验证日期与环境；**先改文档再改代码**（A2-02 §6）。

## 1. 端点清单

| method | path | 认证 | 验证状态 |
|---|---|---|---|
| GET | `https://chatgpt.com/api/auth/session` | Cookie（next-auth 会话令牌） | **待登录态补证**——2026-11-13 本机直连不通（无代理），未捕获未登录态形状；端点按 next-auth 惯例声明（A2-03 §7.1） |

## 2. 认证与凭据

- 凭据 kind：`browser_cookie`（信封 JSON，A2-03 §1）
- cookie 名单（2026-11-12 本机 Chrome 库实存）：`__Secure-next-auth.session-token.0/1`
  （Secure/HttpOnly）+ `oai-sc` + `oai-did` + `cf_clearance`
- **捕获名单 = 两段会话令牌**（next-auth 鉴权承载，分片 cookie）；`oai-*`/`cf_*`
  观察到但未捕获——数据最小化；探针若证明需要 → 先改本文与名单声明
- 有效期：两段令牌各自 expires_utc（WebKit 纪元）取最早者 → 凭据 expires_at

## 3. 关键请求形状

- 探针 = 纯 GET + `Cookie` 头（名单拼装，A2-03 §1），无签名/设备头申报
- Cloudflare 挑战（403 challenge）→ 探针如实 `NO_AUTH`，无对抗绕过（A1-04 §6）

## 4. 业务码字典（探针 = HTTP status，A2-03 §3）

| HTTP | 语义 | core Status |
|---|---|---|
| 200 | 会话有效 | （ok_status，映射 `ALREADY`） |
| 401 | 会话令牌被拒 | `EXPIRED` |
| 403 | CF 挑战/风控 | `NO_AUTH` |
| 其余 | 未注册 | UnknownEngineCode → FAILED + PROTOCOL_CHANGED |

## 5. 幂等与重试

- 探针只读，无幂等键（非领取类写动作）；导入（session.import）可重复扫，
  重导 = 覆盖式重存凭据 + 同身份幂等回放（ADR-011：首个凑齐 profile =
  `{target}:main` 存量卡位，后续 profile = 目录名 slug 键）

## 6. 已知风险

- 本机网络直连 chatgpt.com 不通——探针 FAILED（不可达 ≠ 会话失效，evidence
  已注明）；代理感知探针未做（A2-03 §7.6）
- CF 挑战 cookie（cf_clearance）生命周期短且绑定指纹——不捕获、不伪造

## 7. 取证记录

- 2026-11-12（mac 本机，A1-04 §4.1）：Chrome cookie 库 358+170 条全解零失败；
  会话令牌在库但已过期（「cookie 在但过期」天然样本）→ 导入语义 = 照常出卡
- 2026-11-13：`/api/auth/session` 未登录态取证未遂（网络不可达）——待登录态环境补证
- 2026-11-13（**Windows 真机验收**，Chrome 运行中）：库为现代布局
  `<profile>/Network/Cookies`（Chrome ≥96，声明补双布局候选——此前旧路径候选
  本机全落空误报「未发现 cookie 库」）；活动 Default 库锁死 → immutable 只读
  直开兜底 + 如实出账「关闭浏览器后重扫」，不注册账号；Local State 钥匙腿真
  DPAPI 实解（209B→32B）+ GCM 腿真钥匙 roundtrip PASS。**平台定性（A2-03
  §7.7）**：可读 Profile 1 的 124 条 cookie 全量 v20（Chrome 127+ 应用绑定
  加密）——本通道不做对抗解密，Windows 新版 Chrome 网页会话捕获如实落榜
- 2026-11-14（**mac 真机多 profile 取证**，A2-02 §9）：Chrome 双 profile
  （`Default`、`Profile 1`）cookie 库均实存名单内会话令牌
  `__Secure-next-auth.session-token.0/.1`——**多 profile 目录布局实证**；
  账号同一性未验（不解密不取明文，红线 5）
- 2026-11-14（**裁决落地**，[ADR-011](../../../../docs/adr/ADR-011-网页会话通道每profile一账户.md)）：
  每 profile 一账户槽接入 dock——首个凑齐 profile = `main`（存量卡位），
  后续 = 目录名 slug（本机即 `profile-1`）；同目录新旧布局去重；展示名带
  profile 目录事实（如「ChatGPT（Profile 1）」）。重复账号 → 重复槽由领取
  幂等 ALREADY 兜底，接受
