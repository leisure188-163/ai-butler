# 任务书 · Butler 重定位（阶段一全深度改名 + 阶段二六页 IA）

> **给执行模型的说明**：本任务书自足完备，按 T0→T11 顺序执行，每任务有独立验收。
> 上位设计 = `docs/superpowers/specs/2026-11-14-butler-repositioning-design.md`
> （用户五问裁决已双通过）。执行前必读 §A 全局铁律与 §B 词表 v2；任务书没写的细节，
> 以仓库现有代码风格与 `docs/conventions/02-开发红线.md` 为准，**不要发明新规则**。
> 仓库根 = 当前目录（含 `packages/ apps/ docs/`）。除任务书列出的文件外一律不动。

## 产品定位变更（一句话）

产品从「Kabao（卡包）· AI 账号管家」重定位为 **「AI 智能助手管家」**（工程标识 **Butler**，
英文对标 AI Assistant Butler，仅文档/关于页用）。两阶段串行：
**阶段一全深度改名（页面结构不动）→ 阶段二六页 IA（纯 apps/web，契约零改动）**。

## 改名映射总表（旧 → 新，全任务书统一口径）

| 层 | 旧 | 新 |
|---|---|---|
| Python 发行包 ×6 | kabao-core / -engine / -connectors / -server / -cli / -mcp | butler-core / -engine / -connectors / -server / -cli / -mcp |
| Python import 名 | kabao_core / kabao_engine / kabao_connectors / kabao_mcp | butler_core / butler_engine / butler_connectors / butler_mcp（server、cli 模块名本就无 kabao） |
| src 内层目录 | packages/*/src/kabao_*、apps/mcp/src/kabao_mcp | butler_*（packages/core 等外层目录名、src/server、src/cli 不动） |
| npm | @kabao/sdk、kabao-desktop、根包 kabao-frontend | @butler/sdk、butler-desktop、butler-frontend（apps/web 包名 `web` 不变） |
| 桌面端 | productName `Kabao` / appId `com.kabao.app` | `Butler` / `com.butler.app` |
| CLI 命令 | `kabao`、`kabao-mcp` | `butler`、`butler-mcp` |
| 环境变量 | `KABAO_DB` / `KABAO_SCHEDULE` / `KABAO_SERVER_URL` / `KABAO_` 前缀剥离 | `BUTLER_DB` / `BUTLER_SCHEDULE` / `BUTLER_SERVER_URL` / `BUTLER_` |
| 数据库 | 数据根目录基名 `kabao` + `kabao.db(-wal/-shm)` | 基名 `butler` + `butler.db`（首运自动迁移，旧库旧目录保留） |
| 前端存储键 | `kabao.settings.v1` | `butler.settings.v1`（读旧键兼容一次搬迁，旧键不删） |
| server 标题 | FastAPI `title="kabao"` | `title="butler"`（openapi 指纹随批4 刷新，见 §F-1） |
| MCP server 名 | `MCPServer("kabao", …)` | `MCPServer("butler", …)` |
| 内部 job 名 | kabao-expiry-scan / kabao-checkin / kabao-usage-scan | butler-*（bridge 内常量，无测试断言） |
| 品类句 | 「Kabao · AI 账号管家」 | **退役**——产品名即「AI 智能助手管家」，无独立品类句 |
| 主题显示名 | 卡纸与墨（浅）/ 墨夜 / 暖纸 | **纸墨**（浅）/ 墨夜 / 暖纸（`THEME_NAMES` 内部值 paper/dark/warm 机制全不动） |
| 仓库远端 | gitee `hiclaw_520/ai-kabao` | `ai-butler`（Gitee 网页改名 = **用户手工步**；本地切 remote 在批5） |
| 文档自称 | Kabao（卡包） | Butler（智能助手管家） |

---

## §A 全局铁律（每个任务都要遵守，违反即返工）

1. **契约纪律**：API 形状/端点/字段零变化；`openapi.sha256` 全程只允许批4 的一次
   指纹刷新（FastAPI title 属契约元数据，改后必须 `pnpm gen:sdk`，且 `schema.d.ts`
   必须 diff 为空——title 不入类型）。除此之外**不跑 gen:sdk**。阶段二追加：
   server/engine/connectors/sdk/mcp/desktop/cli 源码零 diff。
2. **工程层不动（ADR-007 两层原则延续）**：协议七字面量、连接器业务码字典
   （PROTOCOL.md 的 code 表）、领域实体名（Account/Run/Event）、五分类 signal 字面量
   `ok/notice/attention/danger/quiet` 一律不改名。
3. **历史不改写**：`docs/adr/ADR-001..010` 与 `ADR-模板.md`、`docs/specs/legacy/A0-01`、
   `docs/superpowers/`（历史任务书/设计书）**保留原词不改写**；新文档（ADR-011/012）
   标注取代关系。git 历史不改写。
4. **词表 v2 纪律**：用户可见文案按 §B 执行；连接器原始返回文本不算 UI 文案
   （provider 名等数据直渲染纪律不变，不扫）。
5. **每批过门禁**：`eval "$(fnm env --shell zsh)" && uv run python scripts/verify_project.py
   --project . --test`（九项）PASS 才能提交；pytest 基线 459 passed / 10 skipped。
6. **文件长度**：任何代码文件 ≤600 行（verify 第 8 项机检）；一业务域一模块
   （conventions/04）。
7. **不加依赖**：不新增 npm/pip 依赖，不引 vue-router/pinia，不改构建配置与 CI
   workflow，不删改任何 pytest 测试结构（批4 迁移测试改写除外——那是被迁移机制本身
   要求的）。
8. **提交规范**（钩子强制）：`<type>:[<需求单号>]: <中文主题>`，无单号占位 `[0]`，
   主题动词开头、无句号、≤100 字。每批一个提交（序列见各任务）。
9. **uniapp 不动**：`apps/uniapp` 无 kabao 引用、无 package.json，本单零接触。

## §B 词表 v2（用户可见文案以此为准；批1 收编进 conventions/03）

**新增正式词**：智能助手管家（产品名）、应用 App、账户 Account、仪表盘 Dashboard、
流量 Traffic、日志 Logs、导入 Import、领取 Claim、体检 Health check、
余额/额度 Balance/Quota、提醒 Alert、时间表 Schedule。

**退役禁用**：卡、卡包、泊位、**账号（→账户）**、**用量（页名级→流量；域内数据语境
保留**，如「用量流水」「已用量」等数据行文案可留）、航海系全词。

**执行口径**：页名级（导航项/页标题/页副题）必须换；域内数据语境酌情保留；
工程层标识（代码标识符、env、db 文件名）不属文案，按映射总表走。

## §C 环境与常用命令（macOS 开发机）

```bash
# 前端工具链前置（系统 node 20 打不开 lockfile v9，必须先走 fnm 的 node 24）
eval "$(fnm env --shell zsh)"

# 全量门禁（九项：结构/核心纯净/依赖方向/桥闭合/token闭合/契约指纹/空包/600行/测试）
eval "$(fnm env --shell zsh)" && uv run python scripts/verify_project.py --project . --test

# web 类型检查（改动后随时跑）
eval "$(fnm env --shell zsh)" && pnpm --dir apps/web exec vue-tsc --noEmit

# 契约指纹刷新（仅批4 允许跑一次）
eval "$(fnm env --shell zsh)" && pnpm gen:sdk

# 本地起服务（走查用）
uv run uvicorn server.main:app --host 127.0.0.1 --port 8000
eval "$(fnm env --shell zsh)" && pnpm dev:web
```

---

## §D 任务列表

### T0 · 基线门禁（只读，不改代码）

- **目标**：确认起点全绿，后续任何 FAIL 才可归因于本次改动。
- **步骤**：跑 §C 门禁九项记录 PASS；`git status --short` 干净；
  `grep -ril kabao --exclude-dir=.git --exclude-dir=node_modules --exclude-dir=__pycache__ . | wc -l`
  记录基数（约 172 个文件，含 uv.lock/pnpm-lock——随批2/批3 重生成清零）。
- **验收**：门禁九项全绿；否则停下先修基线，与本任务书无关的破损上报，不顺手修。
- **依赖**：无。

---

### T1 · 批1 文档先行（只改 docs，代码零动）

- **要求**：
  1. **新建 `docs/adr/ADR-011-Butler更名与品类句退役.md`**（结论式短文，参照 ADR-007
     行文密度）：裁决一 = 品牌二次更名，产品定名「AI 智能助手管家」/工程标识 Butler，
     ADR-007 的品牌裁决由本裁决取代、其两层词汇原则延续；裁决二 = 引用设计书映射
     总表（六包/src 内层/npm/CLI/env/db/存储键/主题显示名/远端）；裁决三 = 词表 v2
     新增与退役收编 conventions/03 v3；裁决四 = 数据迁移复用 A1-03 §7 机制加两腿
     （db 腿 + localStorage 腿），幂等/旧件保留/审计事件。背景写竞品语系收窄心智、
     「管家」叙事对齐调度与迁移定位、用户五问裁决（2026-11-14）。
  2. **重写 `docs/specs/architecture/A1-03-品牌与业务语言标准.md`**（v2）：§1 定位
     一句话改管家叙事；§3 词表 v2；§6 命名标准当前值全表换新值（含桌面端
     Butler/com.butler.app、数据目录基名 butler）；§7 数据自动迁移加 db 腿
     （kabao.db→butler.db，旧源链：数据根/kabao/kabao.db → CWD/kabao.db →
     数据根/ai-marina/marina.db → CWD/marina.db，幂等/保留/审计/显式 BUTLER_DB
     不迁移）与 localStorage 腿（读新键缺失则读旧键写入新键，旧键保留）；其余节保留。
  3. **重写 `docs/conventions/03-命名与文案规范.md`**（v3）：词表 v2 收编为强制规范
     （新增/退役/工程层不动/连接器原始返回文本不算 UI 文案）；品类句概念退役
     （产品名即「AI 智能助手管家」）。
  4. **更新 `docs/conventions/00-项目配置.md`**：frontmatter 与基础信息表
     （{project}=butler、{projectName}=butler（中文「智能助手管家」）、{basePackage}=
     butler_core）；技术栈表（CLI 入口 butler、MCP 入口 butler-mcp、{stack-db}
     SQLite（butler.db））；`{gate-cmd}` 文案「八项」改「九项」；`{repo-remote}` 行
     **保留现值 ai-kabao** 并注明「更名中，批5 切 ai-butler」（其余批次推送仍走现值）。
  5. **更新 `docs/design-decisions.md`**：D1 品类句改「产品名即 AI 智能助手管家，品类句
     概念退役」+ 引 ADR-011；D2 主题显示名 纸墨（机制/token 不变）；D3 尾部加一行
     「2026-11-14 起品牌词由 ADR-011 更新，本条 IA 裁决继续有效」。
- **验收**：各文件存在且行文结论式；
  `grep -rn "Kabao（卡包）· AI 账号管家" docs/conventions/00*.md docs/conventions/03*.md docs/specs/architecture/A1-03*.md`
  零匹配；跑一次九项门禁确认无意外（docs 不进门禁，此为防手误）。
- **依赖**：T0。

---

### T2 · 批2 Python 六包改名（机械替换，459 测试全绿为准）

- **改动面**（全部用 `git mv` 改目录保历史，`sed`/编辑器换文本，禁止顺手改逻辑）：
  1. 六个 pyproject 的 `name`：kabao-core→butler-core（packages/core）、kabao-engine
     （packages/engine）、kabao-connectors（packages/connectors）、kabao-server
     （apps/server）、kabao-cli（apps/cli）、kabao-mcp（apps/mcp）；description 中
     「Kabao」→「Butler」（如 connectors 的「Kabao 连接器家族」）。
  2. 包间依赖与 `[tool.uv.sources]`：engine/connectors/server/cli 的 pyproject 里
     `kabao-core` 等依赖行全换 butler-*；根 `pyproject.toml`：name→butler-workspace、
     dependencies ×6、`[tool.uv.sources]` ×6（workspace members/testpaths 不动）。
  3. src 内层目录：`packages/core/src/kabao_core`→`butler_core`、
     `packages/engine/src/kabao_engine`→`butler_engine`、
     `packages/connectors/src/kabao_connectors`→`butler_connectors`、
     `apps/mcp/src/kabao_mcp`→`butler_mcp`（`src/server`、`src/cli` 本就无 kabao）。
  4. 全库 `*.py` 的 import 与 docstring 中 `kabao_core/kabao_engine/kabao_connectors/
     kabao_mcp` → `butler_*`（`grep -rl "kabao_" --include="*.py" packages apps` 定位，
     含 tests；**KABAO_ 大写 env 与 kabao.db 本任务不碰**——批4 处理）。
  5. `apps/mcp/pyproject.toml` 的脚本目标必须随目录换：`kabao-mcp =
     "butler_mcp.main:main"`（**命令名 kabao-mcp 保留到批4**）；`apps/cli` 的
     `kabao = "cli.main:app"` 本任务零改动（模块名 cli 未变）。
  6. `scripts/verify_project.py` **零改动**（包名从 src 目录动态推断，无 kabao 硬编码）。
  7. 清缓存 + 重锁：`find . -name __pycache__ -type d -prune -exec rm -rf {} +`；
     `eval "$(fnm env --shell zsh)" && uv sync`（重生成 uv.lock，diff 应只剩包名）。
- **验收**：pytest 全量 **459 passed / 10 skipped**；九项门禁 PASS；
  `grep -rn "kabao_core\|kabao_engine\|kabao_connectors\|kabao_mcp" packages apps --include="*.py"`
  零匹配；uv.lock 中无 kabao- 包名。
- **提交**：`refactor:[0]: Python 六包发行名与导入名 Butler 化`
- **依赖**：T1。

---

### T3 · 批3 npm 包 + 前端文案换词（页面结构不动）

- **改动面**：
  1. `packages/sdk/package.json`：name `@butler/sdk`；description 改「Butler（智能助手
     管家）server OpenAPI contract types — single source for web DTO derivation」；
     repository url `ai-kabao`→`ai-butler`（先写目标值）。
  2. `apps/web/package.json`：依赖 `@butler/sdk: "workspace:*"`。
  3. 根 `package.json`：name `butler-frontend`；gen:sdk filter 改 `--filter @butler/sdk`。
  4. `apps/desktop/package.json`：name `butler-desktop`；`productName: "Butler"`；
     `appId: "com.butler.app"`（main.js 零 kabao 引用，不动）。
  5. **存储键迁移腿** `apps/web/src/composables/useSettings.ts`：`loadSettings()` 先读
     `butler.settings.v1`；缺失则读 `kabao.settings.v1`，命中即解析并
     `localStorage.setItem("butler.settings.v1", …)` 写入新键（**旧键保留不删**）；
     `updateSettings` 写新键；头部注释同步（TDZ 陷阱注释随迁）；`THEME_NAMES`
     内部值零改动。
  6. **UI 文案换词（非页名级）**：`SideNav.vue` 品牌区第一行「Butler」（brand-latin
     span 内收或删除）、第二行 brand-line「AI 智能助手管家」；`SettingsPage.vue`
     主题 option `paper` 显示名「纸墨（浅）」（dark/warm 不变）、关于节产品行
     「AI 智能助手管家（Butler）」；`index.html` `<title>AI 智能助手管家</title>`；
     `tokens.css`/`ui.css`/组件注释里「卡纸与墨」措辞→「纸墨」（**只动注释，token
     值与选择器零变化**）。
  7. 重锁：`eval "$(fnm env --shell zsh)" && pnpm install`（重生成 pnpm-lock.yaml；
     CI 用 --frozen-lockfile，锁文件必须随提交更新）。
- **验收**：vue-tsc 绿；九项门禁 PASS（契约指纹零变化——@butler/sdk 换名不影响
  openapi 指纹）；`grep -rn "Kabao\|卡包\|kabao" apps/web/src apps/web/index.html
  packages/sdk/package.json apps/desktop/package.json package.json` 白名单 =
  useSettings.ts 的 kabao.settings.v1 兼容行，其余零匹配；pnpm-lock.yaml 无 @kabao。
- **提交**：`refactor:[0]: npm 包名与前端存储键 Butler 化`
- **依赖**：T2。

---

### T4 · 批4 底座（env / db 迁移腿 / CLI 命令 / server 标题）

- **改动面**：
  1. **env 前缀**（大写，全库）：`KABAO_DB`→`BUTLER_DB`（engine bridge docstring、
     apps/server/src/server/main.py、apps/cli/src/cli/main.py）；
     `KABAO_SCHEDULE`→`BUTLER_SCHEDULE`（server main ×2 + server tests）；
     `KABAO_SERVER_URL`→`BUTLER_SERVER_URL`（apps/mcp main + mcp tests）；
     connectors `workbuddy_cn/session.py` 的剥离前缀元组与注释 `KABAO_`→`BUTLER_`
     + connectors tests。
  2. **db 迁移腿** `packages/engine/src/butler_engine/bridge.py` `default_db_path()`：
     三平台目录基名 `kabao`→`butler`；`DEFAULT_DB = "butler.db"`；target =
     root/`butler.db`；旧源链**四条按优先级**：① `root.parent/"kabao"/"kabao.db"`
     （上一代品牌目录）② `Path.cwd()/"kabao.db"` ③ `root.parent/"ai-marina"/
     "marina.db"`（R1 前身）④ `Path.cwd()/"marina.db"`；命中即连同 `-wal/-shm`
     整体搬移、旧文件保留不删、`logger.info` 审计、命中后 break；迁移幂等
     （butler.db 已存在即跳过）；**显式 BUTLER_DB 时不做任何迁移**。docstring 同步。
  3. **内部 job 名**（bridge 内常量，无测试断言）：SCAN_JOB_NAME/CHECKIN_JOB_NAME/
     USAGE_JOB_NAME 的 `kabao-*`→`butler-*`。
  4. **CLI 命令**：`apps/cli/pyproject.toml` `kabao = "cli.main:app"`→
     `butler = "cli.main:app"`；`apps/mcp/pyproject.toml` `kabao-mcp`→`butler-mcp`
     （目标路径批2 已是 butler_mcp.main）。
  5. **server 标题**：`apps/server/src/server/main.py` `FastAPI(title="kabao", …)`→
     `title="butler"`（版本号 0.1.0 不动）；SettingsPage 数据位置文案
     「kabao.db（平台标准数据根）」→「butler.db（平台标准数据根）」（display ==
     behavior）。
  6. **指纹刷新（§A-1 唯一许可）**：`eval "$(fnm env --shell zsh)" && pnpm gen:sdk`；
     然后 `git diff --stat -- packages/sdk/src/gen`——**`schema.d.ts` 必须零 diff、
     `openapi.sha256` 一行变化**（openapi.json 不入 git）。schema.d.ts 若出现 diff
     = 契约形状被动了 = 立即停手上报。
  7. **MCP server 名**：`apps/mcp/src/butler_mcp/main.py` `MCPServer("kabao", …)`→
     `("butler", …)`；instructions 文案去「卡包里的卡」措辞，改「先查额度/查用量认识
     各家账户（provider = 连接器 id），再触发领取」。
  8. **迁移测试改写** `packages/engine/tests/test_data_root.py`：按新链重写断言——
     首次迁移（含 wal/shm 随迁、旧文件保留）/ 幂等跳过 / 显式 BUTLER_DB 不迁移 /
     kabao 旧库源优先于 marina 源（结构沿用现测试，机制不变）。
- **验收**：pytest 全量绿（条数 ±迁移测试结构变动可接受，0 failed）；九项门禁 PASS
  （含契约新鲜度——指纹已刷新）；
  `grep -rn "KABAO_" packages apps --include="*.py"` 零匹配；
  `grep -rn "kabao" packages/engine/src/butler_engine/bridge.py` 仅剩
  default_db_path 的旧源检测行（迁移兼容白名单）；
  `uv run butler --help` 与 `uv run butler-mcp --help`（起后即退）不报命令不存在。
- **提交**：`refactor:[0]: 底座换名与数据库自动迁移腿`
- **依赖**：T3。

---

### T5 · 批5 收尾（全库文档清扫 + 远端切换 + 记账）

- **要求**：
  1. **文档措辞清扫**（按 §B 词表 v2 换词，不改事实内容）：`README.md`、`AGENTS.md`、
     `docs/README.md`、`docs/specs/architecture/A1-01`、`A1-02`、
     `docs/specs/domain/A2-02`、`A2-03`、`docs/specs/cross-cutting/A4-01`、
     `docs/conventions/01`、`02`、`04`、`08`、`docs/conventions/规范索引.md`、
     `docs/guides/01-环境与命令.md`；`packages/connectors/*/PROTOCOL.md` 措辞清扫
     （**业务码字典一个字符不动**）。`docs/conventions/00` 的 `{repo-remote}` 行
     更新为 `ai-butler`。
  2. **【用户手工步，先做】Gitee 网页改名**：`hiclaw_520/ai-kabao`→`ai-butler`
     （执行模型无法代做——向用户提出，等用户确认完成后才继续第 3 步；用户不在
     则记 STATUS 挂账并跳过第 3 步）。
  3. **切远端**：`git remote set-url origin
     git@gitee_hiclaw520_126:hiclaw_520/ai-butler.git`（SSH 别名不变）并 push。
  4. **STATUS**：`docs/STATUS.md` 文首加一行「2026-11-14 起品牌更名 Butler，
     历史段落中的 Kabao/卡包 均指同一产品」；「一句话现状」改写为 Butler 重定位
     完成；里程碑表加一行「**Butler 重定位阶段一（全深度改名）** | 六包/npm/env/db/
     CLI/存储键/主题显示名全换 + kabao.db→butler.db 迁移腿 + 文档收编
     ADR-011/A1-03 v2/conventions 00·03 | **✅ 完成（2026-11-14）**」。
- **验收（阶段一 DoD）**：九项门禁 PASS；
  `grep -ril kabao --exclude-dir=.git --exclude-dir=node_modules
  --exclude-dir=__pycache__ --exclude-dir=.venv --exclude-dir=dist .`
  命中文件全部落在白名单：①`packages/engine/src/butler_engine/bridge.py`（迁移兼容
  检测行）②`apps/web/src/composables/useSettings.ts`（旧键读取行）③`docs/adr/`
  （ADR-001..010 + 模板）④`docs/specs/legacy/A0-01` ⑤`docs/STATUS.md`（历史段）⑥
  `docs/superpowers/`（历史任务书/设计书）⑦指向历史文档**文件名**的路径引用行
  （如 ADR-007-品牌更名Kabao与白话词表.md）；`git remote -v` 显示 ai-butler；
  push 成功。
- **提交**：`docs:[0]: 全库措辞清扫与远端切换收尾`
- **依赖**：T4。

---

### T6 · 阶段二 · DashboardPage（新页组件，独立可编译）

- **文件**：新建 `apps/web/src/pages/DashboardPage.vue`（**此时还无人挂载**）。
- **要求**（三块全复用现有件，**零新端点**，聚合走前端 computed）：
  - props：`accounts: AccountItem[]`、`apps: AppItem[]`、`runs: RunItem[]`、
    `pending: RunItem[]`、`radarRows: RadarRow[]`、`todayDone`、`claimable:
    Set<string>`、`busyTarget`、`msg`、`loading`、`loadError`（对齐壳现有
    composable 出参数）。
  - emits：`claim: [target]`、`health: [target]`、`navigate: [page: PageName]`
    （**透传给 TodoRail**，本组件不自用 navigate 字面量）。
  1. **今日一句话结论**（沿用现 AccountsPage headline 谓词改词 账号→账户）：
     loading「正在打开仪表盘」/ loadError「暂时够不到服务」+ 副行「确认 server 已启动
     后点刷新」/ pending>0「{n} 项待处理」/ accounts 空「还没有接入任何应用」/
     有非正常「{总数} 个账户，{n} 个需要留意」/ 全正常「{总数} 个账户状态正常」。
  2. **常驻待办栏三节整体迁入**：TodoRail 组件原样复用（props 透传），含证据折叠
     与能力驱动按钮。
  3. **速览行**（只数数、signal 驱动、端零映射，`.rows/.row` 行+发丝线四行）：
     账户健康分布（ok/需留意/异常 计数，`.tag` 五分类）/ 今日自动动作（本地自然日
     runs：X 完成 · Y 未完成）/ 流量速览（radarRows 非空→「最近采集于 {loadedAt
     或最近包时间}，最低额度 {account_id}」；空→「尚未采集」）/ 最近一条日志
     （runs[0] 的 fmtTime + kind；空→「—」）。
  - 样式只用现有件（page-title/rows/row/tag/rail）；禁 stamp、禁新 token、
    禁写死颜色。
- **验收**：`pnpm --dir apps/web exec vue-tsc --noEmit` 绿（独立组件，暂无人引用也
  须零报错）；无 Status/HealthLevel 字面量；≤600 行；`git diff --stat -- apps/web/src/api.ts`
  为空。
- **依赖**：T5（阶段一已收尾；词表 v2 已定稿）。

---

### T7 · 阶段二 · AppsPage（应用注册表，独立可编译）

- **文件**：新建 `apps/web/src/pages/AppsPage.vue`。
- **要求**（数据全现成——AppItem 已带 capabilities/schedule_times/account_id）：
  - props：`apps`、`accounts`、`busyTarget`、`msg`、`loading`、`loadError`。
  - emits：`import: [target: string]`、`importAll: []`、`jump: [accountId: string]`
    （**此时用 string，T8 收紧**）。
  - 页头：标题「应用」+ 副题「本机接入的各家 AI 助手与其能力、时间表。」+
    页头右侧「一键导入（n）」——importableCount = apps 中无 account_id 的数量，
    禁用条件照抄现 AccountsPage 同名按钮。
  - 表 6 列（`.matrix` 件）：应用（AppBadge）| 能力（capabilities 顿号连接，
    provision.run→领取 / health.check→体检 / usage 类→用量）| 时间表
    （schedule_times 逐个/顿号，空→「—」）| 账户数（account_id→1；无→「未导入」
    虚线呈现）| 状态汇总（该应用账户 signal 计数小徽，五分类只读）| 动作
    （未导入行→「导入」按钮）。
  - **未接入应用 = 虚线邀请行**「＋ 导入 {应用名}」（emit('import', app.id)，
    从账户页迁来；沿用现 AccountsPage 邀请行的视觉语义）。
  - 点行展开（渐进披露）：能力清单 / 班次明细 / 该应用账户行 +「去账户」跳转
    （emit('jump', account_id)）。
  - 空态（无 apps）：quietline「还没有应用——一键导入把本机客户端接进来。」
- **验收**：vue-tsc 绿；≤600 行；api.ts 零 diff；无 Status 字面量。
- **依赖**：T6。

---

### T8 · 阶段二 · 壳切换批（编译一致性批——四件同批验收）

- **文件**：`apps/web/src/types.ts`、`apps/web/src/composables/useHashRoute.ts`、
  `apps/web/src/components/SideNav.vue`、`apps/web/src/components/TodoRail.vue`、
  `apps/web/src/App.vue`。
- **要求**：
  1. **types.ts**：`PageName = "仪表盘" | "应用" | "账户" | "流量" | "日志" | "设置"`。
     其余零改动。
  2. **useHashRoute v2**：`hashByPage = { 仪表盘:"dashboard", 应用:"apps",
     账户:"accounts", 流量:"traffic", 日志:"logs", 设置:"settings" }`（注意：账户
     沿用 "accounts" 原链、设置沿用 "settings"——**原链有效无需重定向**）；
     `legacyHashByPage = { home:仪表盘, alerts:仪表盘, wallet:账户, card:账户,
     radar:流量, usage:流量, log:日志 }`（7 条，命中即 replaceState 静默重写，
     机制不变）；`resolveActive` 默认页→「仪表盘」（无 hash → `#/dashboard`）。
  3. **SideNav**：`overviewItems` 六项平铺；**提醒角标挂「仪表盘」项**（alertCount
     计算逻辑零变化；账户项不挂）；品牌区改**单行**「AI 智能助手管家」（删
     brand-line 品类句行）；≤900px 顶条同样显示主名（原「窄屏隐藏品类句」规则删除）。
  4. **TodoRail**：「去账号」→「去账户」且 emit('navigate','账户')；组件内文案按
     词表 v2 扫一遍（账号→账户等）。
  5. **App.vue**：挂载六页——仪表盘→DashboardPage、应用→AppsPage、账户→
     AccountsPage（现样）、流量→UsagePage（现样，T10 再换文件名）、日志→LogPage、
     设置→SettingsPage；else 分支→DashboardPage；props 传递：DashboardPage 接
     data/actions 全量（todayDone/claimable/radarRows/runs/pending 等从 composables
     解构），AppsPage 接 import/importAll 动作；AccountsPage 现有绑定本任务不动。
  6. T7 的 `jump` emit 类型收紧为 PageName。
