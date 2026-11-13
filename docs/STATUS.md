# STATUS · 进度卡（每次会话开始先读我）

> 更新纪律：完成一步就改这张卡。格式固定，方便任何终端的 AI 秒懂现状。
> 最后更新：2026-11-13

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
**R3-1 网页会话通道实现批完成（2026-11-13）**：`browser_cookie` 凭据 kind +
capture 通道（Chrome cookie SQLite 直读，mac Keychain / win DPAPI 双链）+
声明式探针通道（DeclarativeHealthPort 七词映射）+ ChatGPT/Claude 两家连接器
（manifest+YAML+PROTOCOL）+ server RunIn.kind + web 体检按钮（能力申报驱动）。
**真机取证修正（A1-04 §4.1）**：mac Chrome v10 密文 = 16B 未定论段 + 16B 真 IV
+ CBC 密文（非经典形状）——unlock.py 双形状自识别，358/358 可读明文；前 16B
段结构未定论挂账。真机两态验收：ChatGPT 过期令牌照常出卡（EXPIRED 卡面），
Claude 未登录如实落榜；探针真机双态（chatgpt_web FAILED 探针不可达 60s 预算 /
claude_web NO_AUTH 缺凭据）；体检按钮全链通（含装配漏挂探针端口 → 500 的
真机抓修 + 回归测试）。
**文件组织规范落地（2026-11-13）**：conventions/04 立规（一业务域一模块 + 代码文件
600 行硬上限门禁机检 / 400 软警戒）——起因 = server 全部 API 单文件混堆 482 行
（10 端点 / 4 业务域）；routes 已拆 accounts/apps/runs/usage 四域模块 + api.py
纯聚合器（openapi 指纹零漂移实证），verify 门禁升八项结构检查 + 测试项。
**R3-2 定时体检轮询落地（2026-11-13）**：engine `register_health_ports`（探针端口
挂载 + 轮询名册同一份事实，与 provision 端口撞车显式拒绝）+ `start_health_scans`
每日 job（启动即补扫；`_daily_health` 号册全账号逐个体检，Run 照常落台账，
单账号异常 WARNING 隔离不打断整轮）；server 组合层接线（`KABAO_SCHEDULE=0` 可关）。
体检从「手动按钮」升级为「每日巡检」：EXPIRED/NO_AUTH 修复建议随 Run 出账，
连败升级走 AssessAccountHealth 既有反馈回路。门禁九项绿（含新文件长度机检）。
**Windows cookie 真机验收批完成（2026-11-13）**：现代 Chrome 布局（≥96：
`<profile>/Network/Cookies`）双候选补齐（此前旧路径候选本机全落空，误报
「未发现 cookie 库」）；活动库锁死 → immutable 只读直开兜底 + 如实出账，
逐 profile 隔离（首个失败换下一个，全落空报首个原因不误报未登录）；v20
应用绑定加密显式落榜（Chrome 127+ App-Bound，解密需冒充 Chrome 进程 =
对抗绕过，不做——A2-03 §7.7 平台定性：Windows 新版 Chrome 网页会话捕获
如实不可得）；DPAPI 钥匙腿（真 CryptUnprotectData 209B→32B）+ GCM 腿
（真钥匙 roundtrip）真机 PASS。顺手修三处 Windows 门禁/测试失明：verify
子进程编码口径（写读双侧定 UTF-8，此前 GBK 撞 ✓ 即整条失明）、豆包 mac
分支 signal.SIGKILL 跨平台模拟（getattr→POSIX 数值 9，真 mac 行为不变）、
immutable connect 失败收编 ProfileUnreadable（真机抓的逃逸）。门禁九项绿
（474 passed，Windows 首跑）。
**R2 收官两件清账（2026-11-13）**：①**MCP 真机全链验收 PASS**（真 server
uvicorn 8019 + 真 kabao-mcp 子进程 + 官方 mcp 客户端 stdio：initialize/三
工具列名/query_quota·query_usage 真账号空态如实投影/claim_now 真领取
ALREADY 幂等回放/不存在账号 HTTP 404 显式转述附可用名单——红线 5 全链生效；
真 LLM 壳注册同日清账，见挂账 0①）；②R2 spec 归档
`docs/superpowers/specs/2026-11-12-kabao-usage-radar.md`（取证三型/领域三
实体/引擎三表/四家适配/雷达域/雷达页/MCP 薄壳/挂账四条全收拢）。
**顺手修（真机发现）**：doubao Windows dock taskkill exit=128 =「没有找到
进程」（探得与击杀间隙退出）此前按失败抛出致停靠扫描异常——改判「杀净语义
已达成」，与 mac 分支 ProcessLookupError 宽容同事实同语义（doubao PROTOCOL
§6 回填；真失败码照旧显式抛）。验收数据垫料：本机三家真客户端导入
（trae/qoder/workbuddy 进临时库）；doubao 因上述 bug 未导入
（2026-11-13 重扫全链实证清账，见挂账 3）。
**接下来：Claude 登录态补证（换有登录态环境）+ npm org 待验证
（org 创建需账号网页交互）。**

