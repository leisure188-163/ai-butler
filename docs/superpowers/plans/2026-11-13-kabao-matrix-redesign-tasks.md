# 任务书 · Kabao 矩阵改版（2026-11-13）

> **给执行模型的说明**：本任务书自足完备，按 T0→T13 顺序执行，每任务有独立验收。
> 执行前必读本文件「§A 全局铁律」与「§B 术语表」；遇到任务书没写的细节，
> 以仓库现有代码风格与 `docs/conventions/02-开发红线.md` 为准，**不要发明新规则**。
> 仓库根：仓库根目录（含 `packages/ apps/ docs/`）。改动面 = `apps/web/src` + `docs/`，
> **除任务书列出的文件外一律不动**。

---

## §A 全局铁律（每个任务都要遵守，违反即返工）

1. **端零映射（红线 2）**：UI 染色/文案只消费 core 出产的五分类 `signal`
   （`ok/notice/attention/danger/quiet`），组件**禁止**认识 `Status`/`HealthLevel` 字面量；
   `status` 原文只在结果列如实展示（如 PENDING 就显示「服务端判定暂不符合条件」的原文，不翻译成"已领取"）。
2. **token 单源（红线 6）**：所有颜色/字号/间距引用 `apps/web/src/styles/tokens.css` 的
   `var(--x)`，**禁止**在组件里写死颜色值；门禁机检「token 引用闭合」（verify 第 5 项）
   会扫描全库 `var(--x)` 是否有定义。
3. **文件长度**：任何代码文件 ≤600 行（硬上限，verify 第 8 项机检）；一业务域一文件。
   矩阵页拆分组件正是为此。
4. **诚实纪律**：待办栏/结论只汇报系统真做过的动作；证据（evidence）一律折叠进「查看详情」；
   空态必须给行动指引。
5. **契约零改动**：禁止改 `apps/server`、`packages/core`、`packages/engine`、
   `packages/sdk`、`packages/connectors`、`apps/mcp`、`apps/desktop`、`apps/cli`。
   `pnpm gen:sdk` **不需要跑**。契约指纹零漂移是验收项。
6. **types.ts 禁手写字段**：前端 DTO 一律 `import type { components } from "@kabao/sdk"`
   派生（现状即如此，保持）；唯一允许的本地加工 = `signal` 窄化为五分类。
7. **不新增任何 npm 依赖**；不引入 webfont；系统字体栈不动。
8. **可访问性地板**：正文对比 ≥4.5:1、所有控件焦点环可见（`:focus-visible` 已全局生效）、
   动效尊重 `prefers-reduced-motion`（tokens 里已有全局归零规则，别删）、
   控件带 role/aria（switch 用 role=switch 的模式照抄 SettingsPage）。
9. **三主题机制不变**：`:root`=卡纸与墨（浅默认）、`[data-theme="dark"]`=墨夜、
   `[data-theme="warm"]`=暖纸；设置默认「跟随系统」（`prefers-color-scheme` 实时跟随）。
   只调 token 值，不改机制、不改主题名（localStorage 存档兼容）。
10. **渲染纪律**：所有列表 = 行+发丝线（`.rows/.row`），表格用新 `.matrix` 件；
    排障信息折叠；不做 SaaS 卡片墙、不做渐变装饰、不做动画除按压反馈外的新动效。

## §B 术语表（词表定稿，用户可见文案以此为准）

| 词 | 含义 | 备注 |
|---|---|---|
| 账号 | account（原「卡」的用户词） | 页名 |
| 用量 | usage/额度雷达 | 页名 |
| 记录 | 操作台账（runs） | 页名 |
| 品类句 | **「Kabao · AI 账号管家」** | 原「你的 AI 卡包」退役（ADR-009 裁决） |
| signal 五词 | ok=正常 / notice=注意 / attention=留意 / danger=异常 / quiet=— | `signalText()` 出文案 |
| 应用小徽 | AppBadge：身份色点 + 应用名 | 唯一保留的身份色载体 |

## §C 环境与常用命令（macOS 开发机）