- **验收（缺一 retry）**：vue-tsc 绿；九项门禁 PASS；
  `grep -n "账号\|用量\|记录" apps/web/src/types.ts apps/web/src/composables/useHashRoute.ts apps/web/src/components/SideNav.vue`
  零匹配；`git diff --stat` 不含 pages/ 下既有文件。
- **提交**：`feat:[0]: 仪表盘与应用注册表新页 + 六页 IA 壳切换`（T6+T7+T8 一个提交）
- **依赖**：T6、T7（App 要挂新页）。

---

### T9 · 阶段二 · AccountsPage 瘦身 + 拆 MatrixTable（销挂账 0①）

- **文件**：`apps/web/src/pages/AccountsPage.vue`（496 行）+ 新建
  `apps/web/src/components/MatrixTable.vue` + `apps/web/src/App.vue`（props 收窄）。
- **要求**：
  1. **移除**（语义各有归处，不删除能力本身）：TodoRail 挂载（→仪表盘 T6）、
     应用空槽邀请行（→应用页 T7）、一键导入按钮与 `import`/`importAll` emits
     （→应用页 T7）、headline 谓词（→仪表盘 T6）；随之 props 收窄：去掉
     `pending`/`todayDone`/`claimable`（App.vue 同步）。
  2. **保留**：9 列矩阵（选择/应用/账户/状态/今日动作/额度/凭据/最近操作/动作）、
     应用与状态筛选、勾选批量条、行展开详情、**一键领取（n）**（领取语义归账户域）、
     「体检」按钮。
  3. **拆 MatrixTable.vue**：表格段（表头/行渲染/展开详情面板）整体迁出为子组件，
     props/events 对齐现模板绑定名（**不顺手改语义**）；AccountsPage 保留页头/筛选/
     批量条/空态。目标 AccountsPage ≤400 行（软警戒），600 硬上限由门禁兜底。
  4. **词表 v2 换词**：页头标题「账号」→「账户」、页内文案账号→账户（列名/筛选/
     批量条/空态），「卡」系词清零。
