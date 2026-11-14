# Butler 按业务域重写实施计划（P1-P6）

> **状态：P0-P6 全部完成（2026-11-14）**——505 tests + 门禁九项全绿；
> 完成记录见 `docs/STATUS.md` 置顶收官行。

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 把 `packages/core` + `packages/engine` 从零重写为五业务域 + shared 的
`butler_core` / `butler_engine`，并入 ADR-010 多账号模型，P6 收口切流。

**Architecture:** 新旧并行——P1-P5 新建 `butler_core`/`butler_engine` 并自带测试，
旧 `kabao_core`/`kabao_engine` 原样保留供 server 继续使用；P6 一次性切流
（apps 改 import、契约再生成、删旧包）。每阶段验收 = 新增测试全绿 + 门禁九项全绿。

**Tech Stack:** Python 3 + uv workspace + pytest；契约 openapi-typescript（P6）；
规范依据：A1-05（总设计）、A2-01（总纲）、A2-11..A2-15（域分册）、
conventions/02（八条红线）、conventions/04（一域一模块 600 行）、conventions/08（提交格式）。

**执行纪律（每个 Task 都适用）：**

1. TDD：先写失败测试 → 跑确认失败 → 最小实现 → 跑绿 → 提交
2. 提交格式（conventions/08，钩子强制）：`<type>:[0]: <动词开头中文主题>`，
   单行 ≤100 字符、不加句号
3. 每次 Task 收尾跑门禁：`python scripts/verify_project.py --project . --test` 九项全绿
4. 新文件单文件 ≤600 行（硬上限）/ 400 行软警戒；一业务域一模块
5. 禁止 import 旧 `kabao_core`（新代码独立自洽）；禁止从 auto-signin-kit 搬代码
6. 核心规则出处：A2-01/A2-11..15 是实体与不变量的唯一事实源，本文只给落位与步骤

---

## 阶段 P1 · butler_core 骨架（shared + accounts）

### Task 1: 包骨架落位

**Files:**
- Create: `packages/core/src/butler_core/__init__.py`（空 docstring）
- Create: `packages/core/src/butler_core/shared/__init__.py`
- Create: `packages/core/src/butler_core/accounts/__init__.py`
- Modify: `packages/core/pyproject.toml`（确认 hatch/uv 打包 `packages = ["src/kabao_core", "src/butler_core"]` 或等价配置；**不改发行包名**——发行名 `butler-core` 的 pyproject 改名留到 Task 20，避免中途打断 server 依赖图）

**Step 1:** 建目录与空 `__init__.py`（含一行模块 docstring，注明域图出处 A1-05）。
**Step 2:** `uv run python -c "import butler_core"` 确认可导入。
**Step 3:** 门禁九项绿。
**Step 4:** `git add -A && git commit -m "feat:[0]: 建立 butler_core 按业务域分包骨架"`

### Task 2: shared/results.py（结果词汇单源）

**Files:**
- Create: `packages/core/src/butler_core/shared/results.py`
- Test: `packages/core/tests/butler_core/test_shared_results.py`

**Step 1: 失败测试**（语义与旧 `kabao_core/domain/results.py` 对齐，oracle 零损耗）：

```python
def test_seven_literals_exact(): ...
# 断言 {s.value for s in Status} == {"CLAIMED","ALREADY","NO_AUTH","EXPIRED","FAILED","PENDING","SKIPPED"}

def test_result_kind_predicates(): ...
# CLAIMED/ALREADY → is_pass；PENDING/EXPIRED/NO_AUTH → is_attention；FAILED → is_fail

def test_from_engine_translation(): ...
# 旧系统方言文本 → Status；未知文本 → 显式错误（不静默映射，红线 5）

def test_repair_hint_carried(): ...
```

