-- butler.db · 保管层 · vault/layered.py（生成视图 · 2 张表）
--
-- 权威单源 = 域适配器 DDL 常量（A4-01 §5：SQL 只存在于 butler_engine 适配器层，
-- 表按域分置）；本文件由 scripts/dump_db_schema.py 生成，**勿手改**。
-- 重新生成：uv run python scripts/dump_db_schema.py
-- 运行库落项目内 data/database/butler.db（BUTLER_DB 可覆盖）。
CREATE TABLE vault_item (
    account_id TEXT NOT NULL,
    kind       TEXT NOT NULL,
    backend    TEXT NOT NULL,
    expires_at TEXT,
    created_at TEXT NOT NULL,
    rotated_at TEXT,
    revoked_at TEXT,
    revoked_reason TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (account_id, kind)
);
CREATE TABLE vault_history (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    archived_ref TEXT NOT NULL,
    rotated_at TEXT NOT NULL
);