- **验收**：vue-tsc 绿；`wc -l apps/web/src/pages/AccountsPage.vue` ≤ 400（力争）；
  九项门禁 PASS；`grep -rn "账号\|一键导入" apps/web/src/pages/AccountsPage.vue
  apps/web/src/components/MatrixTable.vue` 零匹配。
- **提交**：`refactor:[0]: 账户页瘦身并拆矩阵表组件`
- **依赖**：T8。

---

### T10 · 阶段二 · 流量/日志/设置换名换词

- **文件**：`apps/web/src/pages/UsagePage.vue`（git mv → `TrafficPage.vue`）、
  `apps/web/src/pages/LogPage.vue`、`apps/web/src/pages/SettingsPage.vue`、
  `apps/web/src/App.vue`（import 同步）。
- **要求**：
  1. **流量页**：文件名 UsagePage→TrafficPage（git mv 保历史）；页头「用量」→
     「流量」；副题去「额度雷达」语系→「各家账户余额、额度流水与耗尽预测。」；
     空态句账号→账户；**「立即采集」按钮与采集文案保留**；数据结构/forecast/
     progress 全零变化。
  2. **日志页**：页头「记录」→「日志」（LogPage 文件名不动，Log=日志）；
     副题「操作台账——每次动作都留痕。」保留；表结构/证据折叠零变化。
  3. **设置页**：查漏——通用/提醒/关于三节按词表 v2 扫尾（主题名与数据位置
     已在批3/批4 完成）。
  4. App.vue import 与分支名同步（流量→TrafficPage）。