**Step 2:** 跑测试确认 FAIL（ModuleNotFoundError）。
**Step 3:** 实现：从旧 `packages/core/src/kabao_core/domain/results.py` 移植
Status/ResultKind/`from_engine`，**删除 legacy 自映射分支**（A1-05 §4——
方言翻译表保留为纯数据字典，由测试钉死全部条目）。
**Step 4:** 测试 PASS；门禁绿。
**Step 5:** `git commit -m "feat:[0]: 结果词汇七字面量落位 shared 结果单源"`

### Task 3: shared/events.py（事件六型）+ shared/errors.py + shared/ids.py

**Files:**
- Create: `packages/core/src/butler_core/shared/events.py` / `errors.py` / `ids.py`
- Test: `packages/core/tests/butler_core/test_shared_events.py`

**Step 1: 失败测试**：六型枚举值与旧 `domain/event.py` 一致
（RUN_FINISHED / CREDENTIAL_EXPIRING / CREDENTIAL_EXPIRED / QUOTA_LOW /
PROTOCOL_CHANGED / ACCOUNT_HEALTH_CHANGED）；severity ∈ {silent, badge, push}；
事件构造 schema `{type, ts, account_id?, severity, payload}` 校验。
**Step 2:** FAIL 确认。**Step 3:** 从旧 `event.py`/`errors.py` 移植实现；
`ids.py` 放 account_id / run_id 生成（纯函数，可注入时钟/随机源）。
**Step 4:** PASS；门禁绿。**Step 5:** `git commit -m "feat:[0]: 事件六型与错误 ids 落位 shared"`

### Task 4: accounts/domain.py（多账号聚合根）

**Files:**
- Create: `packages/core/src/butler_core/accounts/domain.py`
- Test: `packages/core/tests/butler_core/test_accounts_domain.py`

**Step 1: 失败测试**（A2-11 §2 不变量逐条）：

```python
def test_account_identity_default_key(): ...
# Account(provider_id="trae_cn") → account_key == "main"

def test_same_provider_unique_account_key(): ...
# 同 (provider_id, account_key) 二次建账 → AccountAlreadyExists 显式拒绝

def test_credential_must_belong_to_account(): ...
# Credential 无 account 归属构造 → 拒绝（不变量 2 形状校验）

def test_provider_not_in_ui_vocabulary(): ...  # 静态断言 domain 无 UI 词
```

**Step 2:** FAIL 确认。**Step 3:** 实现：从旧 `domain/account.py` + `vault.py`
移植实体（Credential/Entitlement/Session 形状不变），Account 增加
`identity = (provider_id, account_key)` 集合语义与冲突校验。
**Step 4:** PASS；门禁绿。**Step 5:** `git commit -m "feat:[0]: 账户域聚合根多账号集合化"`

### Task 5: accounts/ports.py + register_account 用例

**Files:**
- Create: `packages/core/src/butler_core/accounts/ports.py`
  （`VaultPort` / `SessionSourcePort` / `AccountRepoPort`，签名移植自旧
  `application/ports.py` 对应段落，**只保留本域端口**）
- Create: `packages/core/src/butler_core/accounts/usecases/__init__.py`
- Create: `packages/core/src/butler_core/accounts/usecases/register_account.py`
- Test: `packages/core/tests/butler_core/test_register_account.py`

**Step 1: 失败测试**：注册成功落库；`(provider, account_key)` 冲突显式拒绝
（不静默改号）；经 AccountRepoPort 假实现注入。
**Step 2:** FAIL。**Step 3:** 实现（旧 usecases/register_account.py 逻辑移植 +
新冲突语义）。**Step 4:** PASS；门禁绿。
**Step 5:** `git commit -m "feat:[0]: 账户域端口随域走并落注册用例"`

---

## 阶段 P2 · execution + scheduling

### Task 6: execution/domain.py（Action/Run + 幂等键）

**Files:**
- Create: `packages/core/src/butler_core/execution/domain.py`
- Test: `packages/core/tests/butler_core/test_execution_domain.py`

**Step 1: 失败测试**：

