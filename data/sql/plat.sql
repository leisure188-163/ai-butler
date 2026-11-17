-- butler.db · 平台域 · platforms/sqlite.py（生成视图 · 1 张表 / 1 个索引）
--
-- 权威单源 = 域适配器 DDL 常量（A4-01 §5：SQL 只存在于 butler_engine 适配器层，
-- 表按域分置）；本文件由 scripts/dump_db_schema.py 生成，**勿手改**。
-- 重新生成：uv run python scripts/dump_db_schema.py
-- 运行库落项目内 data/database/butler.db（BUTLER_DB 可覆盖）。
CREATE TABLE plat_platform (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    platform_code    TEXT NOT NULL UNIQUE,
    platform_name    TEXT NOT NULL,
    name_override    TEXT NOT NULL DEFAULT '',
    platform_kind    TEXT NOT NULL DEFAULT '',
    client_version   TEXT NOT NULL DEFAULT '',
    capabilities     TEXT NOT NULL DEFAULT '[]',
    credential_kinds TEXT NOT NULL DEFAULT '[]',
    schedule_times   TEXT NOT NULL DEFAULT '[]',
    schedule_override TEXT NOT NULL DEFAULT '',
    is_active        INTEGER NOT NULL DEFAULT 1,
    deprecated_at    TEXT,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);
CREATE INDEX idx_plat_platform_active ON plat_platform (is_active);
