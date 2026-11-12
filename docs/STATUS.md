# STATUS · 进度卡（每次会话开始先读我）

> 更新纪律：完成一步就改这张卡。格式固定，方便任何终端的 AI 秒懂现状。
> 最后更新：2026-11-12

## 一句话现状

**R1 品牌重塑批①②③完成 + UI 按设计能力包流程重做（2026-11-12）**：全库
Kabao（卡包）单一词汇体系，verify 七项全绿；UI = 「卡纸与墨」主题（frontend-design
→ theme-factory → ui-ux-pro-max 流程产出）+ 五页全落地（首页卡扇/卡包/记录/提醒/设置，
提醒与设置不再是占位）。M0/M1 收官（一核多端骨架 + L0 四件 + 四连接器真机验收）。
**历史已重塑（2026-11-12）**：main = 单根奠基提交起步，Kabao 前 56 笔 Marina 时代
提交不保留（旧史入 bundle 备份，见环境备忘）；提交规范升级 v2.0.0 单号必填严格版。
**接下来：R2 用量立项（取证清单待 Windows 会话执行）**。

## 里程碑

| 阶段 | 内容 | 状态 |
|---|---|---|
| 设计 + M0 + M1 | 定位/架构/详细设计；一核多端骨架；四连接器真机验收 | ✅ 完成（详见 git 历史与各 PROTOCOL.md） |
| **R1 品牌重塑** | Kabao 更名 + 词表 + 数据自动迁移（ADR-007 / A1-03） | **✅ 完成（2026-11-12，批①②③）** |
| **UI 重设计** | 「卡纸与墨」主题 + 五页落地（设计能力包流程，A3-01/D2） | **✅ 完成（2026-11-12）** |
| R2 | 用量采集 + 额度雷达 + MCP Server | **立项中**（纸面裁决齐，取证清单待执行，见「当前挂账」） |
| R3 | 网页会话捕获框架 + ChatGPT/Claude 首批 | 未开始（广度定位关键一步，竞品空白） |
| R4 | 网关独立进程（账号池/反代/规则引擎） | 未开始 |
| R5 | 会话三级迁移 | 未开始 |

## 当前挂账

0. **R2 立项（纸面裁决已齐，阻塞于真机取证）**：
   - **已裁四项**：①立项路径 = 先真机取证 spike；②MCP 宿主 = stdio 薄壳走
     server 契约 API；③工具集 = 查额度/查用量/触发签到；④范围不含领取扩展
   - **当前动作 = Windows 会话执行取证清单**：docs/plans/M2-用量取证清单.md
     （逐家三问 + 纪律 + 可得性矩阵）
   - 取证后剩余待澄清（依赖取证结果）：额度雷达数据模型（entitlement 快照 +
     消耗速率？）、doubao CDP 与用量采集结合（ADR-005 遗留「R2 另裁」）
   - **既有 spec 锚点（写 spec 直接引用）**：A2-01 已预留
     `usage.collect`/`usage.query` ActionKind + UsageSample 实体
     （tokens_in/out / model / ts / source(client|gateway|api)）+ QUOTA_LOW
     事件；A2-02 manifest 已有 `usage.read: {kind: adapter}` 能力位；
     A4-01 已定 `usage_samples` 独立时序表按天分区；A1-01 §3 L2 采集源三类；
     A3-01 记录页「积分/额度趋势曲线」前端锚点
   - 流程后段：方案对比 → 分节设计获批 → spec 落盘 → 自审 → 用户审阅 → 实施
1. **远端改名待办**：Gitee 仓库改名 `kabao` 后本地
   `git remote set-url origin https://gitee.com/hiclaw_520/kabao.git`
   （改名完成前推送仍走现 URL）；改完同步 guides/01 与 conventions/00。
2. **npm org 待验证**：`@kabao` scope 可用性未验；不可用回退未 scope 的 `kabao-sdk`（A1-03 §6）。
3. **desktop 端 main.js 仍是脚手架态**：R2 托盘/sidecar 时接 `build_engine`。

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

- 远端 origin = `https://gitee.com/hiclaw_520/ai-marina.git`（main；仓库改名 `kabao`
  待办，见挂账 1。2026-11-11 由 SSH 改 HTTPS——Gitee SSH 22 端口间歇不可达；
  SSH 配置仍在 ~/.ssh/config 可切回）。
  **推送口径**：全局 `~/.gitconfig` 有空 `credential.helper=` 会禁用 GCM——
  非交互 shell 普通推送必挂，须用
  `git -c credential.helper=manager push origin main`（凭据已缓存，不再弹窗）
- **uv.lock 口径**：macOS 开发机全局 uv 配置走阿里云镜像，`uv sync` 会把锁源
  重写为镜像——**用 `uv lock --default-index https://pypi.org/simple` 直锁官方源**
  （R1 批①重锁已验证，0 污染）；提交前 `git diff uv.lock | grep -c aliyun` 自检，
  脏了就重出
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