- **验收**：vue-tsc 绿；九项门禁 PASS；
  `grep -rn "额度雷达\|账号" apps/web/src/pages apps/web/src/components` 零匹配；
  `grep -rn "用量" apps/web/src/pages/TrafficPage.vue` 仅剩域内数据语境
  （流水/已用量类）。
- **提交**：`refactor:[0]: 流量日志设置页按词表换名换词`
- **依赖**：T9。

---

### T11 · 阶段二 · 文档收编 + 终验 + 走查

- **要求**：
  1. **新建 `docs/adr/ADR-012-六页信息架构.md`**：裁决 = 四页→六页（仪表盘/应用/
     账户/流量/日志/设置，页名按词表 v2）；仪表盘为默认首页，待办栏三节归仪表盘；
     导入语义归应用页、领取语义归账户页；品牌区单行、品类句概念退役（引 ADR-011）；
     影响面 = 纯 apps/web，契约零改动；一人多账号展示面 = 应用页「账户数」列
     （ADR-010 占位，实现不做）。
  2. **重写 `docs/specs/application/A3-01-信息架构与核心页面.md`**（v2）：§1 侧栏
     （六项 + 单行品牌 + 角标在仪表盘）；§2 六页规格（仪表盘三块/应用注册表六列/
     账户矩阵瘦身版/流量/日志/设置）；§3 组件结构（DashboardPage/AppsPage/
     MatrixTable/TodoRail 归属 + App.vue 数据流 + 路由重定向表 v2）；§4 渲染纪律
     （原条目保留）。
  3. **STATUS**：现状段 + 里程碑表加「**Butler 重定位阶段二（六页 IA）** | … |
     **✅ 完成（2026-11-14）**」；挂账 0①（AccountsPage 496 行）销账。
  4. **终验清单（全过才算完成）**：
     - 九项门禁 PASS；`git diff --stat` 确认阶段二对 server/engine/connectors/sdk/
       mcp/desktop/cli 源码**零 diff**；`openapi.sha256` 与阶段一终态一致（零 diff）。
     - 浏览器走查（server:8000 + `pnpm dev:web`）：**双断点（>900px / ≤900px）×
       三主题（纸墨/墨夜/暖纸）× 六页**全过；旧 hash 7 条直链
       （#/home #/alerts #/wallet #/card #/radar #/usage #/log）重定向正确；
       一键导入（n）/一键领取（n）/角标计数与 server 实数吻合；仪表盘速览四行
       与数据一致；真实动作按钮（导入/领取/体检/采集）**留用户自点**，走查只验证
       状态与计数；走查后还原现场（主 tab 停原 hash、theme=system、弹窗关闭）。
  5. 提交：`docs:[0]: ADR-012 与信息架构文档收编`。
