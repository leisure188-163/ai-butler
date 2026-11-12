# STATUS · 进度卡（每次会话开始先读我）

> 更新纪律：完成一步就改这张卡。格式固定，方便任何终端的 AI 秒懂现状。
> 最后更新：2026-11-12

## 一句话现状

**R1 品牌重塑批①②③完成 + UI 按设计能力包流程重做（2026-11-12）**：全库
Kabao（卡包）单一词汇体系，verify 八项全绿；UI = 「卡纸与墨」主题（frontend-design
→ theme-factory → ui-ux-pro-max 流程产出）+ 五页全落地（首页卡扇/卡包/记录/提醒/设置，
提醒与设置不再是占位）。M0/M1 收官（一核多端骨架 + L0 四件 + 四连接器真机验收）。
**历史已重塑（2026-11-12）**：main = 单根奠基提交起步，Kabao 前 56 笔 Marina 时代
提交不保留（旧史入 bundle 备份，见环境备忘）；提交规范升级 v2.0.0 单号必填严格版。
**UI 增强 + 门禁加固（2026-11-12）**：三主题并列（卡纸与墨/墨夜/暖纸）+ 默认跟随系统
（prefers-color-scheme 实时跟随，D2 v4 / A3-01）；web DTO 派生自 SDK 契约
（types.ts 零手写字段清单），vue-tsc 类型检查收编门禁测试项；窄视口 ≤900px
侧栏转横条后主区被挤出屏已修（.shell 配套转纵向）。
**R2 用量取证 spike 完成（2026-11-12，Windows 真机只读）**：取证清单四家全落
（结论回填各连接器 PROTOCOL §7 + 清单 §6 矩阵）。核心：四家逐调用 tokens
双通道全 UNSUPPORTED，用量采集按「聚合用量 + 额度快照 + 入账流水」三型重定
义；额度雷达输入四家 API 全可得（trae ent_usage 29 包 / qoder v2/me/usage
addOnQuota / doubao quota-records 入账流水 / workbuddy get-user-resource 85
包分账本 remain 1894）；doubao CDP 读用量无增量价值（UI 只有累计获得，与
detail 重复）——ADR-005 三选一裁决材料齐，倾向不做。顺手清 docker-compose
postgres/JWT_SECRET 残留（与 SQLite 单机架构漂移，Dockerfile 保留）。
**R2 用量采集全链完成（2026-11-12）**：core 三实体 + 语义谓词单源（is_quota_low
含耗尽排除 / forecast_exhaustion 含最小帧距）；引擎三表 + 耗尽预测；四家连接器
用量适配真机全通（trae ent_usage / qoder me-usage / doubao quota-records 流水
翻页 / workbuddy get-user-resource）；server /usage/collect + /usage/radar
（契约派生）；web 额度雷达页（六页 IA：活跃包平铺 + 历史耗尽折叠）；engine
每日用量 job（启动补采）+ dock 顺带采集（失败进 issues 不打断导入）。
**R2 收官（2026-11-12）：MCP stdio 薄壳落地（apps/mcp，ADR-008）**——官方 mcp 2.x
MCPServer（v1 FastMCP 已更名）；三工具 query_quota/query_usage/claim_now 纯 HTTP
投影 server 契约 API（零 core/engine import，server 零改动无契约再生成）；server
不可达显式报错附启动命令（红线 5）；stdio 真客户端冒烟（握手/列工具/无 server
调用）全过；门禁八项绿（396 passed）。
**UI 去AI化·钱包视觉语言落地（2026-11-12）**：brainstorm 流程（痛点小样=面板骨架/
状态灯/均节奏 → 用户锚定腾讯卡包模式 → 桌面适配 A 钱包架获批）→ spec
（docs/superpowers/specs/2026-11-12-kabao-wallet-visual-design.md）→ 实现全绿：
卡=真实卡面（face 渐变对 + 首字圆章 + 等级徽 + 墨印角章），`.lamp`/`.panel` 全退役
（`.sheet` 细线框 + 行尾墨印），卡包页=钱包架两栏（详情栏 sticky，≤900px 下沉），
未导入=虚线空卡槽，雷达=face 色横幅节头；层叠按 M1 单账户契约裁掉（YAGNI）；
真机三主题 + 双断点 + 选卡/空槽/详情/领取链路验证过（qoder FAILED 为已知协议
发现，UI 显式转述 = 红线 5 生效）；墨印四色按暗主题 face-5 实测调亮至 ≥4.5:1；
门禁八项绿两轮。
**接下来：R3 网页会话通道——开篇已立（A1-04，两承重裁决已批：直读 cookie /
Chrome·mac+Win），实现批待启动**。

