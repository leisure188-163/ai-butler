-- 002_conform_proxy_key_audit.sql · 全库表结构合规化（06-SQL规范 §1：id 代理键 + 审计三件）
-- 前置：001 ｜ 类型：重建表（INSERT..SELECT 拷回，零丢失，id 不漂移）
--
-- 001 基线里七张表沿袭旧形状，不合 06-SQL规范 §1 总原则：
--   usage_snapshot / usage_aggregate / usage_sample = TEXT 业务键当主键；
--   usage_quota_ledger = 复合主键；health_state = key 主键且缺 created_at；
--   vault_history / audit_log = seq 主键且缺审计三件。
-- 本迁移统一改为 `id INTEGER PRIMARY KEY AUTOINCREMENT` 代理键，
-- 业务键降级 UNIQUE 列（snapshot_id / aggregate_id / sample_id / (account_id, record_id) / key），
-- 补齐 created_at / updated_at（只增不改的事实表以业务时点落值）。

-- ── 用量域 ─────────────────────────────────────────────────────────
CREATE TABLE usage_snapshot__new (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id   TEXT NOT NULL UNIQUE,
    account_id    TEXT NOT NULL,
    target        TEXT NOT NULL,
    collected_at  TEXT NOT NULL,
    packages_json TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
INSERT INTO usage_snapshot__new
    (snapshot_id, account_id, target, collected_at, packages_json, created_at, updated_at)
SELECT id, account_id, target, collected_at, packages_json, collected_at, collected_at
FROM usage_snapshot;
DROP TABLE usage_snapshot;
ALTER TABLE usage_snapshot__new RENAME TO usage_snapshot;
CREATE INDEX idx_usage_snapshot_account
    ON usage_snapshot(account_id, collected_at);

CREATE TABLE usage_aggregate__new (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    aggregate_id TEXT NOT NULL UNIQUE,
    account_id   TEXT NOT NULL,
    target       TEXT NOT NULL,
    collected_at TEXT NOT NULL,
    summary_json TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);
INSERT INTO usage_aggregate__new
    (aggregate_id, account_id, target, collected_at, summary_json, created_at, updated_at)
SELECT id, account_id, target, collected_at, summary_json, collected_at, collected_at
FROM usage_aggregate;
DROP TABLE usage_aggregate;
ALTER TABLE usage_aggregate__new RENAME TO usage_aggregate;
CREATE INDEX idx_usage_aggregate_account
    ON usage_aggregate(account_id, collected_at);

CREATE TABLE usage_quota_ledger__new (
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
INSERT INTO usage_quota_ledger__new
    (account_id, record_id, target, occurred_at, amount, unit, kind, raw_json, created_at, updated_at)
SELECT account_id, record_id, target, occurred_at, amount, unit, kind, raw_json,
       COALESCE(occurred_at, datetime('now')), COALESCE(occurred_at, datetime('now'))
FROM usage_quota_ledger;
DROP TABLE usage_quota_ledger;
ALTER TABLE usage_quota_ledger__new RENAME TO usage_quota_ledger;
CREATE INDEX idx_usage_quota_ledger_account
    ON usage_quota_ledger(account_id, occurred_at);

CREATE TABLE usage_sample__new (
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
INSERT INTO usage_sample__new
    (sample_id, account_id, tokens_in, tokens_out, model, ts, source, duration_ms, created_at, updated_at)
SELECT id, account_id, tokens_in, tokens_out, model, ts, source, duration_ms, ts, ts
FROM usage_sample;
DROP TABLE usage_sample;
ALTER TABLE usage_sample__new RENAME TO usage_sample;
CREATE INDEX idx_usage_sample_account
    ON usage_sample(account_id, ts);

-- ── 健康域 ─────────────────────────────────────────────────────────
CREATE TABLE health_state__new (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    key        TEXT NOT NULL UNIQUE,
    value      TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
INSERT INTO health_state__new (key, value, created_at, updated_at)
SELECT key, value, updated_at, updated_at FROM health_state;
DROP TABLE health_state;
ALTER TABLE health_state__new RENAME TO health_state;

-- ── 保管层（凭据历史） ────────────────────────────────────────────
CREATE TABLE vault_history__new (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id   TEXT NOT NULL,
    kind         TEXT NOT NULL,
    slot         TEXT NOT NULL DEFAULT 'default',
    archived_ref TEXT NOT NULL,
    rotated_at   TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);
INSERT INTO vault_history__new
    (account_id, kind, slot, archived_ref, rotated_at, created_at, updated_at)
SELECT account_id, kind, slot, archived_ref, rotated_at, rotated_at, rotated_at
FROM vault_history;
DROP TABLE vault_history;
ALTER TABLE vault_history__new RENAME TO vault_history;

-- ── shared 内核（审计） ───────────────────────────────────────────
CREATE TABLE audit_log__new (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    ts             TEXT NOT NULL,
    actor          TEXT NOT NULL,
    account_id     TEXT,
    credential_ref TEXT,
    action         TEXT NOT NULL,
    outcome        TEXT NOT NULL,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);
INSERT INTO audit_log__new
    (ts, actor, account_id, credential_ref, action, outcome, created_at, updated_at)
SELECT ts, actor, account_id, credential_ref, action, outcome, ts, ts
FROM audit_log;
DROP TABLE audit_log;
ALTER TABLE audit_log__new RENAME TO audit_log;
