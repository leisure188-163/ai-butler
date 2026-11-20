-- butler.db · shared 内核（审计）（基线快照 · 1 张表）
--
-- 权威单源 = 迁移链 butler_engine/db/migrations/*.sql（ADR-036）；本文件由
-- scripts/dump_db_schema.py 生成，**勿手改**——改表 = 新增迁移文件 + 重跑本脚本。
-- 校验快照未漂移：uv run python scripts/dump_db_schema.py --check
-- 运行库落项目内 data/database/butler.db（BUTLER_DB 可覆盖）。
CREATE TABLE "audit_log" (
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
