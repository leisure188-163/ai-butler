# Kabao 业务子域分包任务书 · 壳拆分 + 用例层分包

> **给执行模型的说明**：本任务书自足完备，按 T0→T10 顺序执行，每任务有独立验收。
> 设计裁决已经用户批准（2026-11-14）：方案 B「端点单源 + 分域动作」+ core 用例层按用例边界分包。
> 执行前提：先读 `docs/conventions/02-开发红线.md`（七条红线）与
> `docs/conventions/04-代码文件组织与长度约束.md`（本单同时给它补前端细则）。
> 环境坑：门禁/构建前先 `eval "$(fnm env --shell zsh)"`（系统 node 读不了 lockfile v9）；
> 门禁命令 `uv run python scripts/verify_project.py --project . --test`（九项）。

## §A 背景与基线（2026-11-14 实测）

用户主诉：业务模块增长后前后端会混堆，维护成本线性恶化。盘点结论：

- 后端/核心层已按域分包（server routes 四域模块、core domain 九概念一文件、
  engine 按端口职责、connectors 一连接器一域）——不成立；
- 真实混点 = 两个**单文件超载**：
  - `apps/web/src/App.vue` **559 行**（距 600 硬上限剩 41）：壳混装 5 端点数据编排、
    全部动作（import/claim/health/批量）、主题、hash 路由、聚合派生、采集文案；
  - `packages/core/src/kabao_core/application/usecases.py` **541 行**（剩 59）：
    五个用例域堆一文件（conventions/04 §4 存量口径已挂账「触碰时拆」，本单即触碰）。

本单同时把前端分包规则固化进 conventions/04，使「加一个端点/加一个动作/加一个域」
各有唯一落位，与后端四域模块同构。

**全程约束：契约零改动**——不加端点、不改请求/响应形状、不跑 `gen:sdk`、
`openapi.sha256` 不动；`apps/server` `packages/engine` `packages/connectors` `packages/sdk`
`apps/mcp` `apps/desktop` `apps/cli` 的**源码零改动**（usecases 包转换靠 `__init__.py`
再导出保引用方零改动）。

## §B 目标文件布局（完成后形态）

### web（方案 B）

```
apps/web/src/
  api.ts                   ← 端点访问单源：apiBase + ApiError + fetchJson 薄封装 +
                             按域分节端点函数（accounts/apps/runs/usage/系统，~110 行）
  composables/
    useHashRoute.ts        ← hash 路由域（~75 行）
    useShellData.ts        ← 数据源域（~130 行）
    useAccountActions.ts   ← 账号域动作（~190 行）
    useUsageActions.ts     ← 用量域动作（~70 行）
    useSettings.ts         ← 设置 + 主题域（~75 行）
  App.vue                  ← 纯装配（~130 行：composable 组装 + schedulePoll + template + style）
```

pages/ components/ styles/ types.ts utils.ts **一行不动**（模板绑定名不变 → props/emit 零变化）。

### core

```
packages/core/src/kabao_core/application/usecases/
  __init__.py           ← 纯再导出 + __all__（12 个公共名逐一核对，~40 行）
  execute_action.py     ← 动作执行域（A2-01 §3）：~185 行
  health_scan.py        ← L0 底座（A4-01）：~145 行
  register_account.py   ← 名册（A2-01 §1）：~30 行
  list_pending.py       ← 待处理聚合（A3-01）：~25 行
  collect_usage.py      ← 用量采集（R2）：~125 行
```

## §C 任务序列

### T0 · 基线门禁

- `eval "$(fnm env --shell zsh)" && uv run python scripts/verify_project.py --project . --test`
  九项 PASS；`git status --short` 干净（只有本任务书未跟踪）。
- 记录基线：`wc -l apps/web/src/App.vue`（=559）、
  `wc -l packages/core/src/kabao_core/application/usecases.py`（=541）。
- 读 `App.vue` 全文与 `usecases.py` 全文（拆分 = 段落搬迁，不重写逻辑）。

### T1 · api.ts 端点访问单源（新文件，不影响编译）

`apps/web/src/api.ts`，结构：

- `const apiBase = "/api/v1";`（自 App.vue L31 迁入）
- `export class ApiError extends Error { status: number; detail?: string }`——
  薄封装 `fetchJson`：`!resp.ok` 时解析 body 取 `detail`，抛 `ApiError`。
  **语义保真**：各调用点现行的 `body.detail ?? \`XX失败（HTTP ${resp.status})\`` 文案
  由 composable 的 catch 侧拼装，api 层只透传 detail/status，不改写文案。
