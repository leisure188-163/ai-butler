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

_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS plat_platform (
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
"""

_INDEX_DDL = """
CREATE INDEX IF NOT EXISTS idx_plat_platform_active ON plat_platform (is_active);
"""

_SCHEMA = _TABLE_DDL + _INDEX_DDL

#: 权威列序（DDL 单源）：老库补列只能追加到物理末尾，重排走 _reorder_columns
_DDL_COLS = (
    "platform_code", "platform_name", "name_override", "platform_kind", "client_version",
    "capabilities", "credential_kinds", "schedule_times", "schedule_override",
    "is_active", "deprecated_at", "created_at", "updated_at",
)
_COLS = ", ".join(_DDL_COLS)

#: 重建时缺失列的落值（显式未知，不猜）
_ADDED_DEFAULTS = {
    "platform_kind": "''", "client_version": "''", "schedule_override": "''",
    "name_override": "''",
}


def _dump(values: tuple[str, ...]) -> str:
    import json

    return json.dumps(list(values), ensure_ascii=False)


def _load_values(raw: str) -> tuple[str, ...]:
    import json

    try:
        return tuple(json.loads(raw or "[]"))
    except ValueError:
        return ()  # 坏行如实空，不炸名册（红线 5：不静默造数据）


def _load_override(raw: str | None) -> tuple[str, ...] | None:
    """'' = 跟随 manifest（None）；JSON 数组 = 用户覆盖（含空数组=不排班）。"""
    if not raw:
        return None
    return _load_values(raw)


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
            # 列名收编（ADR-023 命名裁决）：display_name → platform_name（幂等）
            plat_cols = {
                r[1] for r in conn.execute("PRAGMA table_info(plat_platform)").fetchall()
            }
            if "platform_name" not in plat_cols and "display_name" in plat_cols:
                conn.execute(
                    "ALTER TABLE plat_platform RENAME COLUMN display_name TO platform_name"
                )
            if plat_cols:
                for name, default in _ADDED_DEFAULTS.items():
                    if name not in plat_cols:
                        # 新增列（2026-11-18 裁决）：老库补列，存量行落显式未知
                        conn.execute(
                            f"ALTER TABLE plat_platform ADD COLUMN {name} TEXT NOT NULL DEFAULT {default}"
                        )
                _reorder_columns(conn)
            conn.executescript(_SCHEMA)

    def _connect(self):
        return connect(self._db)

    def upsert(self, entry: PlatformEntry) -> None:
        from butler_core.shared.time import now_utc

        created = entry.created_at.isoformat()
        with self._connect() as conn, conn:
            conn.execute(
                f"INSERT INTO plat_platform ({_COLS}) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT (platform_code) DO UPDATE SET "
                "platform_name=excluded.platform_name, platform_kind=excluded.platform_kind, "
                "client_version=excluded.client_version, "
                "capabilities=excluded.capabilities, "
                "credential_kinds=excluded.credential_kinds, schedule_times=excluded.schedule_times, "
                "updated_at=excluded.updated_at",
                (
                    entry.platform_code,
                    entry.platform_name,
                    entry.name_override,
                    entry.platform_kind.strip(),
                    entry.client_version.strip(),
                    _dump(entry.capabilities),
                    _dump(entry.credential_kinds),
                    _dump(entry.schedule_times),
                    _dump(entry.schedule_override) if entry.schedule_override is not None else "",
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

    def update_profile(
        self,
        platform_code: str,
        *,
        name_override: str | None = None,
        is_active: bool | None = None,
    ) -> PlatformEntry | None:
        """改显示名覆盖 / 启停（None = 不动；"" = 恢复 manifest 名）。平台不存在 → None。"""
        from butler_core.shared.time import now_utc

        sets: list[str] = []
        args: list[object] = []
        if name_override is not None:
            sets.append("name_override = ?")
            args.append(name_override)
        if is_active is not None:
            sets.append("is_active = ?")
            args.append(1 if is_active else 0)
        if not sets:
            return self.get(platform_code)
        sets.append("updated_at = ?")
        args.extend([now_utc().isoformat(), platform_code])
        with self._connect() as conn, conn:
            cur = conn.execute(
                f"UPDATE plat_platform SET {', '.join(sets)} WHERE platform_code = ?", args
            )
            if cur.rowcount == 0:
                return None
            row = conn.execute(
                f"SELECT {_COLS} FROM plat_platform WHERE platform_code = ?",
                (platform_code,),
            ).fetchone()
        return _load(row)

    def set_schedule_override(
        self, platform_code: str, times: tuple[str, ...] | None
    ) -> PlatformEntry | None:
        """写调度覆盖（None = 恢复跟随 manifest）。平台不存在 → None（调用方显式 404）。"""
        from butler_core.shared.time import now_utc

        stored = _dump(times) if times is not None else ""
        with self._connect() as conn, conn:
            cur = conn.execute(
                "UPDATE plat_platform SET schedule_override = ?, updated_at = ? "
                "WHERE platform_code = ?",
                (stored, now_utc().isoformat(), platform_code),
            )
            if cur.rowcount == 0:
                return None
            row = conn.execute(
                f"SELECT {_COLS} FROM plat_platform WHERE platform_code = ?",
                (platform_code,),
            ).fetchone()
        return _load(row)

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
        platform_name=row[1],
        name_override=row[2] or "",
        platform_kind=row[3] or "",
        client_version=row[4] or "",
        capabilities=_load_values(row[5]),
        credential_kinds=_load_values(row[6]),
        schedule_times=_load_values(row[7]),
        schedule_override=_load_override(row[8]),
        is_active=bool(row[9]),
        deprecated_at=datetime.fromisoformat(row[10]) if row[10] else None,
        created_at=datetime.fromisoformat(row[11]),
    )


def _reorder_columns(conn) -> None:
    """物理列序校正（幂等·零丢失）：SQLite 的 ADD COLUMN 只能追加到末尾，
    老库补列后列序与 DDL 权威序不符——按 _DDL_COLS 重建表并整表拷回。

    id 保持首位（代理键不漂移）；缺失列按 _ADDED_DEFAULTS 落显式未知。
    """
    actual = [r[1] for r in conn.execute("PRAGMA table_info(plat_platform)").fetchall()]
    if actual == ["id", *_DDL_COLS]:
        return
    conn.execute("DROP INDEX IF EXISTS idx_plat_platform_active")
    conn.execute("ALTER TABLE plat_platform RENAME TO plat_platform__reorder")
    conn.executescript(_TABLE_DDL)
    select = ", ".join(
        col if col in actual else _ADDED_DEFAULTS.get(col, "NULL") for col in _DDL_COLS
    )
    conn.execute(
        f"INSERT INTO plat_platform (id, {_COLS}) "
        f"SELECT id, {select} FROM plat_platform__reorder"
    )
    conn.execute("DROP TABLE plat_platform__reorder")
