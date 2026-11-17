-- butler.db · 账户域 · accounts/sqlite.py（生成视图 · 1 张表 / 2 个索引）
--
-- 权威单源 = 域适配器 DDL 常量（A4-01 §5：SQL 只存在于 butler_engine 适配器层，
-- 表按域分置）；本文件由 scripts/dump_db_schema.py 生成，**勿手改**。
-- 重新生成：uv run python scripts/dump_db_schema.py
-- 运行库落项目内 data/database/butler.db（BUTLER_DB 可覆盖）。
CREATE TABLE accounts (
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
CREATE UNIQUE INDEX uq_accounts_platform_code_key
    ON accounts (platform_code, account_code);
CREATE INDEX idx_accounts_platform_code ON accounts (platform_code);
