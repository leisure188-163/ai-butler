-- butler.db · 健康域（基线快照 · 1 张表）
--
-- 权威单源 = 迁移链 butler_engine/db/migrations/*.sql（ADR-036）；本文件由
-- scripts/dump_db_schema.py 生成，**勿手改**——改表 = 新增迁移文件 + 重跑本脚本。
-- 校验快照未漂移：uv run python scripts/dump_db_schema.py --check
-- 运行库落项目内 data/database/butler.db（BUTLER_DB 可覆盖）。
CREATE TABLE "health_state" (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    key        TEXT NOT NULL UNIQUE,
    value      TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
