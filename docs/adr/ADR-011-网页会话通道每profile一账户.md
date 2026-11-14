---
name: butler-adr-011
description: 网页会话通道按浏览器 profile 一账户接入。TRIGGER when 讨论网页连接器多 profile / 会话导入编键时
version: "1.0.0"
level: must
---

# ADR-011 · 网页会话通道每 profile 一账户

- **状态**：Accepted
- **日期**：2026-11-14
- **决策者**：用户裁决（jason.zhuo）
- **关联**：ADR-003（多账号领域模型）、A2-02 §9（取证结论）、A2-03 §2（捕获规范）、
  chatgpt_web PROTOCOL §7、A3-01 §5（应用→账户展开）

## 背景

2026-11-14 mac 真机取证（A2-02 §9）：本机 Chrome 双 profile（`Default`、
`Profile 1`）cookie 库均实存 chatgpt.com 名单内会话令牌——多 profile 目录
布局实证。但**账号同一性未验**（不解密不取明文，红线 5）：两 profile 可能
是同一 ChatGPT 账号。候选方案：

- 每 profile 一账户槽（重复账号 → 重复槽，领取幂等 ALREADY 兜底）
- 保持单账户（首个凑齐 profile = main），待同一性可验再扩
- 先解密验同一性再定（碰真实会话明文 + Keychain 授权，敏感）

## 决策

**每 profile 一账户槽**（kind 级扩展，`browser_cookie` 通道统一生效——
chatgpt_web / claude_web 共享，无 per-app 分支），流程要点：

1. 逐 profile 捕获：凑齐必需名单的 profile 各成一个账户槽（`CapturedProfile`）
2. 编键：**首个凑齐 profile = `main`**（存量卡位，重扫幂等回放不覆盖不改号）；
   后续槽 = profile 目录名 slug（小写、空格连字），冲突加 `-2/-3` 序号后缀
3. 展示名：非 main 槽 = `{display}（{profile 目录名}）`——目录名是可核对的
   本机事实，非编造
4. 同 profile 目录新旧布局并配（`Cookies` + `Network/Cookies`）按目录去重，
   首个库（路径序）获胜，不出重复槽
5. 逐 profile 隔离纪律不变：单库锁死/解不开记原因换下一个；全落空有事故报
   首个原因，无事故按未登录如实落榜

**明确排除项**：账号同一性验证不做（不解密、不取 uid 明文）；重复账号的
重复槽是已知代价，由领取幂等（服务端 ALREADY）兜底，不做去重合并；
桌面客户端连接器（trae/qoder/doubao/workbuddy）不适用——本机取证均
单账号形状（A2-02 §9），其多账号走各自取证后的 dock 接入。

## 后果

**正面**：

- 扩展点（`SessionSourcePort.enumerate_accounts` / `import_from_source`）
  首次在真通道落地，core/server 契约零改动
- 双 profile 会话都能用（两个独立浏览器登录态都纳入管理）
- UI「应用 → 账户」展开（A3-01 §5）有了真实多账户数据源

**负面/约束**：

- 若两 profile 是同一账号：矩阵出现重复账户行（展示名可区分 profile），
  领取第二个必 ALREADY——用户可见的冗余，接受
- 编键稳定性依赖「首个凑齐者 = main」：若 Default 失效而 Profile 1 凑齐，
  main 槽信封换源（覆盖式重存，与既有重导语义一致）
