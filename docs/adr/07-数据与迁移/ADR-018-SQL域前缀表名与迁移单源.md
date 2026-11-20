---
name: butler-adr-018
description: SQL 命名、表结构与迁移真相源——术语 platform、代理键 + 审计三件、域前缀单数表名；migration-first：编号迁移文件 + db_migration 版本表，适配器零 DDL。TRIGGER when 改表/命名/迁移/data.sql 审查时
version: "1.2.0"
level: must
---

# ADR-018 · SQL 用域前缀单数表名，迁移只认编号文件

- **状态**：Accepted
- **日期**：2026-11-17（命名与结构五连裁决）；2026-11-20 迁移真相源切换 migration-first
- **决策者**：用户
- **影响域**：全库术语 / accounts / 全表 DDL / 生成视图
- **关联**：conventions/06-SQL规范（现行约束唯一入口）、A4-01 §5、ADR-001（六业务域）

## 背景

同一个"AI 产品身份"概念先后叫 Provider → App → Platform，accounts 表从 v1
（id TEXT 复合主键 + provider/display_name）一路演进；同时裸表名难辨域、执行域表缺审计三件。

迁移侧原来只有各域适配器 `_SCHEMA` DDL 常量 + `__init__` 里的**隐式自迁移**（探测列集 →
RENAME / 补列 / 重建表）。本机单库时代可用，开源后越来越难维护：

- **多人协作**：DDL 散在 7 个适配器里，改一次表要同时改常量 + 自迁移分支 + 测试断言，
  漏一处就漂移；协作 PR 无法 review「这次改了库的什么」。
- **DBA 审查**：没有一份可独立阅读的表结构真相（`data/sql` 生成视图是产物不是源）；
  迁移历史只存在于 git diff 里。
- **多服务共享一个库**：谁负责建表/升表没有单源；版本不可见不可查（曾预埋
  `PRAGMA user_version`，但 binary 整数既藏不住历史也无从审计）。

## 决策

### 1. 术语统一为 platform

全库退役 `provider`/`app`，统一为**平台**（连接器家族、列 `platform_code`、路由 `/platforms`、
`PlatformOut`）。保留不改：FastAPI/Typer 实例变量 `app`、AppBadge 组件名、
第三方 LLM provider 描述。

### 2. 全库 DDL 范式（收编 A4-01 §5）

每表代理键 `id INTEGER PRIMARY KEY AUTOINCREMENT` + `created_at/updated_at` 审计必备 +
禁用数据库关键字列名（`enabled` → `is_active`）。

### 3. 账户域列名 code 化

`account_key`→`account_code`、`display_name`→`account_name`；索引随列名。
显示名称列按业务命名：账户 = `account_name`、平台 = `platform_name`，
禁用 `display_name`/`name` 裸通用名。

### 4. 表名 = 域缩写前缀 + 单数实体

`acc_account` / `plat_platform` / `exe_claim` / `usage_*` / `health_state` / `vault_*` /
`audit_log`；索引名随表名。

### 5. 执行域表 = exe_claim（领取记录）

泛化 `exe_run` 改名，`run_id` 降为业务键（UNIQUE），补审计三件，幂等索引
`idx_exe_claim_idempotency`；core/契约的 Run 术语不变。

### 6. 真相源 = 编号迁移文件（migration-first）

`packages/engine/src/butler_engine/db/migrations/NNN_描述.sql`，随源码/包分发（迁移历史是
源码资产；`importlib.resources` 读取，wheel 可用）。文件格式：

```sql
-- 002_描述.sql · 域：一句话
-- 前置：001 ｜ 类型：ADD COLUMN（幂等由版本表保证，文件内不写 IF NOT EXISTS）
ALTER TABLE ... ;
```

- **改表 = 新增编号迁移文件**，❌ 禁止改历史迁移文件（checksum 记账校验，篡改 = 红线 5）。
- **forward-only**：❌ 禁止 down-migration；回滚 = 备份还原（与 journal_mode=OFF 无回滚日志的
  既有纪律一致）。
- 首份 `001_initial.sql` 即当前全量形状（11 表 9 索引）；适配器零 DDL、零自迁移。

### 7. 版本表 db_migration

`version INTEGER PK / name / checksum / applied_at`，由迁移器**自举**（先于迁移链建表，
本身不作迁移条目——06-SQL规范的唯一例外）。❌ 不用 `PRAGMA user_version`：多服务共享库时
版本必须可见可查。

### 8. 迁移器语义（`butler_engine/db/migrations/__init__.py`）

- `open_db(db_path)` = `conn.connect()` + `ensure_migrated()`——全调用点统一入口；
  各域适配器构造调用它，「构造即 schema 最新」语义不变。
- 幂等追跑：已应用版本按 checksum 校验文件未篡改；编号必须 001 起连续无空洞/重复；
  已应用版本文件缺失（安装回退）显式报错。
- **存量库 baseline**：迁移链首跑但 `acc_account` 已存在 → 校验其列集 = v4 基线（18 列）后记
  001 为已应用（不执行 SQL）；不符 → SystemExit 提示先用旧版本升级。
- 原子性如实登记：journal_mode=OFF 无回滚日志，「执行迁移」与「记账」之间的崩溃窗口靠备份
  兜底，不做伪原子。

### 9. data/sql/ 定位为基线快照

从「生成视图」改为**迁移链基线快照 + DBA 审查入口**（由 `scripts/dump_db_schema.py` 自动
生成、勿手改）：脚本在临时库跑迁移链再 dump，`--check` 校验快照与迁移链无漂移。
审查表结构从 `data/sql` 读，改表从 `migrations/` 读。

## 后果

- `/apps` → `/platforms`、账户契约字段改名均为破坏性变更（SDK 与 web 同步重生成）。
- 各域适配器删除全部 DDL 常量与自迁移代码；七处 `sqlite.py`/`state.py`/`layered.py` 零 DDL，
  只剩 UPSERT/查询 SQL 与列清单常量。
- 入口显式化：server lifespan 对主库 `ensure_migrated`；CLI 新增
  `butler db migrate` / `butler db status`。
- 代价：每次 schema 变更多一个迁移文件；换来 review 可见、审计可查、协作不漂移。
- 列序校正能力收编为 06-SQL规范「重建表迁移模板」（新表 → INSERT..SELECT 拷回 → DROP →
  RENAME → 重建索引）。
- 命名与结构约束的现行全文见 [06-SQL规范](../../conventions/06-SQL规范.md)。