- **依赖**：T10。

---

## 阶段一提交序列（汇总）

```
docs:[0]: ADR-011 更名裁决与词表 v2 入册           ← T1
refactor:[0]: Python 六包发行名与导入名 Butler 化   ← T2
refactor:[0]: npm 包名与前端存储键 Butler 化        ← T3
refactor:[0]: 底座换名与数据库自动迁移腿            ← T4
docs:[0]: 全库措辞清扫与远端切换收尾               ← T5
```

## 阶段二提交序列（汇总）

```
feat:[0]: 仪表盘与应用注册表新页 + 六页 IA 壳切换    ← T6+T7+T8
refactor:[0]: 账户页瘦身并拆矩阵表组件              ← T9
refactor:[0]: 流量日志设置页按词表换名换词           ← T10
docs:[0]: ADR-012 与信息架构文档收编               ← T11
```

## §E 明确不做（执行模型禁止自作主张）

- **不做新功能**（用户「还有其他的功能等等」）——新 IA 站稳后下一阶段单独立项。
- **一人多账号**仍为 ADR-010 占位（应用页「账户数」列只是展示面，不实现）。
- **契约零改动**：不加端点、不改形状；gen:sdk 只在批4 跑一次（标题元数据）；
  阶段二 openapi.sha256 零 diff。