```bash
# 前端工具链前置（系统 node 20 打不开 lockfile v9，必须先走 fnm 的 node 24）
eval "$(fnm env --shell zsh)"
# apps/web/node_modules 缺失时报 vue-tsc ENOENT，先装：
pnpm install --frozen-lockfile

# 类型检查（最常用，改动后随时跑）
pnpm --dir apps/web exec vue-tsc --noEmit

# 全量门禁（九项：结构/核心纯净/依赖方向/桥闭合/token闭合/契约指纹/空包/600行/测试）
uv run python scripts/verify_project.py --project . --test

# 本地起 web 预览（需 server 在 8000 端口，UI 会显式报「够不到本机服务」）
pnpm dev:web
```

**提交规范（v2.0.0，钩子强制）**：`<type>:[<需求单号>]: <中文主题>`；无单号占位 `[0]`；
主题动词开头、≤100 字、不加句号。例：`feat:[0]: 矩阵改版批次一·token 地基`。

---

## §D 任务列表

### T0 · 基线门禁（只读，不改代码）

- **目标**：确认起点全绿，后续任何 FAIL 才可归因于本次改动。
- **步骤**：
  1. 跑 §C 全量门禁 `uv run python scripts/verify_project.py --project . --test`，记录 PASS。
  2. `git status` 确认工作区干净。
- **验收**：门禁九项全绿；否则停下来先修基线，与本任务书无关的破损上报，不顺手修。
- **依赖**：无。

---

### T1 · tokens.css 调值与「待退役」标注（只调值，不删任何 token）

- **文件**：`apps/web/src/styles/tokens.css`（唯一改动文件）。
- **要求**：
  1. **保留且不动值**：语义五色全套（ok/notice/attention/danger/quiet 及 `-ink/-weak`
     变体，三主题各一套）、纸系中性值（`--color-bg/-surface/-surface-2/-border`）、
     文本三档（`--color-ink/--color-text-muted/--color-text-faint`）、字体/字号/尺寸/
     间距/圆角/`--sidebar-w`、`--shadow-card`、`--motion-fast/--motion-base/--ease-out`、
     `:focus-visible` 规则、`prefers-reduced-motion` 规则、body 基础样式。
  2. **保留**：`--color-accent`（金，文本级，值不变）、`--color-accent-weak`、
     `--color-on-ink/--color-ink-strong`、`--card-face-1..6`（身份色单值，三主题块里的
     覆写值全部保留——小徽跨主题一致逻辑照旧）。
  3. **值微调**：无硬性必改值；如需让案面更中性可微调，但**禁止改动语义五色**与
     主题名注释结构。
  4. **「待退役」标注**（本任务只加注释，不删除；删除在 T10）：
     `--card-face-*-hi/--card-face-*-lo`（12 个渐变端值）、`--face-text`、
     `--face-seal-ok/notice/attention/danger/quiet`、`--chip-gold-hi/--chip-gold-lo`、
     `--slot-dash`、`--shadow-lift`、`--motion-reveal`。
     在这批 token 定义处加一行注释：`/* 待退役（矩阵改版 T10 删除）：XXX */`。
  5. 文件头注释更新：主题从「卡纸与墨（实体卡锚定）」改为「卡纸与墨（中性工作台基底），
     2026-11-13 矩阵改版 v5：去卡面装饰，身份色降级为小徽，语义五色不变」。
- **验收**：`pnpm --dir apps/web exec vue-tsc --noEmit` 绿（token 无类型影响，主要防手误）；
  `grep -c "待退役" tokens.css` ≥ 1。
- **依赖**：T0。

---

### T2 · ui.css 新增通用件（只新增，不删旧）

- **文件**：`apps/web/src/styles/ui.css`（唯一改动文件）。
- **要求**（全部从 tokens 取变量，参考现有 .btn/.row 的写法风格）：
  1. `.tag`（结果徽，接替印章形态但更轻）：无边框、`--text-xs`、mono 不强制、
     浅底色块 `*-weak` + `*-ink` 文字，五分类变体 `.tag--ok/--notice/--attention/`
     `--danger/--quiet`；圆角 `--radius-sm`，padding 2px 8px。
  2. `.badge-dot`（应用小徽的身份色点）：8px 圆点，`background` 由使用方内联 style 传
     `var(--card-face-N)`（组件 T3 处理，这里只定义通用圆点类）。
  3. `.matrix` 表格件：
     - `.matrix`：`width:100%; border-collapse:collapse; font-size:var(--text-sm);`
     - `.matrix th`：左对齐、`--text-xs`、`--color-text-muted`、底 `--color-surface-2`、
       下边框 `--color-border`、padding `--space-2 --space-3`、`white-space:nowrap`
     - `.matrix td`：下边框发丝线、padding `--space-2 --space-3`、`vertical-align:middle`
     - `.matrix tbody tr:hover`：底 `--color-surface-2`（注意 theme 覆盖块自动生效）
     - `.matrix tr.is-selected`：底 `--color-accent-weak`
     - `.matrix .num`（tabular）与 `.mono` 复用全局已有类
  4. `.rail`（待办栏容器）：无边框浮板，`display:flex; flex-direction:column;
     gap:var(--space-4);`；`.rail-title`：`--text-xs --color-text-faint`。
  5. `.checkbox`（批量选择用原生 checkbox 样式微调）：`accent-color: var(--color-ink)`。