- 按域分节端点函数（注释节头对齐 server routes 四域）：
  - 账号域：`getAccounts(): Promise<AccountItem[]>`
  - 应用域：`getApps(): Promise<AppItem[]>`、`importApp(target)`（POST `/apps/{target}/import`）、
    `importAllApps(): Promise<ImportResult[]>`（POST `/apps/import-all`）
  - 运行域：`getRuns(): Promise<RunItem[]>`（GET `/runs?limit=50`）、
    `getPending(): Promise<RunItem[]>`（GET `/pending?limit=20`）、
    `createRun(body: { target: string; kind?: string }): Promise<RunItem>`（POST `/runs`）、
    `claimAllRuns(): Promise<RunItem[]>`（POST `/runs/claim-all`）
  - 用量域：`getRadar(): Promise<RadarRow[]>`——**独立容错语义随函数走**（非 ok 或网络失败
    一律 resolve `[]`，注释说明「失败静默为 []（矩阵额度列显示「—」），不拖垮主数据」）、
    `collectUsage(): Promise<CollectOutcome[]>`（POST `/usage/collect`）
  - 系统域：`getOpenApiInfo(): Promise<{ title: string; version: string } | null>`——
    容错语义随函数走（任何失败 resolve null，注释「dev 代理可能不转发 /openapi.json」）
- 类型一律 import 自 `./types`（红线 4：DTO 派生单源不动）。
- 响应 json 断言 `as` 与 App.vue 现行写法一致（不新增运行时校验）。

**验收**：`pnpm --dir apps/web exec vue-tsc --noEmit` 绿（新文件暂无人引用也应零报错；
若有 unused 报错则收紧导入）。

### T2 · useHashRoute（新文件）

`apps/web/src/composables/useHashRoute.ts`：自 App.vue L33–71 **原样搬迁**
`hashByPage` / `legacyHashByPage` / `pageByHash` / `resolveActive` / `onHashChange` /
`navigate`，包成 `export function useHashRoute()`：

- 内部持 `const active = ref<PageName>(resolveActive())`；
- 监听内收：`onMounted(() => { if (!location.hash) history.replaceState(null, "", `#/${hashByPage[active.value]}`); window.addEventListener("hashchange", onHashChange); })` +
  `onBeforeUnmount(() => window.removeEventListener("hashchange", onHashChange))`
  （App.vue onMounted 的 L471–472 两行随迁，`loadAll()/schedulePoll()` 留壳）；
- 返回 `{ active, navigate }`。

**验收**：vue-tsc 绿。

### T3 · useShellData（新文件）

`apps/web/src/composables/useShellData.ts`：自 App.vue **原样搬迁** L73–136 + L448–468：

- 状态：`accounts/apps/runs/pending/radarRows/serverInfo/loading/loadError/loadedAt/usageLoadedAt`；
- `loadAll()`：改用 api 端点函数（`Promise.all([getAccounts(), getRuns(), getPending(), getApps(), getRadar()])`；
  radar 容错已内置于 api.getRadar，这里不再 catch）；
  `loadedAt`/`usageLoadedAt` 赋值与 `loadError` 文案逐字保留；
- `fetchServerInfo()` 改用 `api.getOpenApiInfo()`（容错已在 api 层，本地只剩赋值）；
- 派生：`todayDone` / `alertCount` 两个 computed 原样随迁（isToday 从 ../utils 导入）；
- 返回上述全部（含 `loadAll`）。

**验收**：vue-tsc 绿。

### T4 · useAccountActions（新文件）

`apps/web/src/composables/useAccountActions.ts`：
`export function useAccountActions({ refresh }: { refresh: () => Promise<void> })`：

- 自持 `busyTarget` / `actionMsg`（**核查过：collectUsage 从不碰 busyTarget，无跨域共享**）；
- 自 App.vue L138–337 **原样搬迁**六个动作：`importApp` / `claimApp` / `healthApp` /
  `importAllApps` / `claimAllApps` / `claimMany`；
- fetch 调用换成 api 函数：`!resp.ok` 分支改为 `catch (e)`（`e instanceof ApiError` →
  文案 `e.detail ?? \`XX失败（HTTP ${e.status}）\``）；**成功路径文案逐字不动**；
  `claimMany` 的逐项 try/catch 与 `${target}：请求失败` 兜底保留；
  **网络异常传播行为保持原样**（除 claimMany 既有 per-item catch 外不加新 catch）；
- **不借机改语义**：CLAIMED/ALREADY 判定先例原样保留（现状即有，非本单裁决范围）；
- 每个动作 `finally { busyTarget.value = null; await refresh(); }` 保持不变；
- 返回 `{ busyTarget, actionMsg, importApp, claimApp, healthApp, importAllApps, claimAllApps, claimMany }`。