- **视觉重做不做**：三主题机制/token 值/组件件零变化，只换显示名与文案。
- git 历史不改写；ADR-001..010 与 A0-01、docs/superpowers/ 原词保留。
- 协议七字面量、连接器业务码字典、领域实体名（Account/Run/Event）、signal 五分类
  字面量不改名；连接器原始返回文本不算 UI 文案，不扫。
- apps/uniapp 零接触；不删改 pytest 结构（批4 迁移测试改写除外）；不改 CI workflow
  与构建配置；不引 vue-router/pinia/任何新依赖；需要图标一律字符（✓ ✗ ＋ ✕）。

## §F 风险提示（给执行模型的避坑）

1. **批4 指纹例外是全任务书唯一一次 gen:sdk**：FastAPI title 属 openapi 文档元数据，
   改后指纹必变，verify 第 6 项会 FAIL——跑 `pnpm gen:sdk` 刷新即可；铁律 =
   `schema.d.ts` 必须 diff 为空（现状含 0 个 kabao 引用，title 不入类型），
   若非空说明有形状变化，停下上报。
2. **批2 后必须清 `__pycache__`**：旧 kabao 字节码残影会让 import 静默命中旧包
   （空包检测/测试假绿的真实事故先例），`find . -name __pycache__ -type d -prune
   -exec rm -rf {} +` 后再跑测试。
