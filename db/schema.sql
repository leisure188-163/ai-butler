-- butler.db 全库 schema（生成视图 · 10 张表）
--
-- 权威单源 = 各域适配器的 DDL 常量（A4-01 §5：SQL 只存在于 butler_engine 适配器层，
-- 表按域分置）；本文件是 scripts/dump_db_schema.py 的产物，**勿手改**。
-- 重新生成：uv run python scripts/dump_db_schema.py
-- 运行数据不入库仓库：butler.db 落平台标准用户数据根（BUTLER_DB 可覆盖，A4-01 §5）。

-- ═══ 账户域 · accounts/sqlite.py ═══
CREATE TABLE accounts (
    id            TEXT PRIMARY KEY,
    provider      TEXT NOT NULL,
    display_name  TEXT NOT NULL,
    created_at    TEXT NOT NULL
);
CREATE INDEX idx_accounts_provider ON accounts (provider);

-- ═══ 执行域 · ledger/sqlite.py ═══
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
CREATE INDEX idx_runs_idempotency ON runs(idempotency_key);

-- ═══ 用量域 · usage/sqlite.py ═══
CREATE TABLE usage_snapshots (
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    target TEXT NOT NULL,
    collected_at TEXT NOT NULL,
    packages_json TEXT NOT NULL
);
CREATE TABLE usage_aggregates (
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    target TEXT NOT NULL,
    collected_at TEXT NOT NULL,
    summary_json TEXT NOT NULL
);
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
CREATE INDEX idx_usage_snapshots_account
    ON usage_snapshots(account_id, collected_at);
CREATE INDEX idx_usage_aggregates_account
    ON usage_aggregates(account_id, collected_at);
CREATE INDEX idx_quota_ledger_account
    ON quota_ledger(account_id, occurred_at);
CREATE INDEX idx_usage_samples_account
    ON usage_samples(account_id, ts);

-- ═══ 健康域 · health/state.py ═══
CREATE TABLE health_state (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ═══ 保管层 · vault/layered.py ═══
CREATE TABLE vault_items (
    account_id TEXT NOT NULL,
    kind       TEXT NOT NULL,
    backend    TEXT NOT NULL,
    expires_at TEXT,
    created_at TEXT NOT NULL,
    rotated_at TEXT,
    PRIMARY KEY (account_id, kind)
);
CREATE TABLE vault_history (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    archived_ref TEXT NOT NULL,
    rotated_at TEXT NOT NULL
);

-- ═══ shared 内核 · audit/sqlite.py ═══
CREATE TABLE audit (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    actor TEXT NOT NULL,
    account_id TEXT,
    credential_ref TEXT,
    action TEXT NOT NULL,
    outcome TEXT NOT NULL
);
