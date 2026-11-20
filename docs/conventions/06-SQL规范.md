---
name: butler-sql
description: butler 全库 SQL/表结构约束——表名、列名、审计字段、迁移与产物纪律。TRIGGER when 建表/改列/写 engine 域适配器 SQL/生成 schema 产物/评审 SQL；DO NOT TRIGGER when 纯查询语句编写、不改表结构的数据操作。
version: "1.1.0"
level: must
---

# 06 · SQL 规范（全库表结构约束）

> **唯一源**：表结构真相源 = `butler_engine/db/migrations/*.sql` 编号迁移文件
> （ADR-018）；域适配器零 DDL，只剩 UPSERT/查询 SQL 与列清单常量。
> 本文是**命名与结构约束**的唯一入口。裁决溯源：ADR-018（命名与表结构演进）、
> ADR-001（第六域）、ADR-018（migration-first）。
> 冲突时：本文 > 域分册（A2-04..A2-09）> ADR。

## 1. 总原则（❌ 禁止违反）

1. **统一审计字段**：每张表必备三件——
   `id INTEGER PRIMARY KEY AUTOINCREMENT`（全库统一自增**代理键**）
   + `created_at TEXT NOT NULL` + `updated_at TEXT NOT NULL`。
   ❌ 禁止用业务键（如 platform_code）当主键；❌ 禁止漏审计列。
2. **表名 = 域缩写前缀 + 单数实体**：`acc_account` / `plat_platform` / `exe_claim` /
   `usage_snapshot` / `usage_aggregate` / `usage_quota_ledger` / `usage_sample` /
   `health_state` / `vault_item` / `vault_history` / `audit_log`。
   ❌ 禁止裸实体名（`accounts`/`runs`/`audit` 这种）——业务扩展后难辨域。
3. **禁用数据库关键字作列名**：`enabled` → `is_active`（ADR-018）。
   新列起名先对照 SQLite 关键字表。
4. **显示名称列按业务命名**：一律 `XXX_name`（账户 = `account_name`、
   平台 = `platform_name`），❌ 禁止 `display_name` / `name` 裸通用名（ADR-018）。
5. **身份/引用列 code 化**：`account_code`（非 account_key）、`platform_code`
   （非 platform）（ADR-018）；对外引用恒等式 = 其它域只持 code 字符串。
6. **表结构变更 = 新增编号迁移文件**（ADR-018）：在
   `butler_engine/db/migrations/` 加 `NNN_描述.sql`（编号连续、forward-only、
   文件内不写 IF NOT EXISTS——幂等由版本表保证），❌ 禁止改历史迁移文件
   （checksum 记账校验，篡改 = 红线 5）、❌ 禁止 down-migration（回滚 = 备份还原）、
   ❌ 禁止删行迁数据（零数据丢失）。改完跑 `uv run python scripts/dump_db_schema.py`
   刷 data/sql 基线快照。
7. **不删行原则**：事实退役走生命周期列（如 `deprecated_at`），❌ 禁止
   manifest 缺失/用户停用就 DELETE 行（审计可溯）。

## 2. 分类细则

| 类型 | 正确形态 | 禁止 |
|------|----------|------|
| 主键 | `id` 自增代理键 | 业务键当主键、无 id 裸表 |
| 唯一业务键 | 落 UNIQUE 列（如 `platform_code` TEXT NOT NULL UNIQUE） | 靠主键兼做业务键 |
| 索引名 | 随表名：`idx_<表>_<列>` / `uq_<表>_<列>_key` | 与表名脱钩的旧索引名 |
| 布尔列 | `is_active INTEGER DEFAULT 1` | `enabled`/`disabled` 等关键字 |
| JSON 列 | TEXT 存 JSON（`capabilities`/`schedule_times`/`sessions`），随聚合整体替换 | 拆出隐式关联表（无聚合语义时） |
| DDL 单源 | `butler_engine/db/migrations/*.sql` 编号迁移文件（ADR-018） | SQL 散落在适配器/脚本/文档/端侧 |
| 迁移 | 新增 `NNN_描述.sql` + 版本表 `db_migration` 记账（自举例外，不入迁移链） | 改历史迁移、隐式自迁移、PRAGMA user_version |
| 产物 | `data/sql/<域>.sql` 由 `scripts/dump_db_schema.py` 生成（临时库跑迁移链再 dump），**勿手改**；改表后必须重跑；`--check` 校验漂移 | 手工编辑产物、产物与迁移链漂移 |
| 产物分域 | 一域一文件，**文件名 = 表名域前缀**（acc.sql / plat.sql / exe.sql / usage.sql / health.sql / vault.sql / audit.sql） | 全库挤一个 schema.sql、文件名与表名前缀脱钩 |
| 域归属登记 | `dump_db_schema.py` `_SECTIONS` 表/索引→域映射 + `_DOMAIN_FILES` 域→文件 | 新表不登记（产物漏生成） |
| UPSERT | `ON CONFLICT(<业务键>) DO UPDATE`，保代理键不漂移 | 先 DELETE 再 INSERT |
| 状态语义分离 | 生命周期（deprecated_at）≠ 用户开关（is_active），两列分开 | 一列混用两义 |