3. **锁文件重生成时点**：批2 `uv sync`（uv.lock 包名）、批3 `pnpm install`
   （pnpm-lock @butler/sdk）——CI 用 `--frozen-lockfile`，锁文件必须随当批提交。
4. **THEME_NAMES 内部值零改动**：paper/dark/warm 是 localStorage 存档兼容面，只换
   SettingsPage option 显示名与注释；useSettings 的 TDZ 陷阱注释随代码走。
5. **存储键迁移腿必须幂等温和**：读新键缺失→读旧键→写新键；**旧键永不删除**
   （双端/回滚安全）；解析失败静默回默认（现 try/catch 行为保留）。
6. **db 迁移腿四源链顺序不能乱**：kabao 目录 → CWD kabao.db → marina 目录 →
   CWD marina.db；显式 BUTLER_DB 一律不迁移；wal/shm 整体搬；旧文件保留 +
   logger 审计；测试四条断言（首迁/幂等/显式 env/kabao 优先）钉死。
7. **词表执行口径**：页名级必须换、域内数据语境可留（「用量流水」「已用量」）；
   拿不准的词先查 conventions/03 v3，没有的→上报，别发明。
8. **T8 是编译一致性批**：types/useHashRoute/SideNav/TodoRail/App 必须同批验收，
   中间态 vue-tsc 必红（PageName 字面量联动，矩阵改版 T8 同款教训）。
