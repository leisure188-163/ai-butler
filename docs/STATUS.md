# STATUS · 进度卡（每次会话开始先读我）

> 更新纪律：完成一步就改这张卡。格式固定，方便任何终端的 AI 秒懂现状。
> 最后更新：2026-11-14

## 一句话现状

**六页 IA 阶段二收官（2026-11-14，[ADR-010](adr/ADR-010-六页信息架构.md)）**：
四页（账号/用量/记录/设置）→ **六页（仪表盘/应用/账户/流量/日志/设置）**，
仪表盘默认、待办栏迁入、导入归应用、领取归账户、角标挂仪表盘；重定向表 v2
7 条旧链 + 运行中 hashchange 重写全过（`#/usage`/`#/log` 降级为旧链）；
页名词表 v2 一次到位，主题显示名「纸墨/墨夜/暖纸」与关于节产品名回收阶段一
遗留；`AccountsPage` 485 行 → 页头 76 行 + `MatrixTable.vue` 321 行。
**影响面仅 `apps/web/src/` + 文档**：`api.ts` 零 diff，composables 仅注释/
动作消息换词（数据接口不变），
server/engine/connectors/sdk/mcp/desktop/cli 零 diff，OpenAPI 与
openapi.sha256 零 diff。**验收**：vue-tsc 绿 + 门禁九项绿 + 505 tests 全绿；
浏览器走查 server:8000 + Vite:5173（隔离 BUTLER_DB=/tmp 临时库）——
六页 × 双断点（1440×900 / 375×812）× 三主题（纸墨/墨夜/暖纸）全过，
7 条旧链重定向正确，一键导入（6）与 server apps=6 吻合、
一键领取（0）/角标（无）与 accounts=0/pending=0 吻合，console 零错误；
修掉窄屏顶条六项导航与主名重叠（改两行网格 + 导航横向滚动）。
Butler 重定位六问裁决全部落地。

**按业务域重写 P0-P6 全部完成（2026-11-14，ADR-002）**：`butler_core` 五业务域
+ shared 内核从零落地（端口随域走、依赖恒等式入门禁机检），`butler_engine` 按同
域图重写，旧 `kabao_core/butler_engine` 已删除；全库 six 包/CLI/env/db/存储键/
npm 包名统一 butler（仅 Gitee 远端改名待用户手工）；多账号模型落地
（首账号键 `main` 兼容存量，幂等键按账号，契约 `account_key`/`account_ids`，
一键领取逐账户发起）；一次性迁移集中 `butler_engine/db/migrate.py`（旧库四级
优先级 + vault 旧前缀装配期回写，运行时零 legacy 分支）；OpenAPI 契约已再生成、
web vue-tsc 绿。**验收：全量测试 505 passed + 门禁九项全绿**。
A2-02 §9 如实登记连接器多 profile 取证结论（未取证不虚报）。

## 剩余挂账

- **Gitee 远端改名** `ai-kabao`→`ai-butler`（用户手工；改完同步 `conventions/00` 远端值）。
- **R3 网页会话通道余项**：Claude 最小 cookie 名单补证（本机无登录态，换环境取证）；
  mac v10 密文前 16B 段结构未定论（确定性相关、非 sha256/hmac，完整性验证挂账）。
- **npm org 创建** `butler`（网页交互，发布前做；A1-03 §6 口径）。
- **连接器多 profile 取证** 后展开「应用 → 账户」操作面（A2-02 §9）。

## 已定关键决策（不再讨论，照做）

- 前代项目 auto-signin-kit **严禁搬代码**：只提炼 PROTOCOL.md + 行为对照验收（A0-01）
- **ADR-001**：出站适配器独立成 `packages/engine`（COLA infrastructure 正形）；
  端只准 `from butler_engine.bridge import ...`；core.bootstrap 保留纯装配根
- **ADR-004**：from_engine 方言注册表——连接器以**数据**申报业务码→Status 映射、
  加载期注册；默认 legacy 自映射；未知码显式抛 UnknownEngineCode（红线 5），
  用例层转 FAILED + evidence + PROTOCOL_CHANGED；严格字面匹配不归一。
  协议字面量七词（CLAIMED/ALREADY/FAILED/NO_AUTH/PENDING/EXPIRED/SKIPPED）
  与旧系统 oracle 对齐，**永不改名**（两层词汇原则，收编 conventions/3 与 A1-03 §3）
- **ADR-005**：连接器 target 级端口路由
- **ADR-006**：qoder 接入形状 = 声明式扩展（列表领取受限形状 / DPAPI+AES-GCM
  双层凭据 / 机器身份头组 kind 化 / 静默陷阱显式化 = FAILED + repair_hint）
- **ADR-007**：doubao 接入形状 = CDP 界面通道（零凭据）
- **ADR-008**：workbuddy 接入形状 = adapter 端口实现——凭据**现用现取零申报**
  （不落 vault，运行时读客户端会话文件即用即弃）；信封 token 解密走 helper.js
  子进程（客户端自带 Electron runtime；「严禁搬代码」的唯一例外 = 协议契约，
  守卫测试钉 12 标记）
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
- **文件组织与长度**（conventions/4）：一业务域 = 一模块 = 一文件（路由按
  accounts/apps/runs/usage 分域，api.py 纯聚合器）；代码文件软警戒 400 行 /
  **硬上限 600 行门禁机检**（verify 第八项，packages/apps/scripts 下
  py/ts/tsx/vue/js/mjs，gen 等派生物除外；文档不进机检）；
  存量 400+（decl/usecases/dockio）不强制立即拆，新代码不得堆入

## 环境备忘

- 远端 origin = `git@gitee_hiclaw520_126:hiclaw_520/ai-kabao.git`（main；
  2026-11-12 仓库已由 `ai-marina` 更名为 `ai-kabao`）。**Gitee 远端改名 `ai-kabao`→`ai-butler`
  待用户手工（改完同步 conventions/00）**。
  推送口径（2026-11-12 起 SSH 别名直推）：远端 URL 必须用 `~/.ssh/config`
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
  启用），规范正文 `conventions/04-提交信息规范.md`。**v2.0.0 严格版（2026-11-12
  起，与 cross-platform-arch skill 同源）**：单号必填（无关联占位 `[0]`），
  超长/句号结尾钩子强制拒绝
- 契约指纹：`generate.mjs` 与 verify 都是
  `sha256(json.dumps(app.openapi()) + "\n")`；改 API 后照常 `pnpm gen:sdk` 即可
- **CodeGraph**（2026-11-11）：CLI 已装 1.5.0-sl.1（npm -g）；前代项目
  auto-signin-kit 已建图；MCP user 级注册 `codegraph serve --mcp --path
  D:/codes/opensoure/auto-signin-kit`；会话内可 CLI `codegraph explore` / `query` 直查
- cross-platform-arch skill 1.8.0 实际位于 **`D:\codes\leisure\leisure_skill\cross-platform-arch`**
  （Windows 端路径；C 盘 ~/codes 不存在）
