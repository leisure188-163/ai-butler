---
name: butler-adr-014
description: 本地服务浏览器边界 = CORS 白名单 + OriginGuard 服务端硬拦截；密钥权限 Windows 走 icacls。TRIGGER when 讨论主控 server 鉴权/跨域/本地安全边界时
version: "1.0.0"
level: must
---

# ADR-014 · 本地服务浏览器边界：CORS 白名单 + Origin 服务端硬拦截

- **状态**：Accepted
- **日期**：2026-11-16
- **决策者**：butler 维护者
- **关联**：A1-02 §8（鉴权差异点）、ADR-012 裁决 4（网关 key 权限）、A4-01 §5

## 背景

主控 server 是**无鉴权的本地 HTTP 服务**（127.0.0.1:8000，A1-02 §8 既定：
单用户、不设 JWT）。原实现 `CORSMiddleware(allow_origins=["*"])`，等于把
本机 API 的读权限向任意网页开放。

复盘后确认这是**两层独立的漏洞**，只修一层不够：

1. **CORS 不阻止请求送达，只阻止读响应**。恶意页面可用"简单请求"（表单型
   POST、无预检）打到 `/api/v1/runs`、`PUT /gateway/routes`，签到与路由改写
   会在用户毫不知情时真的执行——CORS 只让它看不到回包。
2. **localhost 不受混合内容策略保护**。HTTPS 页面访问 `http://127.0.0.1`
   被视为 potentially trustworthy origin，因此"用户不会在陌生页面里打开本地
   服务"这个前提不成立。

候选方案：

- A. 引入本地 token（server 全端点 Bearer）——需要 CLI/MCP/web/桌面壳全部
  带凭据，改造面大，且桌面壳加载的是 server 自身页面（凭据注入无天然位）。
- B. 绑定回环 + CORS 白名单（现状的唯一加强）——挡不住第 1 条，**否决**。
- C. **CORS 白名单 + 服务端 Origin 硬拦截**（选定）。

## 决策

**选定 C，两道闸同批落地**：

1. `CORSMiddleware.allow_origins` 从 `["*"]` 收为显式白名单
   （`server/security.py:allowed_origins()`：Vite 5173 两形态 +
   `BUTLER_ALLOWED_ORIGINS` 追加）。
2. 新增 `OriginGuard`（纯 ASGI，最外层）：**请求带 Origin 且不在名单 → 403，
   不进路由**（读/写/预检一律）。带 Origin 的判断在服务端，与 CORS 无关。
3. **同源放行限定回环**：Origin 的 netloc 与 Host 完全一致、且 Host 是
   `127.0.0.1` / `localhost` / `::1` 才放行——覆盖桌面壳直连 server、
   server 自托管静态页、改端口运行；**DNS rebinding**（Host 与 Origin 同为
   攻击者域名）因此被挡在外面。
4. **无 Origin 一律放行**：curl / CLI / MCP / 网关控制面不带 Origin，
   不是浏览器攻击面，不引入凭据体系。

同批修正（同源问题，不单独拆）：
**网关 key 的"0600"在 Windows 上是假安全**——NTFS 不承载 POSIX 权限位，
`os.chmod(0o600)` 实测 mode 仍 `0o666`。改为 `harden_permissions()`：
POSIX `chmod 0600`；Windows `icacls /inheritance:r /grant:r <user>:F`；
icacls 不可用/失败 → **告警 + 返回 False**，不静默假装成功、不阻断启动。

明确排除：

- 不做用户体系 / 登录态 / 多用户隔离（单机定位不变）
- 不把网关的 Bearer key 复用到 server（两者信任模型不同：网关面向"本地
  LLM 客户端"，server 面向"本机页面与本地工具"）

## 后果

**正面**：

- 任意网页驱动本机签到、改网关路由的攻击面关闭；桌面壳/CLI/MCP 零改动
- 权限失败可见：icacls 失败有 WARNING，不再"看过 0600 就以为安全"
- 新增面只在 `server/security.py` + `main.py` 三行装配，契约零变更
  （OpenAPI 与 openapi.sha256 不动）

**负面/约束**：

- `BUTLER_ALLOWED_ORIGINS` 在 **create_app 求值** → 改白名单须重启 server
  （本地单进程，可接受）
- 局域网部署若要给手机端用，必须显式加 Origin 白名单（默认只认回环与 5173）
- Windows 上 ACL 收紧依赖系统自带 `icacls`；不可用环境是"告警 + 可读"，
  需要用户手工收紧（已在日志里写明后果）
- 未带 Origin 的本地进程（任何本机程序）仍可直连——本决策**只封浏览器面**，
  "本机进程可信"的前提保持 A1-02 §8 口径