```python
def test_idempotency_key_per_account(): ...
# key(kind, account_id, window) 同账号同窗口 → 相同；不同账号 → 不同（ADR-010 §4）

def test_run_budget_is_first_class(): ...
# Run 构造必填 budget；超预算判定函数返回如实语义

def test_kind_enum_closed(): ...
# kind 与 A2-01 §4 八值精确一致
```

**Step 2:** FAIL。**Step 3:** 移植旧 `action.py`/`run.py`/`results.py` 消费侧，
target 改为"应用 + 账号"编址。**Step 4:** PASS；门禁绿。
**Step 5:** `git commit -m "feat:[0]: 执行域动作与幂等键按账号粒度"`

### Task 7: execution/ports.py + execute_action 用例

**Files:**
- Create: `packages/core/src/butler_core/execution/ports.py`（`ProvisionPort` / `RunRepoPort`）
- Create: `packages/core/src/butler_core/execution/usecases/execute_action.py`
- Test: `packages/core/tests/butler_core/test_execute_action.py`

**Step 1: 失败测试**：①幂等命中回放不重打（同键二次调用 → ALREADY，执行器零调用）；
②`dry_run=True` 只报告不领取；③连接器申报不支持 dry_run → 用例层显式拒绝
（红线 5，绝不静默降级）；④超预算立即停止并如实上报。
**Step 2:** FAIL。**Step 3:** 移植旧 usecases/execute_action.py（210 行）逻辑，
幂等查询走 RunRepoPort。**Step 4:** PASS；门禁绿。
**Step 5:** `git commit -m "feat:[0]: 执行用例幂等回放与预算硬承诺"`

### Task 8: scheduling 域（Trigger/窗口/list_pending）

**Files:**
- Create: `packages/core/src/butler_core/scheduling/domain.py` + `ports.py`
  （`SchedulerPort` / `TriggerRepoPort`）+ `usecases/list_pending.py`
- Test: `packages/core/tests/butler_core/test_scheduling.py`

**Step 1: 失败测试**（A2-15 §2 不变量）：窗口判定只在 scheduling；
event/threshold 触发器消费 shared 事件发起 Action；待办去重
（同 (kind, account, 窗口) 只一条）。
**Step 2-4:** FAIL → 移植旧 `schedule.py` + `list_pending.py` → PASS。
**Step 5:** `git commit -m "feat:[0]: 调度域触发器窗口与待办队列落位"`

---

## 阶段 P3 · usage + health

### Task 9: usage 域

**Files:**
- Create: `packages/core/src/butler_core/usage/domain.py` + `ports.py`
  （`UsageCollectorPort` / `UsageRepoPort`）+ `usecases/collect_usage.py`
- Test: `packages/core/tests/butler_core/test_usage.py`

**Step 1: 失败测试**（A2-13 §2）：样本必带 source 否则拒绝入账；样本只增不改；
`is_quota_low` / `forecast_exhaustion` 谓词输出与旧 `usage.py`（204 行）对齐
（**移植后用旧实现的已知输入输出对做 oracle 测试**）；QUOTA_LOW 按账号隔离。
**Step 2-4:** FAIL → 移植 → PASS。**Step 5:**
`git commit -m "feat:[0]: 用量域三型语义谓词与采集用例落位"`

### Task 10: health 域

**Files:**
- Create: `packages/core/src/butler_core/health/domain.py` + `ports.py`
  （`HealthProbePort` / `HealthRepoPort`）+ `usecases/health_scan.py`
  （含 assess_account_health）
- Test: `packages/core/tests/butler_core/test_health.py`

**Step 1: 失败测试**（A2-14 §2）：分级是纯函数（同输入同输出）；预警窗常量
随域迁入（旧 `vault.py` 常量值不变，oracle 对齐）；到期 N 天 → 对应事件；
扫描失败如实上报不静默视为健康。
**Step 2-4:** FAIL → 移植旧 `health.py` + `health_scan.py` → PASS。**Step 5:**
`git commit -m "feat:[0]: 健康域分级风险规则与体检用例落位"`

### Task 11: bootstrap 装配根 + core 侧收尾

