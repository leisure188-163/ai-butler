-- butler.db · 用量域 · usage/sqlite.py（生成视图 · 4 张表 / 4 个索引）
--
-- 权威单源 = 域适配器 DDL 常量（A4-01 §5：SQL 只存在于 butler_engine 适配器层，
-- 表按域分置）；本文件由 scripts/dump_db_schema.py 生成，**勿手改**。
-- 重新生成：uv run python scripts/dump_db_schema.py
-- 运行库落项目内 data/database/butler.db（BUTLER_DB 可覆盖）。
CREATE TABLE usage_snapshots (
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    target TEXT NOT NULL,
    collected_at TEXT NOT NULL,
    packages_json TEXT NOT NULL
);
CREATE INDEX idx_usage_snapshots_account
    ON usage_snapshots(account_id, collected_at);
CREATE TABLE usage_aggregates (
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    target TEXT NOT NULL,
    collected_at TEXT NOT NULL,
    summary_json TEXT NOT NULL
);
CREATE INDEX idx_usage_aggregates_account
    ON usage_aggregates(account_id, collected_at);
CREATE TABLE quota_ledger (
    account_id TEXT NOT NULL,
    record_id TEXT NOT NULL,
    target TEXT NOT NULL,
    occurred_at TEXT,
    amount REAL NOT NULL,
    unit TEXT NOT NULL,
    kind TEXT,
    raw_json TEXT,
    PRIMARY KEY (account_id, record_id)
);
CREATE INDEX idx_quota_ledger_account
    ON quota_ledger(account_id, occurred_at);
CREATE TABLE usage_samples (
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    tokens_in INTEGER NOT NULL,
    tokens_out INTEGER NOT NULL,
    model TEXT NOT NULL,
    ts TEXT NOT NULL,
    source TEXT NOT NULL,
    duration_ms REAL
);
CREATE INDEX idx_usage_samples_account
    ON usage_samples(account_id, ts);