## 里程碑

| 阶段 | 内容 | 状态 |
|---|---|---|
| 设计 + M0 + M1 | 定位/架构/详细设计；一核多端骨架；四连接器真机验收 | ✅ 完成（详见 git 历史与各 PROTOCOL.md） |
| **R1 品牌重塑** | Kabao 更名 + 词表 + 数据自动迁移（ADR-007 / A1-03） | **✅ 完成（2026-11-12，批①②③）** |
| **UI 重设计** | 「卡纸与墨」主题 + 五页落地（设计能力包流程，A3-01/D2） | **✅ 完成（2026-11-12）** |
| R2 | 用量采集 + 额度雷达 + MCP Server | **✅ 收官（2026-11-12）**：用量采集+雷达（真机四家实测）+ MCP stdio 薄壳（ADR-008） |
| **UI 钱包视觉语言** | 去 AI 化重设计：真实卡面+墨印+账本行+钱包架（spec 2026-11-12） | **✅ 完成（2026-11-12）** |
| R3 | 网页会话捕获框架 + ChatGPT/Claude 首批 | **实现批①+R3-2 完成（2026-11-13）**：A1-04 开篇两裁决 + A2-03 细案 + `browser_cookie`/capture/探针全链 + 两家连接器 + 体检 UI + 每日体检轮询 job（真机验收过）+ **Windows cookie 真机验收批（2026-11-13，双布局/锁死兜底/v20 定性）**；余项见挂账 3（①③⑤） |
| R4 | 网关独立进程（账号池/反代/规则引擎） | 未开始 |
| R5 | 会话三级迁移 | 未开始 |

## 当前挂账

0. **R2 收官待办（实现全绿，剩验收与归档）**：
   - **MCP stdio 薄壳（apps/mcp，ADR-008）已完成（2026-11-12）**：官方 mcp 2.x
     MCPServer；三工具 query_quota/query_usage/claim_now = server 契约 API 纯投影
     （GET /usage/radar 拆额度面/用量面 + POST /runs 直传）；可选 provider 过滤；
     server 不可达显式报错附启动命令（红线 5）；门禁八项绿 + stdio 真客户端冒烟
   - 待办：①真机 LLM 客户端验收——**2026-11-13 Windows 补真 server 全链
     tools/call 验收 PASS**（query_quota/query_usage 真投影 + claim_now 真
     领取 ALREADY + 404 显式转述）；**真 LLM 壳注册 ✅（2026-11-13）**：
     已注册进 Qoder 用户级 MCP（entryKey `kabao`，stdio = `uv --directory
     <repo> run kabao-mcp`；控制面 list_tools 三工具握手实证，server 状态
     ready）；**工具可用依赖 = server 8000 在跑**（常驻自动拉起归挂账 2
     托盘批次；server 不可达时工具显式报错附启动命令，红线 5）
     ②~~R2 spec 落盘~~（2026-11-13 归档 docs/superpowers/specs/
     2026-11-12-kabao-usage-radar.md——spec §11 另挂四条随档：
     qoder 9999 占位 cycle 语义待登录态补证 / workbuddy 85 包分组聚合待
     雷达页迭代 / 耗尽预测帧距下限 1h 随使用反馈再定 / MCP 真 LLM 壳即①）
   - **一键批量（2026-11-12 增补）**：POST /apps/import-all + /runs/claim-all
     （编排语义归 server，端零入参）；卡包页「一键导入（n）/一键领取（n）」，
     结果如实分列（signal 计数 + 原文 issues）。真机实测过：导入对无客户端家
     如实报修复建议；领取幂等回放当日班次 Run 不重打