## 里程碑

| 阶段 | 内容 | 状态 |
|---|---|---|
| 设计 + M0 + M1 | 定位/架构/详细设计；一核多端骨架；四连接器真机验收 | ✅ 完成（详见 git 历史与各 PROTOCOL.md） |
| **R1 品牌重塑** | Kabao 更名 + 词表 + 数据自动迁移（ADR-007 / A1-03） | **✅ 完成（2026-11-12，批①②③）** |
| **UI 重设计** | 「卡纸与墨」主题 + 五页落地（设计能力包流程，A3-01/D2） | **✅ 完成（2026-11-12）** |
| R2 | 用量采集 + 额度雷达 + MCP Server | **✅ 收官（2026-11-12）**：用量采集+雷达（真机四家实测）+ MCP stdio 薄壳（ADR-008） |
| **UI 钱包视觉语言** | 去 AI 化重设计：真实卡面+墨印+账本行+钱包架（spec 2026-11-12） | **✅ 完成（2026-11-12，待提交）** |
| R3 | 网页会话捕获框架 + ChatGPT/Claude 首批 | **开篇已立（2026-11-12，A1-04）**：双通道定位/捕获机制/平台矩阵/第一批边界两裁决已批；实现未开始 |
| R4 | 网关独立进程（账号池/反代/规则引擎） | 未开始 |
| R5 | 会话三级迁移 | 未开始 |

## 当前挂账

0. **R2 收官待办（实现全绿，剩验收与归档）**：
   - **MCP stdio 薄壳（apps/mcp，ADR-008）已完成（2026-11-12）**：官方 mcp 2.x
     MCPServer；三工具 query_quota/query_usage/claim_now = server 契约 API 纯投影
     （GET /usage/radar 拆额度面/用量面 + POST /runs 直传）；可选 provider 过滤；
     server 不可达显式报错附启动命令（红线 5）；门禁八项绿 + stdio 真客户端冒烟
   - 待办：①真机 LLM 客户端验收（注册命令 `uv run kabao-mcp`）
     ②R2 spec 落盘 docs/superpowers/specs/（设计与实现已批，可后补归档）
   - **一键批量（2026-11-12 增补）**：POST /apps/import-all + /runs/claim-all
     （编排语义归 server，端零入参）；卡包页「一键导入（n）/一键领取（n）」，
     结果如实分列（signal 计数 + 原文 issues）。真机实测过：导入对无客户端家
     如实报修复建议；领取幂等回放当日班次 Run 不重打
1. **npm org 待验证**：`@kabao` scope 可用性未验；不可用回退未 scope 的 `kabao-sdk`（A1-03 §6）。
2. **desktop 端托盘/单实例锁未做**：main.js 双模式（在线/离线 sidecar 拉起 +
   健康轮询）已实现，托盘常驻与单实例锁留待 R2 网关批次一并接入 `build_engine`。