**验收**：vue-tsc 绿。

### T5 · useUsageActions（新文件）

`apps/web/src/composables/useUsageActions.ts`：
`export function useUsageActions({ refresh, radarRows }: { refresh: () => Promise<void>; radarRows: Ref<RadarRow[]> })`：

- 自持 `collecting` / `usageMsg`；
- 自 App.vue L339–387 **原样搬迁** `collectUsage` + `summarizeCollect`
  （radarRows 经参数注入，display_name 回退逻辑逐字保留；「采集失败——够不到本机服务。」
  catch 分支保留；ApiError 分支同 T4 规则）；
- 返回 `{ collecting, usageMsg, collectUsage }`。

**验收**：vue-tsc 绿。

### T6 · useSettings（新文件）

`apps/web/src/composables/useSettings.ts`：自 App.vue L389–434 **原样搬迁**：

- `THEME_NAMES` / `loadSettings` / `updateSettings` / `applyTheme` / `systemDark` 监听；
- **THEME_NAMES TDZ 陷阱注释（L390–391）随迁**，声明顺序保持：常量先于使用；
- 监听内收：`systemDark.addEventListener("change", applyTheme)` 与
  `watch(() => settings.value.theme, applyTheme)`、`applyTheme()` 首调留在 composable 体内，
  `onBeforeUnmount(() => systemDark.removeEventListener("change", applyTheme))` 内收；
- 返回 `{ settings, updateSettings }`。

**验收**：vue-tsc 绿。

### T7 · App.vue 收壳（编译一致性批——T2–T6 五件 + 本批同批验收）

- script 段重写为装配（对齐 api.py 纯聚合器纪律——壳禁业务逻辑）：

  ```ts
  const { active, navigate } = useHashRoute();
  const data = useShellData();
  const account = useAccountActions({ refresh: data.loadAll });
  const usage = useUsageActions({ refresh: data.loadAll, radarRows: data.radarRows });
  const { settings, updateSettings } = useSettings();
  ```
  解构保持模板绑定名不变（或直接 `data.accounts` 式引用——二选一，但模板 props
  绑定与事件名**零变化**）；`schedulePoll` + `watch(autoRefresh/intervalSec)` +
  `onMounted(() => { data.loadAll(); schedulePoll(); })` 留壳（~15 行 wiring）；
- template（L484–536）与 style（L538–559）**逐字不动**；
- 删除全部已迁走逻辑。

**验收**（编译一致性批，缺一 retry）：
1. `pnpm --dir apps/web exec vue-tsc --noEmit` 绿；
2. `grep -n "fetch(\|hashByPage\|THEME_NAMES\|summarizeCollect" apps/web/src/App.vue` 零匹配；
3. `wc -l apps/web/src/App.vue` ≤ 160；
4. `git diff --stat -- apps/web/src/pages apps/web/src/components apps/web/src/styles apps/web/src/types.ts apps/web/src/utils.ts` 为空；
5. 全量门禁 `uv run python scripts/verify_project.py --project . --test` PASS。

### T8 · core 用例层分包（import 兼容批）

- 删 `usecases.py`，新建 `usecases/` 包，五模块**按 §B 边界搬迁**（段落原样，含全部
  注释与 spec 引用号 A2-01/A4-01/R2）：
  - `execute_action.py`：L60–236（UnsupportedAction / InvalidRequest / DryRunNotSupported /
    RunRequest / idempotency_key / ExecuteAction）；
  - `health_scan.py`：L238–376（`_CRED_EVENT_LEVELS` / `_ACCOUNT_SEVERITY` 私有常量随迁 +
    ScanCredentialExpiry + AssessAccountHealth）；
  - `register_account.py`：L379–401（RegisterAccount）；
  - `list_pending.py`：L404–422（ListPending）；
  - `collect_usage.py`：L425–541（CollectOutcome + CollectUsage）；
- 各模块 import 自 `kabao_core.application.ports` 与 `kabao_core.domain.*`（原样），
  **模块间零横向依赖**；
- `__init__.py`：模块 docstring 指路（各域 → 各文件）+ `from .x import ...` 纯再导出 +
  `__all__`。**公共名清单（逐一核对，漏一 = 引用方 ImportError）**：
  `UnsupportedAction, InvalidRequest, DryRunNotSupported, RunRequest, idempotency_key,
  ExecuteAction, ScanCredentialExpiry, AssessAccountHealth, RegisterAccount, ListPending,
  CollectOutcome, CollectUsage`（12 个）；
- 引用方 17 处（bootstrap/bridge/checkin/registry/cli/server routes/tests）**零改动**。