9. **T9 拆 MatrixTable 保契约**：props/events 对齐现模板绑定名，不借机改语义；
   AccountsPage 的今日动作列日期比较用本地自然日（现实现原样保留）。
10. **走查探针**：Vue 更新是微任务异步——dispatchEvent 后须 `await` 再断言；
    判列隐藏必须看 computed display（display:none 元素 innerText 回退
    textContent）；Code Mode `execute` 禁 setTimeout（sleep 只能放页面脚本内）。
11. **远端切换时序**：Gitee 网页改名（用户手工）→ `git remote set-url` → push；
    SSH 别名 `gitee_hiclaw520_126` 不变；Gitee 旧 URL 自动重定向，风险低。
    用户未完成改名前，T5 第 3 步挂账跳过，其余照常。
12. **验收 grep 白名单**（阶段一 DoD 的允许残留）：bridge.py 迁移兼容行 /
    useSettings.ts 旧键行 / docs/adr（除 ADR-011）/ A0-01 / STATUS 历史段 /
    docs/superpowers/ / 历史文档文件名路径引用。白名单外出现 kabao 即未收尾。
13. **挂账销账**：0① AccountsPage 496 行 → T9 销；0③ ADR-010 占位 → 本单不动。
14. **后台服务**：走查起 `uv run uvicorn server.main:app --host 127.0.0.1 --port 8000`
    与 `pnpm dev:web`（先 `eval "$(fnm env --shell zsh)"`）；走查完还原现场。
