-- butler.db · 健康域 · health/state.py（生成视图 · 1 张表）
--
-- 权威单源 = 域适配器 DDL 常量（A4-01 §5：SQL 只存在于 butler_engine 适配器层，
-- 表按域分置）；本文件由 scripts/dump_db_schema.py 生成，**勿手改**。
-- 重新生成：uv run python scripts/dump_db_schema.py
-- 运行库落项目内 data/database/butler.db（BUTLER_DB 可覆盖）。
CREATE TABLE health_state (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