- **验收**：vue-tsc 绿；`grep -c "\.matrix\|\.tag\b\|\.rail\b" ui.css` ≥ 3。
  **禁止**在此任务删除 `.stamp`（还有旧页面在用，T10 才删）。
- **依赖**：T1。

---

### T3 · 新组件 AppBadge.vue（应用小徽）

- **文件**：新建 `apps/web/src/components/AppBadge.vue`。
- **要求**：
  - props：`name: string`（应用名）、`colorIndex: number`（1..6，来自 faceOf）、
    `size?: "sm" | "md"`（默认 md）。
  - 形态：一行内 flex——身份色圆点（`.badge-dot`，颜色 `var(--card-face-${colorIndex})`，
    用内联 style 绑定）+ 应用名文本（`--text-sm`）。
  - 无任何卡片化装饰、无渐变；颜色只此一处身份色。
  - 复用 `utils.ts` 的散列逻辑由调用方算好传入，本组件不做散列。
- **验收**：独立组件编译绿；不 import 任何将被删除的组件。
- **依赖**：T2。

---

### T4 · 新组件 TodoRail.vue（常驻待办栏）

- **文件**：新建 `apps/web/src/components/TodoRail.vue`。
- **要求**：
  - props：`pending: RunItem[]`、`accounts: AccountItem[]`、`todayDone: { label: string; ok: number; total: number } | null`
    （今日自动完成一句话的数据，由壳组装；null 则整节不显示）、`loading: boolean`。
  - emits：`navigate: [page: PageName]`、`claim: [target: string]`、`health: [target: string]`。
  - **三节结构**（沿用 AlertsPage 的聚合语义，不发明新规则）：
    1. 「已自动完成」：`todayDone` 有值时显示一句话
       （模板：`今日已自动处理 {label}：{ok}/{total} 正常`）；null 显示
       「今日自动巡检尚未运行」。
    2. 「需要你处理」：pending 行（`account_id` + `kind · target` mono 小字 +
       `repair_reason` 人话原因 + evidence 折叠「查看详情」）+ 每条尾部
       「领取」按钮（走 emit('claim')，仅当该账号能力含 provision.run 时显示——
       能力判断由壳传入或本组件查 props.accounts 对应 app？**落定：由壳传入
       `claimable: Set<string>`（target 集合），本组件只查集合**）。
    3. 「即将到期」：accounts 里 credentials 中 `signal === "notice"` 的凭据行
       （`account_id` + `kind · 有效期至 {fmtTime}` + `.tag--notice`「注意」）+
       「去账号」ghost 按钮（emit('navigate','账号')）。
  - **空态**：三节全空时显示整栏一句「没有需要你操心的事。」
  - 复用 `utils.ts` 的 `fmtTime`；**注意**：此时 utils 还叫 `signalSeal`（T10 才更名），
    若需要 signal 文案，直接调 `signalSeal` 保持可编译，T10 同步改 import。
  - 样式：`.rail` 容器 + `.rows/.row` 行件 + `.tag`；禁止 stamp 类。
- **验收**：vue-tsc 绿；组件内 `grep -c "signalSeal\|signalText"` 与 props 一致，无 Status 字面量。
- **依赖**：T2；类型依赖 T8 的 PageName（组件内用字符串字面量 `'账号'` 传 PageName 时
  需该类型已存在——**为解依赖顺序，本任务先在 emit 类型处用 `string`，
  T8 切换时收紧为 PageName**）。

---

### T5 · 新组件 AccountDetail.vue（详情面板，替代 CardDetail）

