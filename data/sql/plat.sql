-- butler.db · 平台域（基线快照 · 1 张表 / 1 个索引）
--
-- 权威单源 = 迁移链 butler_engine/db/migrations/*.sql（ADR-036）；本文件由
-- scripts/dump_db_schema.py 生成，**勿手改**——改表 = 新增迁移文件 + 重跑本脚本。
-- 校验快照未漂移：uv run python scripts/dump_db_schema.py --check
-- 运行库落项目内 data/database/butler.db（BUTLER_DB 可覆盖）。
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