1. **npm org 占用验证全绿（2026-11-13，真浏览器只读）**：org 页
   /org/kabao 与用户页 /~kabao 双双 `Scope not found`（真浏览器过
   Cloudflare；截图坏改用 accessibility 快照取证）；registry 侧
   `@kabao/sdk` 与回退名 `kabao-sdk`/`kabao-core`/`kabao` 全 404（本机
   npm CLI 只读）——**`@kabao` scope 可定稿**（pnpm workspace 已用
   `@kabao/sdk` 无需改名）。剩创建一步需 npm 账号网页交互（登录 →
   npmjs.com/org/create 建 org `kabao` 即可发布；不建则回退未 scope 的
   `kabao-sdk`，A1-03 §6 口径）。注意 npm 公告：bypass-2FA token
   2026-08 起受限、2027-01 起停直发——发布走 granular token + 2FA。
2. **desktop 端托盘/单实例锁未做**：main.js 双模式（在线/离线 sidecar 拉起 +
   健康轮询）已实现，托盘常驻与单实例锁留待 R2 网关批次一并接入 `build_engine`。
3. **R3 网页会话通道——实现批①已收官（2026-11-13），余项**：
   - **已完成**：A2-03 细案 spec；`browser_cookie` kind + capture 通道
     （browser.py：发现/拷贝/解密/信封/两态）+ 探针通道（DeclarativeHealthPort）；
     ChatGPT/Claude 两家连接器（导入+体检）；server RunIn.kind + 契约再生成；
     web CardDetail 体检按钮（能力申报驱动）；engine bridge 零改动（health 端口
     随 register_provision_ports 挂载，server _assemble_connectors 补挂
     health_ports——真机抓到漏挂 500 后加回归测试）
   - **挂账**：①Claude 最小 cookie 名单补证（本机无登录态，换环境取证）；
     ②Windows Chrome cookie 真机验收——**2026-11-13 完成**：现代布局双候选/
      锁死兜底/逐 profile 隔离/v20 显式落榜 + DPAPI/GCM 真机 PASS；平台定性 =
      Chrome 127+ 应用绑定加密 v20 全量，本通道不做对抗解密（Windows 新版
      Chrome 网页会话捕获如实落榜，A2-03 §7.3/§7.7）；③mac v10
     密文前 16B 段结构未定论（确定性相关、非 sha256/hmac，完整性验证挂账）；
     ④~~定时体检轮询批次~~（已落地 R3-2，2026-11-13：register_health_ports +
     start_health_scans，轮询名册=探针名册，启动补扫+单账号隔离）；⑤A1-04 §8.3/8.4
     待裁照旧
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
   重启客户端后重扫验证真数据面。**doubao Windows dock 全链重扫验证 ✅
   （2026-11-13 本机真机）**：无端口普通态客户端起步 → POST
   /apps/doubao_cn/import 全链 = 杀净清场 → 带端口拉起（新 PID 9222
   LISTENING 实证）→ probe 就绪 → doubao_cn:main 泊位 → 顺带采集
   入账流水 10 条真数据零 issues；snapshot=None/aggregate=None 为
   ledger 单型如实形状；二次重扫幂等（probe 直达不杀进程同账号）。
   taskkill-128 分支保持单测钉语义（间隙竞态真机不可确定性复现）。

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
- **文件组织与长度**（conventions/04）：一业务域 = 一模块 = 一文件（路由按
  accounts/apps/runs/usage 分域，api.py 纯聚合器）；代码文件软警戒 400 行 /
  **硬上限 600 行门禁机检**（verify 第八项，packages/apps/scripts 下
  py/ts/tsx/vue/js/mjs，gen 等派生物除外；文档不进机检）；
  存量 400+（decl/usecases/dockio）不强制立即拆，新代码不得堆入

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
