-- butler.db · 保管层（基线快照 · 2 张表）
--
-- 权威单源 = 迁移链 butler_engine/db/migrations/*.sql（ADR-036）；本文件由
-- scripts/dump_db_schema.py 生成，**勿手改**——改表 = 新增迁移文件 + 重跑本脚本。
-- 校验快照未漂移：uv run python scripts/dump_db_schema.py --check
-- 运行库落项目内 data/database/butler.db（BUTLER_DB 可覆盖）。
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
CREATE TABLE "vault_history" (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id   TEXT NOT NULL,
    kind         TEXT NOT NULL,
    slot         TEXT NOT NULL DEFAULT 'default',
    archived_ref TEXT NOT NULL,
    rotated_at   TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);