- **文件**：新建 `apps/web/src/components/AccountDetail.vue`。
- **要求**：
  - props：`account: AccountItem | null`、`app: AppItem | null`、`busy: boolean`。
  - emits：`claim: [target: string]`、`health: [target: string]`、`close: []`。
  - 结构（从 `components/CardDetail.vue` 改造，**去掉 BizCard 引用**）：
    - 头行：AppBadge（应用名+色点）+ 账号 id（mono）+ 关闭按钮（✕，emit close）。
    - 状态行：`.tag--{signal}` + `signalSeal(signal)` 文案。
    - 「凭据」节：`cred.kind / cred.level / 有效期 {fmtTime(cred.expires_at)} / .tag`
      行列表（无凭据时空态「该账号还没有凭据记录。」）。
    - `account.evidence`（string[]）如非空：小字 evidence 段落。
    - `account.repair_hint` 如非空：「建议：{hint}」段（`.row-fix` 样式）。
    - 动作按钮：按 `app.capabilities` 能力申报驱动——`provision.run`→「领取」主按钮、
      `health.check`→「体检」次按钮（无能力则不渲染按钮，不造按钮）。
  - 空态（account 为 null）：「在矩阵里点一行账号，看它的凭据与体检详情。」
  - 布局由调用页控制（矩阵行下展开面板），本组件只出内容块。
- **验收**：vue-tsc 绿；无 BizCard/CardDetail import。
- **依赖**：T2、T3。

---

### T6 · 新页面 AccountsPage.vue（矩阵主页，产品新核心页）

- **文件**：新建 `apps/web/src/pages/AccountsPage.vue`。
- **要求**：
  - props：`accounts: AccountItem[]`、`apps: AppItem[]`、`radar: RadarRow[]`、
    `pending: RunItem[]`、`busyTarget: string | null`、
    `msg: { text: string; tone: "ok" | "warn" } | null`、`loading: boolean`、
    `loadError: string`、`todayDone: { label: string; ok: number; total: number } | null`。
  - emits：`import: [target: string]`、`claim: [target: string]`、`health: [target: string]`、
    `importAll: []`、`claimAll: []`。
  - **页头**：一句话结论大字（`page-title`）——聚合规则照 HomePage 的 headline 思路改词：
    loading=「正在打开账号面板」/ loadError=「暂时够不到服务」+副行「确认 server 已启动后点刷新」
    / pending>0=「{n} 项待处理」+「处理完即可清静」/ accounts 空=「还没有接入任何应用」+
    副行「点右侧一键导入，把本机客户端接进来」/ 有非正常=「{总数} 个账号，{n} 个需要留意」
    / 全正常=「{总数} 个账号状态正常」+「今日无事」。
    页头右侧批量动作：一键导入（n）/ 一键领取（n）——计数语义照抄 WalletPage：
    importableCount = apps 中 `!a.account_id` 的数量；claimableCount = apps 中
    `a.account_id && a.capabilities.includes("provision.run")` 的数量；禁用条件同旧页。
  - **布局**：左矩阵（flex:1.6）+ 右 TodoRail（sticky，宽约 280px，边左发丝线）；
    `@media (max-width: 900px)` 转纵向（TodoRail 下沉到矩阵下方，去 sticky）。
  - **矩阵表**（7 列，桌面）：
    | 列 | 内容 |
    |---|---|
    | 选择 | `.checkbox`，表头全选（全选=当前筛选结果全选） |
    | 应用 | AppBadge（app.display + faceOf(account_id)） |
    | 账号 | `account_id`（mono 小字）|
    | 状态 | `.tag--{signal}` + signalSeal 文案 |
    | 今日动作 | 该账号今日（本地自然日）runs 汇总：有 CLAIMED/ALREADY→「✓ 已完成」
      （.tag--ok）；有 FAILED→「✗ 未完成」（.tag--attention，原因折叠）；只有 PENDING→
      「进行中」（.tag--quiet，原文如实）；无→「未做」（.tag--quiet）。数据由壳传入的
      `runs` 计算（**加 prop `runs: RunItem[]`**），组件内只做日期比较与分组，不做语义判断 |
    | 额度 | 从 `radar` 里按 account_id 找 RadarRow：活跃包 remaining 求和按 unit 分组显示
      「{sum}/{total} {unit}」最紧的一行 + quota_low 命中→「低额」`.tag--attention`；
      无数据→「—」；radar 该账号 packages 全 remaining≤0→「已耗尽」`.tag--quiet` |
    | 凭据 | 最早到期 `earliestExpiry(account)` →「{fmtTime} 到期」；credential 有
      notice→加「临期」`.tag--notice`；无凭据→「—」 |
    | 最近操作 | 该账号最近一条 run 的 `fmtTime(started_at)`，无→「—」 |
    | 动作 | 行内「领取」（能力驱动，同 T5 判断）/「体检」/「详情」ghost 按钮 |
  - **筛选**：表头上方一行——应用筛选（select，全选+各应用 display）与状态筛选
    （select：全部/需处理(signal≠ok)/正常）；筛选只影响表格行与全选范围，不影响计数按钮。
  - **行交互**：点行（非按钮/checkbox 区）toggle 展开行下详情面板（AccountDetail，
    colspan=全列）；再点收起；同时选中态 `is-selected`。
  - **空应用邀请**：apps 中 `!a.account_id` 的应用渲染为一行虚位（沿用 slot 语义但改为
    矩阵行形态：`.tag` 风格虚线行「＋ 导入 {app.display}」，点击 emit('import', app.id)）。
  - **完全空态**（无 accounts 且无 apps）：`quietline`「还没有接入任何应用——一键导入
    把本机客户端接进来。」
  - **勾选批量**（v1 最小集）：选中行 >0 时，表头上方出现批量条「已选 {n} · 批量领取」
    （对选中且能力含 provision.run 的 target 逐个 emit('claim')——壳已有 claim 单发；
    **不做批量体检**（每日巡检已覆盖，YAGNI））。批量条禁止出现在窄屏断点以下时遮挡
    TodoRail（布局上放矩阵卡上方即可）。