**Files:**
- Create: `packages/core/src/butler_core/bootstrap.py`
- Test: `packages/core/tests/butler_core/test_bootstrap.py`

**Step 1: 失败测试**：bootstrap 组装五域 + shared，端口注入点齐全；
零框架 import（verify AST 检查通过）；依赖恒等式抽查
（domain 不 import 其他域——用 ast 断言或测试内 importlib 校验）。
**Step 2-4:** FAIL → 实现 → PASS；门禁九项绿。
**Step 5:** `git commit -m "feat:[0]: butler_core 五域装配根收口"`

---

## 阶段 P4 · butler_engine

### Task 12: engine 骨架与 sqlite repos

**Files:**
- Create: `packages/engine/src/butler_engine/__init__.py`、`db/`（schema + WAL + 迁移版本表）、
  `accounts/` `events/` `usage/` `health/` `scheduling/` `vault/` `audit/` `notify/`、`bridge.py`
- Test: `packages/engine/tests/butler_engine/`

**Step 1: 失败测试**：各域 repo 实现对应 core ports（假→真替换测试，
复用 core 侧用例测试作集成测试）；schema 表含 `account_key` 列
（accounts 集合落地），`usage_samples` 按天分区独立表。
**Step 2-4:** FAIL → 移植旧 engine 九子模块实现（`kabao_engine/` 各 sqlite.py）
到新域图目录 → PASS。**Step 5:**
`git commit -m "feat:[0]: butler_engine 按域图落库适配器"`

### Task 13: 一次性数据迁移（历史包袱收口）

**Files:**
- Create: `packages/engine/src/butler_engine/db/migrate_from_kabao.py`
- Test: `packages/engine/tests/butler_engine/test_migrate_from_kabao.py`

**Step 1: 失败测试**（A1-05 §4 / A1-03 §7 机制逐条）：

```python
def test_first_migration_moves_db(): ...      # kabao.db → butler.db 新 schema，account_key="main"
def test_idempotent_skip_when_migrated(): ...
def test_explicit_butler_db_env_no_move(): ...
def test_marina_legacy_prefix_collected_once(): ...  # 旧 marina 凭据前缀读出后写入新键，旧文件保留
def test_audit_written(): ...
```

**Step 2:** FAIL。**Step 3:** 实现迁移脚本（一次性收口 marina 读穿 / legacy
方言 / ProvisionRequest 透传——新运行时代码零 legacy 分支）。
**Step 4:** PASS；门禁绿。**Step 5:**
`git commit -m "feat:[0]: 一次性数据迁移脚本收口历史包袱"`

### Task 14: bridge 装配与调度/事件/审计/通知

**Files:**
- Create: `packages/engine/src/butler_engine/bridge.py`
- Test: `packages/engine/tests/butler_engine/test_bridge.py`

**Step 1: 失败测试**：bridge 组装出站适配器注入 butler_core.bootstrap；
端口撞车显式拒绝（承袭旧 register_health_ports 语义）；每日 job 注册。
**Step 2-4:** FAIL → 移植旧 bridge.py（**去掉 `ai-marina/marina.db` 迁移腿**，
已由 Task 13 脚本收口）→ PASS。**Step 5:**
`git commit -m "feat:[0]: engine 桥装配五域端口与定时任务"`

---

## 阶段 P5 · connectors 适配

### Task 15: 横切运行时与六连接器搬家

**Files:**
- Modify: `packages/connectors/src/kabao_connectors/` → 目录改名
  `butler_connectors/`（registry.py / decl.py / dockio.py / browser.py / cdp.py /
  unlock.py / manifest.py / ssaes.py / native_helper.py 随迁，import 全部切
  butler_core/butler_engine——**此时旧 kabao_engine 尚在，注意 connectors
  切新包后旧 server 侧仍走 kabao_engine：本 Task 完成 P5+P6 前半，切换期间
  以 `uv run pytest` 全量绿为准绳；若 verify 结构项冲突，把"双包并存期"
  期望更新进 verify_project.py 并在提交信息注明**）