3. **R3 网页会话通道（开篇已立，A1-04）**：双通道战略——网页 = 广度主通道
   （浏览器 × 系统矩阵，Chrome·mac+Win 首批），客户端 dock = 深度面（mac 分支
   按需排优先级）。**mac Chrome Keychain 取证已完成（2026-11-12 本机，A1-04 §4.1）**：
   解密链全通（PBKDF2 1003 轮 + AES-128-CBC + v10 前缀），一钥匙覆盖全 profile，
   本机 528 cookie 全解零失败；本机 ChatGPT（令牌已过期）/ Claude（未登录）恰为
   两类导入边缘态天然样本。下一步：`browser_cookie` 凭据 kind + capture 通道
   （A2-03 细案）→ ChatGPT/Claude 两家连接器（Claude cookie 名单待补取证——
   本机无登录态，需换有登录态的环境）→ 导入/体检 UI。待裁清单见 A1-04 §8。
   **A-档轻活已清（2026-11-12）**：locate 链与 issue 文案按 sys.platform 分流——
   mac 上如实报「分支未实现/待取证」+ 本平台逃生口（DOUBAO_EXE/WORKBUDDY_EXE），
   不再报 Windows 视角文案。顺手修两个真 bug：①dock 主扫描出的 `_issue` 会被
   umid 采集器掩盖（真机 mac 实证：qoder DPAPI 解锁失败被定位失败顶掉）——
   _issue 即落榜不跑附加采集；②`_issue` 走 store 期 raise 会逃出 scan_storage
   且先注册孤儿账号——改为注册前如实落榜。qoder umid 定位链补真 mac 分支
   （`/Applications/Qoder.app/Contents/Resources/umid/runtime-info` 本机取证
   存在且可运行）。本机实证四家客户端全装（豆包/Qoder/Trae×3/WorkBuddy）——
   客户端 mac 分支的取证优先级因此上调（B-档候选按数据增量排）。
   **B-档已清（2026-11-12，三家 mac 分支全落地 + 真机验收）**：
   ①豆包——真机实锤 `--remote-debugging-port` 在 mac 同样生效（9223 实例佐证），
   localenv 补 mac 分支（Info.plist 版本 / `.app` 束定位 / pgrep / SIGKILL /
   start_new_session 拉起），dock + 真签全链通（ALREADY「连签 5 天」）；
   ②WorkBuddy——解密链与平台无关（helper.js 只要定制版 Electron 的
   `electron_browser_workbuddy_storage` 绑定），mac 主程序 probe 通过
   （Electron 37.10.3）+ 真机解密通（1472 字符 token 验形不落盘），localenv 补
   `.app` 束定位（`Contents/MacOS/Electron`，CFBundleExecutable 即原生 Electron），
   dock + 顺带采集真机绿（90 权益包入库）；③Qoder——mac 的 Local State 无
   `os_crypt`，钥匙走 Keychain safeStorage（服务名实测定稿 `Qoder App Safe
   Storage`），链 = PBKDF2(saltysalt,1003) + AES-128-CBC（密文块长 16 倍数实证），
   kind 仍 `dpapi_gcm_v10` 双平台单源分流（mac 信封只带 dat，钥匙现取不入 vault），
   dock 真机落册。**协议新发现（PROTOCOL §1.2）**：Qoder 客户端运行期不回写
   auth.v1.dat（连跑 6 天文件停在 11-06）→ 文件内 token 已被服务端轮换作废，
   usage/campaigns 齐 401 TOKEN_EXPIRE——处置 = 重启客户端后重扫，非解锁链缺陷。
   门禁八项绿。**剩余缺口**：Trae×3 mac 取证未做（M1 记忆既有挂账）；qoder 需
   重启客户端后重扫验证真数据面。
4. **UI 钱包视觉语言已实现待提交**：apps/web 全量（tokens/ui/BizCard/CardDetail/
   WalletPage/Home/Radar/Log/Alerts/Settings）+ spec 增补一行（.panel 删除与
   .sheet 收编）；STATUS 本条与 B-档叙事同文件——提交时按意图拆分由提交方裁量。
   实测记录：qoder 领取 FAILED 为 PROTOCOL §1.2 已知轮换滞留（重启客户端后重扫
   即愈），UI 转述链显式无吞错。