- **验收**：vue-tsc 绿；组件 ≤600 行（**注意**：本文件最容易超——若超，把矩阵表体拆成
  `components/MatrixTable.vue` 子组件再验）；无 signal 之外的语义映射。
- **依赖**：T3、T4、T5；`runs` prop 的类型已存在（RunItem）。

---

### T7 · 新页面 UsagePage.vue（雷达改用量页）

- **文件**：新建 `apps/web/src/pages/UsagePage.vue`（**不是**改 RadarPage——旧文件 T10 删）。
- **要求**：
  - props：`rows: RadarRow[]`、`loading: boolean`、`collecting: boolean`、
    `msg: { text: string; tone: "ok" | "warn" } | null`、`loadedAt: string`。
  - emits：`refresh: []`、`collect: []`。
  - **数据流改为壳下发**：本组件不自持 fetch（原 RadarPage 的 load/collect 逻辑迁到壳
    T8；本组件纯展示+按钮 emit）。空态句改「还没有可观测的账号——先到「账号」页导入应用。」
  - **结构保留**（数据面不变）：每账号一块（AppBadge 头行替换 face 色横幅；
    `provider · 采集于/尚未采集` 副行）→ 活跃包节（余额大数字 + 进度条 + 已用/周期/状态 +
    耗尽预测行或「采集中——再采一帧即出耗尽预测。」）→「已耗尽的历史包（n 个）」折叠 →
    「用量汇总原话」折叠（agg summary JSON 直渲染）→「最近流水」行列表。
  - 页头：标题「用量」、副题「各家套餐余额、用量流水与耗尽预测。」、按钮 刷新 / 立即采集
    （collecting 时禁用并显示「采集中…」）、更新于 {loadedAt}。
  - forecastLine/ratioOf/fmtNum/fmtRate/aggText 等纯格式化函数**从 RadarPage 原样搬入**。
  - 低额标记：`.tag--attention`「低额」（替换 stamp）。
- **验收**：vue-tsc 绿；无 face 色横幅类；≤600 行。
- **依赖**：T2、T3。

---

### T8 · 壳切换批（四文件同任务，保证编译一致）

- **文件**：`apps/web/src/types.ts`、`apps/web/src/App.vue`、
  `apps/web/src/components/SideNav.vue`、`apps/web/index.html`。