**验收**（import 兼容批）：
1. `uv run pytest packages/core/tests packages/engine/tests packages/connectors/tests apps/server/tests -q` 全绿；
2. `grep -rn "application.usecases" --include="*.py" apps packages | grep -v "application/usecases/\|application/usecases import\|from kabao_core.application import usecases"` 无意外形态；
3. `git diff --name-only` 只含 `packages/core/src/kabao_core/application/usecases*`；
4. 全量门禁 `uv run python scripts/verify_project.py --project . --test` PASS。

### T9 · 规范入册 + 记账

- `docs/conventions/04-代码文件组织与长度约束.md`：
  - 新增「### 2.4 前端（apps/web/src/）」分包细则（**不重排既有 §2.1–2.3 编号**）：
    壳 App.vue = 装配器（禁业务逻辑，对齐 api.py 纪律）；composables 按职责分域
    （路由/数据源/域动作/设置）；`api.ts` = 端点访问单源（URL 与响应形状只写一处，
    DTO 派生单源仍是 types.ts，红线 4 不变）；pages/ 即页面域，加页不加分包层；
  - §2.3 表加一行：`composables/api.ts | 按职责/按域 | 把 fetch 散装进组件`；
  - §3 已定稿对照补一行：`App.vue 559 行壳 + usecases.py 541 行 → 装配壳 + 五 composables
    + api.ts 单源；usecases 五用例模块包（2026-11-14）`；
  - §4 存量口径：删除 usecases.py 条目（销账），其余不动。
- `docs/STATUS.md`：现状段补分包改造结论；里程碑表加一行
  「**业务子域分包（壳拆分+用例层分包）** | App.vue→装配壳+五 composables+api.ts；usecases.py→五用例包；前端分包规则入册 conventions/04 §2.4 | **✅ 完成（2026-11-14）**」。

### T10 · 终验 + 提交序列

- `eval "$(fnm env --shell zsh)" && uv run python scripts/verify_project.py --project . --test`
  九项 PASS；`git status --short` 只剩待提交清单；
- `git diff --name-only` 核对改动面 = web 壳组 + core usecases 包 + 三文档，**契约与
  server/engine/connectors/sdk/mcp/desktop/cli 源码零改动**；
- 提交序列（钩子强制 `<type>:[<需求单号>]: <中文主题>`，无单号占位 `[0]`，无句号，≤100 字）：

  ```
  refactor:[0]: web 壳拆 composables 与端点单源        ← T1–T7
  refactor:[0]: core 用例层按用例边界分包              ← T8
  docs:[0]: 前端分包规范入册与状态记账                 ← T9（含本任务书 plans/ 目录）
  ```

- 每批提交后工作区 = 最终态，门禁已在 T10 跑过即满足红线 7；提交后 `git status` 干净收工。

## §E 明确不做（执行模型禁止自作主张）

- 不加/不改任何端点与数据形状；不跑 `gen:sdk`；`openapi.sha256` 不动。
- 不动引用方 import（bootstrap/bridge/checkin/registry/cli/server/tests 全部零改动）。
- 不改任何文案语义与判定逻辑（CLAIMED/ALREADY 先例原样；文案逐字迁移）。
- 不拆 AccountsPage.vue 496 行（挂账 0① 另案）；不动 pages/components/styles/types/utils。
- 不引入 pinia / vue-router / 任何新依赖；不做前端单测（无先例，YAGNI）。
- 不重排 conventions/04 既有小节编号；不改 pytest 测试与 .github/workflows。

## §F 风险提示（给执行模型的避坑）

1. **T7 是编译一致性批**：composables 五件 + App.vue 切换必须同批验收，中间态 vue-tsc
   必红（同矩阵改版 T8 教训）。
2. **T8 是 import 兼容批**：`__init__.py` 再导出名册必须与原文件公共面逐一 grep 核对；
   私有名（`_CRED_EVENT_LEVELS` / `_ACCOUNT_SEVERITY`）不导出，随 health_scan.py 走。
3. **THEME_NAMES TDZ**：迁进 useSettings 时保持「常量声明先于 loadSettings 使用」，
   陷阱注释随迁，否则存档主题永远静默回退 system。
4. **radar / openapi 容错语义随 api 函数走**（getRadar 永不 throw、getOpenApiInfo 永不
   throw），composable 侧不得重复 catch；loadAll 主链只对四个主端点失败负责。
5. **ApiError 只管 !ok**：网络 TypeError 传播行为与现状一致（claimMany 既有 per-item
   catch 除外）——不得加新兜底（红线 5：显式报错不静默）。
6. 行数预期是**软目标**（400 软警戒内），超了先看是否段落切错，不为凑数硬拆
   （conventions/04 §1.4）。
