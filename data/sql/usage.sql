-- butler.db · 用量域（基线快照 · 4 张表 / 4 个索引）
--
-- 权威单源 = 迁移链 butler_engine/db/migrations/*.sql（ADR-036）；本文件由
-- scripts/dump_db_schema.py 生成，**勿手改**——改表 = 新增迁移文件 + 重跑本脚本。
-- 校验快照未漂移：uv run python scripts/dump_db_schema.py --check
-- 运行库落项目内 data/database/butler.db（BUTLER_DB 可覆盖）。
CREATE TABLE "usage_snapshot" (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id   TEXT NOT NULL UNIQUE,
    account_id    TEXT NOT NULL,
    target        TEXT NOT NULL,
    collected_at  TEXT NOT NULL,
    packages_json TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
CREATE INDEX idx_usage_snapshot_account
    ON usage_snapshot(account_id, collected_at);
CREATE TABLE "usage_aggregate" (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    aggregate_id TEXT NOT NULL UNIQUE,
    account_id   TEXT NOT NULL,
    target       TEXT NOT NULL,
    collected_at TEXT NOT NULL,
    summary_json TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);
CREATE INDEX idx_usage_aggregate_account
    ON usage_aggregate(account_id, collected_at);
CREATE TABLE "usage_quota_ledger" (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id TEXT NOT NULL,
    record_id  TEXT NOT NULL,
    target     TEXT NOT NULL,
    occurred_at TEXT,
    amount     REAL NOT NULL,
    unit       TEXT NOT NULL,
    kind       TEXT,
    raw_json   TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (account_id, record_id)
);
CREATE INDEX idx_usage_quota_ledger_account
    ON usage_quota_ledger(account_id, occurred_at);
CREATE TABLE "usage_sample" (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    sample_id   TEXT NOT NULL UNIQUE,
    account_id  TEXT NOT NULL,
    tokens_in   INTEGER NOT NULL,
    tokens_out  INTEGER NOT NULL,
    model       TEXT NOT NULL,
    ts          TEXT NOT NULL,
    source      TEXT NOT NULL,
    duration_ms REAL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX idx_usage_sample_account
    ON usage_sample(account_id, ts);