- **要求**：
  1. **types.ts**：`PageName = "账号" | "用量" | "记录" | "设置"`。其余全部不动。
  2. **App.vue**：
     - `hashByPage = { 账号: "accounts", 用量: "usage", 记录: "log", 设置: "settings" }`。
     - **旧 hash 兼容映射**（一次写入永久免维护）：`pageByHash` 在四页映射之外加别名
       `{ home: "账号", wallet: "账号", alerts: "账号", radar: "usage", card: "账号" }`——
       命中别名时 `history.replaceState` 重写为规范 hash 再切页（避免地址栏残留旧链）。
     - 页面挂载：`账号`→AccountsPage、`用量`→UsagePage、`记录`→LogPage、else SettingsPage。
       **删除** HomePage/WalletPage/RadarPage/AlertsPage 的 import 与挂载分支
       （旧文件暂留磁盘，T10 删）。
     - **radar 数据上收壳**：新增 `radarRows = ref<RadarRow[]>([])` 与
       `collecting = ref(false)`；`loadAll()` 的 `Promise.all` 追加第 5 个请求
       `GET /api/v1/usage/radar`（失败静默——radar 拉不到时矩阵额度列显示「—」，不阻塞
       其他四项；注意 Promise.all 一败全败，所以 radar 要用
       `fetch(...).then(r => r.ok ? r.json() : []).catch(() => [])` 单独容错）。
       `collectUsage()` 动作（POST /usage/collect，逻辑照 RadarPage.summarize 原样搬）
       与 `loadedAt` 一并上收；`collecting` 状态传 UsagePage。
     - `todayDone` computed（给 TodoRail/矩阵页）：从 runs 里取本地今日、kind 含
       「health」或 provision 语义的——**落定**：`todayDone = { label: "自动巡检",
       ok: 今日 runs 中 signal==="ok" 的体检类条数, total: 今日体检类总条数 }`；
       今日无体检类 runs → null。判定「体检类」用 `kind === "health.check"`
       （该字面量已是壳 healthApp 在用的既有事实，不算新映射）。
     - `claimableTargets` computed：apps 中 `account_id && capabilities.includes("provision.run")`
       的 `id` 集合（给 TodoRail 的 claimable）。
     - 其余（轮询/主题/动作函数 alertCount 计算）不动；`alertCount` 语义保持
       （pending + 非正常卡 + notice 凭据），仍传 SideNav。
  3. **SideNav.vue**：
     - 品牌区：删除 `.brand-chip` 金箔符；改为两行文字标——第一行「卡包 Kabao」
       （`--text-lg 650`），第二行品类句「AI 账号管家」（`--text-xs --color-text-muted`）。
     - 导航四项平铺（分组标签「总览/管理」删除）：账号 / 用量 / 记录 / 设置；
       `overviewItems = ["账号", "用量", "记录", "设置"]`。
     - 角标移到「账号」项（alertCount 逻辑不变，badge 样式沿用）。
     - 刷新按钮 + `loadedAt` 保留；≤900px 断点规则保留。
  4. **index.html**：`<title>Kabao · AI 账号管家</title>`。
- **验收**：`pnpm --dir apps/web exec vue-tsc --noEmit` **必须绿**——此时旧四个页面文件
  仍在但无人引用，其类型完好即可；`grep -n "首页\|卡包\|雷达\|提醒" apps/web/src/App.vue
  apps/web/src/components/SideNav.vue apps/web/src/types.ts` 应无匹配。
- **依赖**：T3–T7 全部完成（App 要挂新页面）。

---

### T9 · 旧页换皮批（两文件，结构与数据流不动）

- **文件**：`apps/web/src/pages/LogPage.vue`、`apps/web/src/pages/SettingsPage.vue`。
- **要求**：
  1. **LogPage**：结果列 `.stamp` → `.tag`（`signalSeal` 此刻仍叫旧名，照用）；
     副标题改「操作台账——每次动作都留痕。」；表结构/证据折叠不动。
  2. **SettingsPage**：「关于」节产品行改「Kabao（卡包）· AI 账号管家」；
     其余（主题三选项名、提醒规则只读值、版本/数据位置/仓库/接口文档）全部不动。
- **验收**：vue-tsc 绿；两文件无 stamp 类引用。
- **依赖**：T2。

---

### T10 · 退役删除批（删文件 + 删 token + 删旧件 + utils 更名，一气呵成）