## 3. 已定稿对照（废弃 → 现行）

| 废弃 | 现行 | 裁决 |
|------|------|------|
| 裸表名 accounts/runs/usage_snapshots/… | acc_account / exe_claim / usage_snapshot / … | ADR-018 |
| `provider` 列 | `app` → `platform_code` | ADR-018 |
| `account_key` / `display_name` | `account_code` / `account_name` | ADR-018 |
| `enabled` 列 | `is_active` | ADR-018 |
| 平台册 acc_platform（寄居账户域） | plat_platform（platforms 域，第六业务域） | ADR-001 |
| exe_run（泛化 run 命名 + TEXT 主键无审计列） | exe_claim（领取记录，代理键 + run_id 业务键 + 审计三件） | ADR-018 |
| 适配器 `_SCHEMA` 常量 + `__init__` 隐式自迁移 | migrations/*.sql 编号迁移 + db_migration 版本表 | ADR-018 |
| PRAGMA user_version（A4-01 §5 预埋） | db_migration 版本表（可见可查可审计） | ADR-018 |
| usage_snapshot/aggregate/sample TEXT 主键、quota_ledger 复合主键、health_state key 主键、vault_history/audit_log seq 主键（均缺审计三件） | 统一 `id` 代理键 + 唯一业务键（snapshot_id/aggregate_id/sample_id/UNIQUE(account_id,record_id)/key）+ 审计三件（迁移 002 合规化） | 06 §1 |

## 4. 检查清单（建表/改表 PR 自查）

- [ ] `id` 自增代理键 + `created_at`/`updated_at` 三件齐
- [ ] 表名 = 域缩写前缀 + 单数实体；索引名随表名
- [ ] 无数据库关键字列名；显示列 = `XXX_name`
- [ ] 业务键 UNIQUE；UPSERT ON CONFLICT 指向业务键
- [ ] 改表 = 新增 `migrations/NNN_描述.sql`（编号连续，不碰历史文件）
- [ ] 跑过 `uv run python scripts/dump_db_schema.py`，`data/sql/*.sql` 已同步
- [ ] 新表/索引已在 `dump_db_schema.py` `_SECTIONS` 登记域归属
- [ ] 对应域分册（A2-04..A2-09）表格已更新（红线 8：文档同提交收编）

## 列序纪律（2026-11-18 裁决；能力收编于 ADR-018 重建模板）

- **DDL 权威列序**：迁移文件里声明的列顺序即唯一权威序（`id` 首位，
  业务列按语义成组：code → name → kind → version → JSON 能力列 → 开关 → 审计三件）；
  适配器列清单常量（如 accounts `_COLS`）必须与迁移文件列序一致。
- **重建表迁移模板**：SQLite 的 `ALTER TABLE ADD COLUMN` 只能追加到末尾，
  需要校正列序/改主键时，在新迁移文件里重建表——建新表 →
  `INSERT ... SELECT` 整表拷回（缺失列落显式默认，NOT NULL 不落 NULL）→
  DROP 旧表 → 重建索引，**零丢失、id 不漂移**。
- **测试必须覆盖**新迁移文件的行为（空库/存量 baseline/数据拷回正确性，
  参考 `packages/engine/tests/test_schema_migrate.py`）。