## 已定关键决策（不再讨论，照做）

- 前代项目 auto-signin-kit **严禁搬代码**：只提炼 PROTOCOL.md + 行为对照验收（A0-01）
- **ADR-001**：出站适配器独立成 `packages/engine`（COLA infrastructure 正形）；
  端只准 `from kabao_engine.bridge import ...`；core.bootstrap 保留纯装配根
- **ADR-002**：from_engine 方言注册表——连接器以**数据**申报业务码→Status 映射、
  加载期注册；默认 legacy 自映射；未知码显式抛 UnknownEngineCode（红线 5），
  用例层转 FAILED + evidence + PROTOCOL_CHANGED；严格字面匹配不归一。
  协议字面量七词（CLAIMED/ALREADY/FAILED/NO_AUTH/PENDING/EXPIRED/SKIPPED）
  与旧系统 oracle 对齐，**永不改名**（ADR-007 两层词汇）
- **ADR-003**：连接器 target 级端口路由
- **ADR-004**：qoder 接入形状 = 声明式扩展（列表领取受限形状 / DPAPI+AES-GCM
  双层凭据 / 机器身份头组 kind 化 / 静默陷阱显式化 = FAILED + repair_hint）
- **ADR-005**：doubao 接入形状 = CDP 界面通道（零凭据）
- **ADR-006**：workbuddy 接入形状 = adapter 端口实现——凭据**现用现取零申报**
  （不落 vault，运行时读客户端会话文件即用即弃）；信封 token 解密走 helper.js
  子进程（客户端自带 Electron runtime；「严禁搬代码」的唯一例外 = 协议契约，
  守卫测试钉 12 标记）
- **ADR-007**：品牌 Kabao（卡包）+ 市场白话词表，标准单源 A1-03，
  已收编 conventions/03（见下）
- **M1 硬标准**：每个 Connector 不加特殊分支接入；要写例外 → 停下来改模型
- **kind 收敛原则**（A2-02 §3）：应用接入面 = 声明 + 可枚举 kind 的组合，
  一套运行时 + N 份数据，绝不 per-app 平行代码；协议特殊性只以 kind 形态扩展
- **L0 参数默认值**（core 常量单源）：CREDENTIAL_EXPIRING 预警窗默认 **3 天**
  （`domain/vault.py:EXPIRING_WINDOW_DAYS`）；risk = 连续 **3 次** NO_AUTH
  （`domain/health.py:RISK_NO_AUTH_STREAK`）
- **Windows 凭据管理器（DPAPI）适配器**：ctypes advapi32，纯标准库；系统调用经
  `api_factory` 注入隔离，非 Windows 用假 api 单测（CI 中照跑）
- **Vault 审计不走事件总线**：存/取/轮换在 LayeredVault 内**同步**落审计——
  审计是 R4 反代上线前的安全底线；事件总线只承载通知类事件
- **到期扫描的记忆语义**：凭据/账号都以"上一已知级别"做变更检测——级别不变不重发；
  恢复 healthy 不产新事件类型（A2-01 §5 无恢复事件，不发明），
  账号恢复发 SILENT 级 ACCOUNT_HEALTH_CHANGED 保 UI 同步
- **健康首评语义**：首评即 healthy 不发事件；首评即异常发事件（新事实要进"待处理"）
- **视觉 signal 分类 core 单源**：`ResultKind.signal`（ok/attention/danger/quiet）
  与 `HealthLevel.signal`（ok/notice/attention/danger）——端上染色是业务语义，
  必须 core 出产；UI 只认五词上 CSS class（红线 2 的 Web 端闭环）
- **横幅聚合在端**：横幅句式 = 纯计数 + 文案模板，语义词仍是 core 的 signal——
  属表达不属业务规则；若规则复杂化再上收 core