- **要求**（本任务结束时全库必须编译绿 + 门禁绿，拆开做会破）：
  1. **删 6 个文件**：`pages/HomePage.vue`、`pages/WalletPage.vue`、
     `pages/AlertsPage.vue`、`pages/RadarPage.vue`、`components/BizCard.vue`、
     `components/CardDetail.vue`。
  2. **tokens.css 删 T1 标注的全部「待退役」token**（三主题覆盖块里的对应行一并删，
     含 dark 块的 card-face-*-hi/lo）。
  3. **ui.css 删 `.stamp` 及五变体**（`.tag` 已接管）。
  4. **utils.ts**：`signalSeal` 更名 `signalText`（注释同步去「墨印」措辞，改
     「signal 五分类 → 结果徽文案」）；全库 import 同步改（此刻引用方只剩
     TodoRail/AccountDetail/AccountsPage/UsagePage/LogPage）。
     `fmtTime/faceOf/earliestExpiry` 不动。
  5. `grep -rn "stamp\|signalSeal\|BizCard\|CardDetail\|HomePage\|WalletPage\|AlertsPage\|RadarPage\|chip-gold\|face-seal\|face-text\|slot-dash\|shadow-lift\|motion-reveal\|card-face-.-hi" apps/web/src`
     **零匹配**（card-face 单值保留所以只查 -hi/-lo）。
- **验收**：vue-tsc 绿；`uv run python scripts/verify_project.py --project .`（不带 --test 也行，
  但建议带）全绿——重点看第 5 项 token 闭合与第 8 项 600 行。
- **依赖**：T6–T9 全部完成。

---

### T11 · ADR 落盘（两份新文档）

- **文件**：`docs/adr/ADR-009-矩阵重构与品类句调整.md`、
  `docs/adr/ADR-010-一人多账号领域模型方向.md`（**只写方向，不写实现**）。
- **ADR-009 要点**（结论式短文，参照 ADR-007 的行文密度）：
  1. 裁决一：IA 从六页（首页/卡包/雷达/记录/提醒/设置）收敛为四页
     （账号/用量/记录/设置），**矩阵即首页**——账号矩阵为默认页与产品本体。
  2. 裁决二：品类句「你的 AI 卡包 / AI Card Wallet」退役，改「AI 账号管家 / AI Account
     Butler」；产品名 Kabao（卡包）不动；ADR-007 其余词汇继续有效。
  3. 裁决三：视觉去卡化——真比例卡/金箔/墨印/卡扇退役，中性基底 + 应用小徽；
     主题三套机制与名不变。
  4. 背景：竞品（doubao/workbuddy 等）均为极简界面；原视觉装饰多信息少，且未突出
     「AI 管家替你打理」的产品心智；矩阵形态最贴「一人多账号多应用的繁琐操作统一化」初衷。
- **ADR-010 要点**：
  1. 现状：M1 契约 = 一应用一账户（Account 为应用下单例）。
  2. 目标方向（R4/R5 前置）：Account 变应用下集合；target 编址 = 应用 + 账号标识；
     connector import 返回多账号；幂等/调度/领取按账号粒度；vault 凭据按账号隔离。
  3. 影响面：core 领域模型与 usecases、engine bridge 装配、server 契约（accounts/runs
     的键位）、web 矩阵（多账号=多行，天然兼容，无需再改 IA）。
  4. 风险与开放问题：同应用多开的会话隔离（多 profile/双开）取证；各连接器
     幂等语义按账号重验；契约变更波及 MCP 三工具。
  5. 状态：**占位**（Proposed）——本文只定方向与边界，实现另立 spec。
- **验收**：两文件存在且为结论式行文；`docs/adr/` 无编号冲突。
- **依赖**：T10（文档记录的是已实现终态）。

---

### T12 · 文档修订批（六处同步）

- **要求**：
  1. `docs/specs/application/A3-01-信息架构与核心页面.md` **全文重写**：
     §1 侧栏（四项平铺+品牌区新形态+角标在「账号」）；§2 页面规格（账号矩阵页
     全规格=本任务书 T6 的列定义/筛选/批量/空态；用量页；记录页；设置页）；
     §3 组件结构（新组件清单 + App.vue 数据流含 radar 上收与旧 hash 映射）；
     §4 渲染纪律（原四条保留，加「身份色只允许出现在 AppBadge」）。
  2. `docs/design-decisions.md`：D1 品类句改「Kabao · AI 账号管家」+引用 ADR-009；
     D2 改 v5（中性工作台基底：去卡面/金箔/墨印/卡扇；小徽单色身份色；退役 token 清单；
     三主题值微调说明）；D3 改矩阵四页 IA + 旧 hash 兼容映射说明。
  3. `docs/conventions/03-命名与文案规范.md` L16 品类句同步。
  4. `docs/specs/architecture/A1-03-品牌与业务语言标准.md`：定位一句话、品类句、
     §4 IA、§5 主题相应段落同步（引用 ADR-009，不复制正文）。
  5. `README.md`：首行 tagline 改「**One butler for all your AI accounts.** 你的所有
     AI 账号，交给一个管家——签到、领取、计量、调度，一件不落。」；
     文档导航表 A3-01 行「五导航」→「四页 IA」。
  6. `docs/superpowers/specs/2026-11-12-kabao-wallet-visual-design.md` 文件头部加一行
     引用块：「> **已被 2026-11-13 矩阵改版取代**（ADR-009），本文仅存档。正文不改。」
