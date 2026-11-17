-- butler.db · 执行域 · ledger/sqlite.py（生成视图 · 1 张表 / 1 个索引）
--
-- 权威单源 = 域适配器 DDL 常量（A4-01 §5：SQL 只存在于 butler_engine 适配器层，
-- 表按域分置）；本文件由 scripts/dump_db_schema.py 生成，**勿手改**。
-- 重新生成：uv run python scripts/dump_db_schema.py
-- 运行库落项目内 data/database/butler.db（BUTLER_DB 可覆盖）。
CREATE TABLE exe_run (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    target TEXT NOT NULL,
    params_json TEXT NOT NULL,
    account_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    started_at TEXT NOT NULL,
    budget_seconds REAL NOT NULL,
    finished_at TEXT,
    status TEXT,
    result_json TEXT
);
CREATE INDEX idx_exe_run_idempotency ON exe_run(idempotency_key);
