-- butler 数据库 schema（从运行库导出，journal_mode=OFF，A4-01 §5）
-- 生成时间：2026-11-16；重建：sqlite3 butler.db < butler-schema.sql
-- 数据根：data/database/butler.db（BUTLER_DB 可覆盖）

-- table accounts
CREATE TABLE accounts (
    id            TEXT PRIMARY KEY,
    provider      TEXT NOT NULL,
    display_name  TEXT NOT NULL,
    created_at    TEXT NOT NULL
, sessions TEXT NOT NULL DEFAULT '[]');

-- table audit
CREATE TABLE audit (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    actor TEXT NOT NULL,
    account_id TEXT,
    credential_ref TEXT,
    action TEXT NOT NULL,
    outcome TEXT NOT NULL
);

-- table health_state
CREATE TABLE health_state (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- table quota_ledger
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

-- table runs
CREATE TABLE runs (
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

-- table sqlite_sequence
CREATE TABLE sqlite_sequence(name,seq);

-- table usage_aggregates
CREATE TABLE usage_aggregates (
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    target TEXT NOT NULL,
    collected_at TEXT NOT NULL,
    summary_json TEXT NOT NULL
);

-- table usage_samples
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

-- table usage_snapshots
CREATE TABLE usage_snapshots (
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    target TEXT NOT NULL,
    collected_at TEXT NOT NULL,
    packages_json TEXT NOT NULL
);

-- table vault_history
CREATE TABLE vault_history (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    archived_ref TEXT NOT NULL,
    rotated_at TEXT NOT NULL
);

-- table vault_items
CREATE TABLE vault_items (
    account_id TEXT NOT NULL,
    kind       TEXT NOT NULL,
    backend    TEXT NOT NULL,
    expires_at TEXT,
    created_at TEXT NOT NULL,
    rotated_at TEXT,
    PRIMARY KEY (account_id, kind)
);

-- index idx_accounts_provider
CREATE INDEX idx_accounts_provider ON accounts (provider);

-- index idx_quota_ledger_account
CREATE INDEX idx_quota_ledger_account
    ON quota_ledger(account_id, occurred_at);

-- index idx_runs_idempotency
CREATE INDEX idx_runs_idempotency ON runs(idempotency_key);

-- index idx_usage_aggregates_account
CREATE INDEX idx_usage_aggregates_account
    ON usage_aggregates(account_id, collected_at);

-- index idx_usage_samples_account
CREATE INDEX idx_usage_samples_account
    ON usage_samples(account_id, ts);

-- index idx_usage_snapshots_account
CREATE INDEX idx_usage_snapshots_account
    ON usage_snapshots(account_id, collected_at);