- **验收**：`grep -rn "AI 卡包" docs/ README.md` 仅剩历史存档类文件可留（wallet spec 存档
  行除外）；`grep -rn "首页.*卡包.*雷达" docs/` 无 A3-01/design-decisions 匹配。
- **依赖**：T11。

---

### T13 · 终验 + 提交序列

- **终验清单**（全过才算完成）：
  1. `uv run python scripts/verify_project.py --project . --test` 九项全绿（含 pytest 全量
     与 vue-tsc）；`git diff --stat` 确认 server/core/engine/sdk/connectors/mcp/desktop/cli
     **零改动**。
  2. 真机/浏览器走查（`pnpm dev:web` + server 在 8000）：
     - 三主题（卡纸与墨/墨夜/暖纸）× 两断点（>900px / ≤900px）过四页；
     - 矩阵：空态邀请行 / 应用+状态筛选 / 点行展开详情 / 全选+批量领取 / 一键导入（n）
       与一键领取（n）计数正确；≤900px 时 TodoRail 下沉、额度/凭据/最近操作列隐藏。
     - 旧 hash 直链 `#/home`、`#/wallet`、`#/radar`、`#/alerts` 均重定向到对应新页。
     - 用量页「立即采集」结果如实分列；记录页含体检类 kind 条目。
     - 对比度抽查：`.tag` 五色在白底 ≥4.5:1（与旧 stamp 同值系，理论无回归）。
  3. **提交序列**（每批一个意图，钩子强制格式）：
     ```
     feat:[0]: 矩阵改版·token 与通用件地基        ← T1+T2
     feat:[0]: 新增应用小徽与待办栏详情组件        ← T3+T4+T5
     feat:[0]: 账号矩阵页与用量页落地              ← T6+T7
     feat:[0]: 壳切换四页 IA 与旧链兼容            ← T8
     refactor:[0]: 记录与设置页去印章化            ← T9
     refactor:[0]: 退役卡面组件与装饰 token        ← T10
     docs:[0]: ADR-009/010 与文档体系同步          ← T11+T12
     ```
- **依赖**：T12。

---

## §E 明确不做（执行模型禁止自作主张）

- 不做批量体检端点/按钮（每日巡检 R3-2 已覆盖）。
- 不做对话式/LLM 管家（定位叙事走 TodoRail 文案，不造假 AI）。
- 不动 server 契约、不加端点、不跑 gen:sdk。
- 不做「一人同应用多账号」的领域实现（ADR-010 占位即可；矩阵天然多行兼容）。
- 不删/改任何 pytest 测试与 .github/workflows。
- 不改 apps/web 的构建配置（vite/tsconfig/package.json）。
- 不引入图标库/字体库；需要图标一律字符（✓ ✗ ＋ ✕）或纯 CSS。

## §F 风险提示（给执行模型的避坑）

1. **T8 是编译一致性批次**：types/App/SideNav 必须同一任务内改完，拆开必破。
2. **T10 是删除一致性批次**：文件/token/类名/函数名四类退役必须同批完成并跑门禁，
   中间态会 FAIL（verify 第 5 项 token 闭合最敏感）。
3. **radar 请求失败静默**：壳 loadAll 里 radar 用独立 catch 返回 []，
   千万别进 Promise.all 主链（一败全败会把账号页也打死）。
4. **今日动作列的日期比较用本地自然日**（`new Date()` 的年月日比对 started_at），
   不引入时区库。
5. **AccountsPage 行数**：矩阵 7 列 + 筛选 + 批量 + 空态容易破 600 行，
   预留拆 `MatrixTable.vue` 的方案，别硬塞。
