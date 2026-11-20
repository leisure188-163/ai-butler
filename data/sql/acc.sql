-- butler.db · 账户域（基线快照 · 1 张表 / 3 个索引）
--
-- 权威单源 = 迁移链 butler_engine/db/migrations/*.sql（ADR-036）；本文件由
-- scripts/dump_db_schema.py 生成，**勿手改**——改表 = 新增迁移文件 + 重跑本脚本。
-- 校验快照未漂移：uv run python scripts/dump_db_schema.py --check
-- 运行库落项目内 data/database/butler.db（BUTLER_DB 可覆盖）。
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
