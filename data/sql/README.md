# data/sql · butler.db schema 基线快照（按业务域分文件，DBA 审查入口）

> **为什么有这个目录**：表 DDL 真相源在 `butler_engine/db/migrations/*.sql`
> 编号迁移文件（ADR-018），没有一个「一处看完全部表」的地方。本目录补的就是
> 这个视图——**生成产物，勿手改**。（2026-11-16 自 `db/` 迁入 `data/sql/`；
> 2026-11-17 拆分为每业务域一个文件；2026-11-20 随 ADR-018 从「生成视图」
> 重定位为「迁移链基线快照 + DBA 审查入口」——多人协作 / 多服务共享库时
> 审查表结构从这里读，改表从 migrations/ 读。）

## 里面有什么

| 文件 | 说明 |
|---|---|
| `acc.sql` | 账户域：acc_account + 3 索引 |
| `plat.sql` | 平台域：plat_platform + 1 索引（ADR-001） |
| `exe.sql` | 执行域：exe_claim 领取记录 + 1 索引（ADR-018） |
| `usage.sql` | 用量域：usage_snapshot / usage_aggregate / usage_quota_ledger / usage_sample + 4 索引 |
| `health.sql` | 健康域：health_state |
| `vault.sql` | 保管层：vault_item / vault_history |
| `audit.sql` | shared 内核：audit_log |

> **文件名 = 表名域前缀**（2026-11-17 裁决）：acc/plat/exe 与表名前缀一字不差。

## 权威单源与纪律（ADR-018）

- **DDL 权威单源 = 迁移链** `butler_engine/db/migrations/*.sql`；改表 = 新增
  `NNN_描述.sql`（forward-only，❌ 改历史迁移文件）。
- **本目录是快照**：由 `scripts/dump_db_schema.py` 在临时库跑迁移链后 dump
  `sqlite_master` 生成——它 dump 的是「真库」，不是手抄，可当
  「迁移链 ↔ 快照」的漂移探针。
- **改表流程**：新增迁移文件 → 跑 `uv run python scripts/dump_db_schema.py`
  → 对应域 `<前缀>.sql` 随同批提交；提交前 `--check` 校验无漂移。
- **防漂移守卫**：导出脚本发现映射之外的表/索引会显式报错退出（红线 5），
  新表必须先在脚本 `_SECTIONS` 登记所属域；登记了域却没有任何对象同样报错。
- **全量视图**：需要一处看全库时 `cat data/sql/*.sql` 即可。

## 边界

- **运行库不入本目录**：`butler.db` 落项目内 `data/database/`（BUTLER_DB 可覆盖；
  2026-11-16 用户裁决数据根迁项目内——本机文件虚拟化层锁死平台标准数据根，
  A4-01 §5 注记）——gitignore 排除，运行数据不进 git。
- `data/doubao_identity.json`（豆包身份基线）同为运行时本机状态，gitignore 排除。
- 本目录不参与 verify 六项门禁的文件长度/结构检查面（.sql 非代码文件）。