- 六连接器子包 `trae_cn/qoder_cn/doubao_cn/workbuddy_cn/chatgpt_web/claude_web`：
  **manifest.yaml / declarative/ / PROTOCOL.md 零改动**，仅 import 适配
- Test: 既有连接器测试全部保留并改 import

**Step 1:** 改 import + 目录改名。**Step 2:** 全量测试绿（358+ 用例）。
**Step 3:** 门禁绿。**Step 4:**
`git commit -m "refactor:[0]: 连接器包搬家适配 butler 域图"`

### Task 16: 多账号 dock/import 取证回填

**Files:**
- Modify: `packages/connectors/src/butler_connectors/*/PROTOCOL.md`（§新增多账号取证结论）
- Modify: `docs/specs/domain/A2-02-Connector-规范.md`（多账号枚举要求小节）

**Step 1:** 逐连接器确认 dock/import 的多 profile 语义（真机可得者实测，
不可得者如实标注"单账号，多开待取证"——红线 5 精神，不虚报）。
**Step 2:** PROTOCOL.md 回填 + A2-02 增补。**Step 3:** 门禁绿。**Step 4:**
`git commit -m "docs:[0]: 连接器多账号取证结论回填协议字典"`

---

## 阶段 P6 · 收口切流

### Task 17: apps 切流 + 旧包退役

**Files:**
- Modify: `apps/server`、`apps/cli`、`apps/mcp`、`apps/desktop` 全部 import
  kabao_core/kabao_engine → butler_core/butler_engine
- Modify: 各 `pyproject.toml` 发行包名 → `butler-core/-engine/-connectors/-server/-cli/-mcp`
- Delete: `packages/core/src/kabao_core/`、`packages/engine/src/kabao_engine/`
- Modify: `scripts/verify_project.py`（结构期望：butler_core 域图 + 依赖恒等式机检：
  domain.py 禁止 import 其他域）
- Modify: `docs/conventions/00-项目配置.md`（`{repo-remote}` 等——若 Gitee 已改名）

**Step 1:** 切 import → 全量测试绿 → 删旧包 → verify 期望更新 → 门禁九项绿。
**Step 2:** `git commit -m "refactor:[0]: 应用壳切流 butler 并退役旧包"`

### Task 18: 契约再生成（多账号）+ web 适配

**Files:**
- Modify: `apps/server/src/server/routes/accounts.py` / `runs.py`（端点带账号维度，
  裸应用 id = 首账号兼容层）
- Regen: `pnpm gen:sdk`（`packages/sdk` + openapi.sha256 同步，红线 4）
- Modify: `apps/web/src/api.ts` / `types.ts`（DTO 派生新契约）+ 受影响页面
- Modify: `apps/mcp`（三工具 target 语义适配，兼容裸应用 id）
- Test: server 契约测试 + web vue-tsc

**Step 1:** server 契约测试先行（新形状失败测试）→ 实现 → `gen:sdk` →
web 适配 → `vue-tsc` 绿 → 门禁绿。
**Step 2:** `git commit -m "feat:[0]: 契约再生成多账号维度并适配端"`

### Task 19: DoD 终验 + 文档收尾

**Step 1:** A1-05 §6 六条逐项验证（grep kabao 仅剩历史文档与迁移脚本字面量）。
**Step 2:** 更新 `docs/STATUS.md`（重写收官行 + 挂账销账 0③）。
**Step 3:** 门禁九项绿 + 全量测试绿。
**Step 4:** `git commit -m "docs:[0]: 按业务域重写收官状态卡更新"`

---

## 风险与回退

- **双包并存期**（P1-P5）：新旧互不依赖，旧链路测试始终绿 = 随时可停
- **P6 切流是唯一大爆炸点**：切流前 P1-P5 全部测试绿 + 迁移脚本钉死；切流
  单独成 commit，出问题 `git revert` 单点回退
- **多账号契约波及 MCP**：兼容层裸应用 id = 首账号，既有调用不断（ADR-010 §2）
