-- 001_initial.sql · 全库初始基线：六业务域 + 保管层 + 审计（11 张表 / 9 个索引）
-- 前置：无 ｜ 类型：CREATE TABLE/INDEX（历史 v1→v4 squash，ADR-036）
--
-- 语句逐字取自 data/sql/*.sql 基线快照（dump_db_schema.py 生成视图），
-- 重跑 dump 必须与本迁移链产物逐字一致（等价性由 --check 门禁）。

-- ── 账户域 ─────────────────────────────────────────────────────────
CREATE TABLE acc_account (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    platform_code    TEXT NOT NULL,
    source_key       TEXT NOT NULL DEFAULT '',
    account_id       TEXT NOT NULL UNIQUE,
    account_code     TEXT NOT NULL DEFAULT '',
    account_name     TEXT NOT NULL,
    alias            TEXT NOT NULL DEFAULT '',
    base_url         TEXT,
    device_ref       TEXT,
    identity_json    TEXT,
    origin           TEXT NOT NULL DEFAULT 'connector',
    last_seen_at     TEXT,
    sessions         TEXT NOT NULL DEFAULT '[]',
    entitlement_json TEXT,
    is_active        INTEGER NOT NULL DEFAULT 1,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    deleted_at       TEXT
);
CREATE UNIQUE INDEX uq_acc_account_platform_code_key
    ON acc_account (platform_code, account_code) WHERE account_code <> '';
CREATE UNIQUE INDEX uq_acc_account_platform_source_key
    ON acc_account (platform_code, source_key) WHERE source_key <> '';
CREATE INDEX idx_acc_account_platform_code ON acc_account (platform_code);

-- ── 平台域 ─────────────────────────────────────────────────────────
CREATE TABLE plat_platform (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    platform_code    TEXT NOT NULL UNIQUE,
    platform_name    TEXT NOT NULL,
    platform_kind    TEXT NOT NULL DEFAULT '',
    client_version   TEXT NOT NULL DEFAULT '',
    icon             TEXT NOT NULL DEFAULT '',
    capabilities     TEXT NOT NULL DEFAULT '[]',
    credential_kinds TEXT NOT NULL DEFAULT '[]',
    schedule_times   TEXT NOT NULL DEFAULT '[]',
    schedule_override TEXT NOT NULL DEFAULT '',
    base_url         TEXT NOT NULL DEFAULT '',
    protocol         TEXT NOT NULL DEFAULT '',
    models_json      TEXT NOT NULL DEFAULT '[]',
    origin           TEXT NOT NULL DEFAULT 'connector',
    is_active        INTEGER NOT NULL DEFAULT 1,
    deprecated_at    TEXT,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);
CREATE INDEX idx_plat_platform_active ON plat_platform (is_active);

-- ── 执行域 ─────────────────────────────────────────────────────────
CREATE TABLE exe_claim (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL,
    target TEXT NOT NULL,
    params_json TEXT NOT NULL,
    account_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    started_at TEXT NOT NULL,
    budget_seconds REAL NOT NULL,
    finished_at TEXT,
    status TEXT,
    result_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX idx_exe_claim_idempotency ON exe_claim(idempotency_key);

-- ── 用量域 ─────────────────────────────────────────────────────────
CREATE TABLE usage_snapshot (
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    target TEXT NOT NULL,
    collected_at TEXT NOT NULL,
    packages_json TEXT NOT NULL
);
CREATE INDEX idx_usage_snapshot_account
    ON usage_snapshot(account_id, collected_at);
CREATE TABLE usage_aggregate (
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    target TEXT NOT NULL,
    collected_at TEXT NOT NULL,
    summary_json TEXT NOT NULL
);
CREATE INDEX idx_usage_aggregate_account
    ON usage_aggregate(account_id, collected_at);
CREATE TABLE usage_quota_ledger (
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
CREATE INDEX idx_usage_quota_ledger_account
    ON usage_quota_ledger(account_id, occurred_at);
CREATE TABLE usage_sample (
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    tokens_in INTEGER NOT NULL,
    tokens_out INTEGER NOT NULL,
    model TEXT NOT NULL,
    ts TEXT NOT NULL,
    source TEXT NOT NULL,
    duration_ms REAL
);
CREATE INDEX idx_usage_sample_account
    ON usage_sample(account_id, ts);

-- ── 健康域 ─────────────────────────────────────────────────────────
CREATE TABLE health_state (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ── 保管层（凭据元数据） ──────────────────────────────────────────
CREATE TABLE vault_item (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id     TEXT NOT NULL,
    kind           TEXT NOT NULL,
    slot           TEXT NOT NULL DEFAULT 'default',
    label          TEXT NOT NULL DEFAULT '',
    backend        TEXT NOT NULL,
    expires_at     TEXT,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL,
    rotated_at     TEXT,
    revoked_at     TEXT,
    revoked_reason TEXT NOT NULL DEFAULT '',
    UNIQUE (account_id, kind, slot)
);
CREATE TABLE vault_history (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    slot TEXT NOT NULL DEFAULT 'default',
    archived_ref TEXT NOT NULL,
    rotated_at TEXT NOT NULL
);

-- ── shared 内核（审计） ───────────────────────────────────────────
CREATE TABLE audit_log (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    actor TEXT NOT NULL,
    account_id TEXT,
    credential_ref TEXT,
    action TEXT NOT NULL,
    outcome TEXT NOT NULL
);
