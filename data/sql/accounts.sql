-- butler.db · 账户域 · accounts/sqlite.py + accounts/platform_sqlite.py（生成视图 · 2 张表 / 3 个索引）
--
-- 权威单源 = 域适配器 DDL 常量（A4-01 §5：SQL 只存在于 butler_engine 适配器层，
-- 表按域分置）；本文件由 scripts/dump_db_schema.py 生成，**勿手改**。
-- 重新生成：uv run python scripts/dump_db_schema.py
-- 运行库落项目内 data/database/butler.db（BUTLER_DB 可覆盖）。
CREATE TABLE acc_account (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id       TEXT NOT NULL UNIQUE,
    platform_code    TEXT NOT NULL,
    account_code     TEXT NOT NULL DEFAULT 'main',
    account_name     TEXT NOT NULL,
    base_url         TEXT,
    device_ref       TEXT,
    sessions         TEXT NOT NULL DEFAULT '[]',
    entitlement_json TEXT,
    is_active        INTEGER NOT NULL DEFAULT 1,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    deleted_at       TEXT
);
CREATE UNIQUE INDEX uq_acc_account_platform_code_key
    ON acc_account (platform_code, account_code);
CREATE INDEX idx_acc_account_platform_code ON acc_account (platform_code);
CREATE TABLE acc_platform (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    platform_code    TEXT NOT NULL UNIQUE,
    display_name     TEXT NOT NULL,
    capabilities     TEXT NOT NULL DEFAULT '[]',
    credential_kinds TEXT NOT NULL DEFAULT '[]',
    schedule_times   TEXT NOT NULL DEFAULT '[]',
    is_active        INTEGER NOT NULL DEFAULT 1,
    deprecated_at    TEXT,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);
CREATE INDEX idx_acc_platform_active ON acc_platform (is_active);