- **契约流水线口径**：`generate.mjs` 直接 `from server.main import app` 导出
  （免起 uvicorn），hash = `sha256(json.dumps(app.openapi()) + "\n")` 与 verify
  同口径；中间产物 `openapi.json` 进 .gitignore 不入库
- **docs 体系**：设计文档入 specs/ 分层子目录，强制规范入 conventions/
  （00-项目配置为唯一变量入口），决策入 adr/；STATUS.md 代替 TODO.md（避免双源）；
  specs 文件命名 `A{层级}-{NN}{分册字母}-{主题}.md`

## 环境备忘

- 远端 origin = `git@gitee_hiclaw520_126:hiclaw_520/ai-kabao.git`（main；
  2026-11-12 仓库已由 `ai-marina` 更名为 `ai-kabao`）。
  **推送口径（2026-11-12 起 SSH 别名直推）**：远端 URL 必须用 `~/.ssh/config`
  别名 `gitee_hiclaw520_126`（hiclaw_520 账号专用钥匙）——裸 `git@gitee.com:`
  走默认钥匙（xiaoyaojiugui 账号）对 hiclaw_520 仓库报 Access denied；
  HTTPS + `credential.helper=manager` 在非交互 shell 弹窗被取消必挂，均弃用
- **uv.lock 口径**：macOS 开发机全局 uv 配置走阿里云镜像，`uv sync` 会把锁源
  重写为镜像——**用 `uv lock --default-index https://pypi.org/simple` 直锁官方源**
  （R1 批①重锁已验证，0 污染）；提交前 `git diff uv.lock | grep -c aliyun` 自检，
  脏了就重出。**2026-11-12 复发实证**：库内旧锁混入 744 行 aliyun（MCP 薄壳批次
  重锁清零）——自检看新增行 `git diff uv.lock | grep -c '^+.*aliyun'` 才准
- **macOS 前端门禁**：系统 node 20 + pnpm 7 打不开 lockfile v9——shell 先
  `eval "$(fnm env --shell zsh)"` 走 node 24 + pnpm 9；apps/web/node_modules
  缺失时报 vue-tsc ENOENT，`pnpm install --frozen-lockfile` 即愈
- pnpm-lock.yaml 已提交，CI 用 `--frozen-lockfile`
- 提交信息规范接入提交钩子三件套 `.githooks/commit-msg` +
  `scripts/install_hooks.py` + `scripts/setup_hooks.cjs`（pnpm postinstall 自动
  启用），规范正文 `conventions/08-提交信息规范.md`。**v2.0.0 严格版（2026-11-12
  起，与 cross-platform-arch skill 同源）**：单号必填（无关联占位 `[0]`），
  超长/句号结尾钩子强制拒绝
- **历史重塑（2026-11-12）**：main 重写为单根奠基提交 `1909978`（feat:[0]:
  落地 Kabao 初版）；其前 69 笔旧史（Marina 全程 + Kabao 批①②③，终态 42e18e6）
  备份于 `D:/codes/opensoure/kabao-history-20261112.bundle` + 本地 tag
  `archive/marina-full-history`（仅本地，不推送）。旧提交哈希自此全部悬空，
  文档一律不再引用
- 契约指纹：`generate.mjs` 与 verify 都是
  `sha256(json.dumps(app.openapi()) + "\n")`；改 API 后照常 `pnpm gen:sdk` 即可
- **CodeGraph**（2026-11-11）：CLI 已装 1.5.0-sl.1（npm -g）；前代项目
  auto-signin-kit 已建图；MCP user 级注册 `codegraph serve --mcp --path
  D:/codes/opensoure/auto-signin-kit`；会话内可 CLI `codegraph explore` / `query` 直查
- cross-platform-arch skill 1.8.0 实际位于 **`D:\codes\leisure\leisure_skill\cross-platform-arch`**
  （Windows 端路径；C 盘 ~/codes 不存在）
