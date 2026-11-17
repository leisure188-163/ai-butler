"""平台域适配器（A2-09，ADR-021/022）：连接器平台事实落库，DB 为真相源。

组合根（server 装配层）启动时从连接器 manifest 抽纯数据 facts → SyncPlatforms
用例 → 本适配器 UPSERT + 缺失平台落 deprecated。web `/platforms` 名册读本表
+ 台账并账，不再每次装配穿连接器包拼装（端零映射）。

表名带域前缀（ADR-021 全库表名纪律）：plat_platform。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from butler_core.platforms.ports import PlatformRepository
from butler_core.platforms.domain import PlatformEntry

from butler_engine.db.conn import connect

_SCHEMA = """
CREATE TABLE IF NOT EXISTS plat_platform (
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
CREATE INDEX IF NOT EXISTS idx_plat_platform_active ON plat_platform (is_active);
"""

_COLS = (
    "platform_code, display_name, capabilities, credential_kinds, schedule_times, "
    "is_active, deprecated_at, created_at, updated_at"
)


def _dump(values: tuple[str, ...]) -> str:
    import json

    return json.dumps(list(values), ensure_ascii=False)


def _load_values(raw: str) -> tuple[str, ...]:
    import json

    try:
        return tuple(json.loads(raw or "[]"))
    except ValueError:
        return ()  # 坏行如实空，不炸名册（红线 5：不静默造数据）


class SqlitePlatformRepository(PlatformRepository):
    def __init__(self, db_path: str | Path) -> None:
        self._db = str(db_path)
        with self._connect() as conn, conn:
            # 表名迁移（ADR-022）：独立平台域后 acc_platform → plat_platform（幂等）
            if conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='acc_platform'"
            ).fetchone():
                conn.execute("ALTER TABLE acc_platform RENAME TO plat_platform")
            conn.execute("DROP INDEX IF EXISTS idx_acc_platform_active")
            conn.executescript(_SCHEMA)

    def _connect(self):
        return connect(self._db)

    def upsert(self, entry: PlatformEntry) -> None:
        from butler_core.shared.time import now_utc

        created = entry.created_at.isoformat()
        with self._connect() as conn, conn:
            conn.execute(
                f"INSERT INTO plat_platform ({_COLS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT (platform_code) DO UPDATE SET "
                "display_name=excluded.display_name, capabilities=excluded.capabilities, "
                "credential_kinds=excluded.credential_kinds, schedule_times=excluded.schedule_times, "
                "updated_at=excluded.updated_at",
                (
                    entry.platform_code,
                    entry.display_name,
                    _dump(entry.capabilities),
                    _dump(entry.credential_kinds),
                    _dump(entry.schedule_times),
                    1 if entry.is_active else 0,
                    entry.deprecated_at.isoformat() if entry.deprecated_at else None,
                    created,
                    now_utc().isoformat(),
                ),
            )

    def deprecate_missing(self, platform_codes: frozenset[str]) -> list[str]:
        from butler_core.shared.time import now_utc

        now = now_utc().isoformat()
        with self._connect() as conn, conn:
            rows = conn.execute(
                "SELECT platform_code FROM plat_platform "
                "WHERE deprecated_at IS NULL AND platform_code NOT IN "
                f"({', '.join('?' * len(platform_codes)) or "''"})",
                tuple(platform_codes),
            ).fetchall()
            stale = [r[0] for r in rows]
            for code in stale:
                conn.execute(
                    "UPDATE plat_platform SET deprecated_at = ?, updated_at = ? WHERE platform_code = ?",
                    (now, now, code),
                )
        return stale

    def get(self, platform_code: str) -> PlatformEntry | None:
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT {_COLS} FROM plat_platform WHERE platform_code = ?",
                (platform_code,),
            ).fetchone()
        return _load(row)

    def list_all(self) -> list[PlatformEntry]:
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT {_COLS} FROM plat_platform ORDER BY platform_code"
            ).fetchall()
        return [_load(r) for r in rows]


def _load(row) -> PlatformEntry | None:
    if row is None:
        return None
    return PlatformEntry(
        platform_code=row[0],
        display_name=row[1],
        capabilities=_load_values(row[2]),
        credential_kinds=_load_values(row[3]),
        schedule_times=_load_values(row[4]),
        is_active=bool(row[5]),
        deprecated_at=datetime.fromisoformat(row[6]) if row[6] else None,
        created_at=datetime.fromisoformat(row[7]),
    )
