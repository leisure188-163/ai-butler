# data/sql · butler.db 全库 schema 生成视图

> **为什么有这个目录**：表 DDL 按域分散在各适配器（规范如此），没有一个
> 「一处看完全部表」的地方。本目录补的就是这个视图——**生成产物，勿手改**。
> （2026-11-16 自 `db/` 迁入 `data/sql/`：用户裁决数据域统一收在项目 `data/` 下。）

## 里面有什么

| 文件 | 说明 |
|---|---|
| `butler-schema.sql` | butler.db 全部表 + 索引的 DDL，按业务域分节（账户/执行/用量/健康/保管层/shared 审计），直接可读、可贴给任何工具 |

## 权威单源与纪律

- **DDL 权威单源仍是代码**：`butler_engine` 各域适配器的 `_SCHEMA` 常量
  （A4-01 §5「SQL 只存在于 packages/engine 适配器层，表按域分置」——分散是
  规范刻意的设计：端口随域走，集中 DDL 会造出跨域共享文件，破坏依赖恒等式）。
- **本目录只是生成视图**：由 `scripts/dump_db_schema.py` 在临时目录用与运行时
  相同的适配器真实建库后 dump `sqlite_master` 生成——它 dump 的是「真库」，不是
  手抄，可当「代码 ↔ 视图」的漂移探针。
- **改表流程**：改某域适配器的 `_SCHEMA` → 跑 `uv run python scripts/dump_db_schema.py`
  → `butler-schema.sql` 随同批提交（加列/改列还须配套 `PRAGMA user_version` 显式迁移，
  A4-01 §5 schema 演进纪律）。
- **防漂移守卫**：导出脚本发现映射之外的表/索引会显式报错退出（红线 5），
  新表必须先在脚本 `_SECTIONS` 登记分节。

## 边界

- **运行库不入本目录**：`butler.db` 落项目内 `data/database/`（BUTLER_DB 可覆盖；
  2026-11-16 用户裁决数据根迁项目内——本机文件虚拟化层锁死平台标准数据根，
  A4-01 §5 注记）——gitignore 排除，运行数据不进 git。
- `data/doubao_identity.json`（豆包身份基线）同为运行时本机状态，gitignore 排除。
- 本目录不参与 verify 六项门禁的文件长度/结构检查面（.sql 非代码文件）。
