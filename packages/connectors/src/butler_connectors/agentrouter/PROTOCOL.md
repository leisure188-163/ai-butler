# AgentRouter（New API 系）PROTOCOL

> 证据时间：2026-11-16；站点 `https://ps.air-outer.com`（主站 `agentrouter.org` 本机不可达，
> 备用域名公告称功能完全一致）。版本 `init-20261016-861e4557`。

## 1. 站点与登录

- New API 系面板，系统名 `Agent Router`；登录入口 `/login`，支持 GitHub、LinuxDO、邮箱。
- 本机可访问备用域名 `ps.air-outer.com`；页面 `localStorage.user` 保存当前用户快照
  （`id/username/checked_in/last_login_time/quota` 等）。
- 页面鉴权走 Cookie + `New-Api-User` 头（旧版 New API 语义）；直接 `Cookie: session=...`
  调 `/api/user/self` 会 401「未提供 New-Api-User」。

## 2. OAuth 回调前缀

GitHub 登录成功后回调形如：

```text
https://ps.air-outer.com/oauth/github?code=<one-time-code>&iss=https%3A%2F%2Fgithub.com%2Flogin%2Foauth&state=<state>
```

- 主站 `agentrouter.org` 在本机不可达，若 GitHub 默认回调到主站前缀，浏览器打开前
  应把前缀替换为备用域名 `https://ps.air-outer.com`；`/oauth/github` 路径与 query
  保持不变。
- `code` 和 `state` 都是一次性登录凭据，不写入仓库、日志、证据或账户台账；登录成功后
  不再重复访问回调 URL。
- 登录成功后页面进入 `/console`，此时 `localStorage.user` 才带有效 `id/checked_in`。

## 3. 签到语义（真机结论）

- 站点 FAQ 明确：「签到领 $25 额度」——「需要退出后重新登陆才会到账。Log out & back in to activate.」
- 前端登录成功回调里判断 `data.checked_in`：为 true 时提示「签到成功，新增额度已到账」。
- 页面无「立即签到」按钮；`POST /api/user/checkin` 返回 404；`GET /api/user/checkin`
  对普通用户返回 200 业务错误「权限不足」。**结论：登录即签到，没有独立领取接口。**
- 权威状态 = 页面 `localStorage.user.checked_in`（布尔）；`last_login_time` 可辅助审计。

## 4. 本连接器

- `session.import`：经本机 Chromium 调试端口 9222，找 `ps.air-outer.com` 页面，
  读 `localStorage.user`；有 `id` 才登记账户，否则如实报「未登录」。
- `provision.run`：`checked_in=true` → `ALREADY`；false → 自动执行
  「用户菜单退出 → 登录页点 GitHub → 等待 `agentrouter.org/oauth/github` 回调 →
  仅把 host 换成 `ps.air-outer.com` → 等 `/console`」→ `CLAIMED`（登录即签到）。
  控件用 CDP 受信任鼠标事件点击并先 `Page.bringToFront`（后台 webview 会被浏览器
  节流，表现为登录页 Runtime 超时）；回调等待上限 75s。找不到控件、GitHub 未返回回调、
  回调后未进控制台，转 `NO_AUTH` + `relogin` 提示，不假装成功。
- `dry_run=true` 且未签到 → `SKIPPED`，不触发退出/登录。
- 凭据 kind `browser_session` 只存 `domain/port/user_id` 非密定位信息，不存 token/cookie。

## 5. 已知边界

- 需要本机 Chromium（Doubao Browser）调试端口 9222 有 AgentRouter 页面；页面关闭时
  不自动开新标签，返回 `NO_AUTH` / 未登录。
- Chrome v20 应用绑定加密 cookie 不可解（A2-03 §7），因此不走 `browser_cookie` 捕获。
- 站点未来若开放独立 checkin API，可把 adapter 的 `PENDING` 分支替换为 API claim；
  `checked_in` 仍作为权威复查字段。
