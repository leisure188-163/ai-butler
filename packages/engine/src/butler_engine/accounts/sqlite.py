"""账号名册适配器（A2-01 §1）：SQLite 单库、与台账/审计同库不同表。

accounts v3（2026-11-17 用户裁决，ADR-019）：
- 每表统一代理键 `id INTEGER PRIMARY KEY AUTOINCREMENT`（DDL 约定见 A4-01 §5）；
  账户规范 id `{platform}:{account_key}` 降级为业务键 `account_id`（UNIQUE）。
- 统一审计列 `created_at / updated_at` 必备；save 用 UPSERT（ON CONFLICT
  account_id）保住代理键不漂移。
- `platform` 列（原 provider→app→platform，ADR-018/ADR-019 两轮术语裁决）；
  `is_active` 用户管理开关（不用 enabled——数据库关键字风险，用户裁决）。
- 聚合事实落全：base_url / device_ref / entitlement_json / deleted_at。

老库自迁移（幂等，纯增量不破坏）：
- v1/v2 形状（id TEXT 主键 + provider/app 列）→ 重建式迁移：Python 侧回填
  （account_key 按规范 id 反推、updated_at=created_at 兜底）→ 旧表让位换 v3。
- v3 形状只补缺列/索引。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from butler_core.accounts.ports import AccountRepository
from butler_core.accounts.domain import Account, Entitlement, Session, SessionKind, SessionLevel

from butler_engine.db.conn import connect

_SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id       TEXT NOT NULL UNIQUE,
    platform         TEXT NOT NULL,
    account_key      TEXT NOT NULL DEFAULT 'main',
    display_name     TEXT NOT NULL,
    base_url         TEXT,
    device_ref       TEXT,
    sessions         TEXT NOT NULL DEFAULT '[]',
    entitlement_json TEXT,
    is_active        INTEGER NOT NULL DEFAULT 1,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    deleted_at       TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_accounts_platform_key
    ON accounts (platform, account_key);
CREATE INDEX IF NOT EXISTS idx_accounts_platform ON accounts (platform);
"""

_COLS = (
    "account_id, platform, account_key, display_name, base_url, device_ref, sessions, "
    "entitlement_json, is_active, created_at, updated_at, deleted_at"
)

# v3 缺列补丁（幂等；v1/v2 走重建不走这里）
_MISSING_COLS: dict[str, str] = {
    "account_key": "account_key TEXT NOT NULL DEFAULT 'main'",
    "base_url": "base_url TEXT",
    "device_ref": "device_ref TEXT",
    "entitlement_json": "entitlement_json TEXT",
    "is_active": "is_active INTEGER NOT NULL DEFAULT 1",
    "updated_at": "updated_at TEXT NOT NULL DEFAULT ''",
    "deleted_at": "deleted_at TEXT",
}

# v1/v2 旧索引名（重建/补索引时一律 DROP）
_LEGACY_INDEXES = ("idx_accounts_provider", "idx_accounts_app", "uq_accounts_app_key")


def _ensure_columns(conn) -> None:
    """老库自迁移（幂等）：v1/v2 → v3 重建；v3 只补缺列/索引。"""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(accounts)")}
    if not cols:
        return  # 表由 _SCHEMA 新建，无需迁移
    if "account_id" not in cols:
        _rebuild_from_legacy(conn, cols)
        return
    for name, ddl in _MISSING_COLS.items():
        if name not in cols:
            conn.execute(f"ALTER TABLE accounts ADD COLUMN {ddl}")
    conn.execute("UPDATE accounts SET updated_at = created_at WHERE updated_at = ''")
    _recreate_indexes(conn)


def _recreate_indexes(conn) -> None:
    for idx in _LEGACY_INDEXES:
        conn.execute(f"DROP INDEX IF EXISTS {idx}")
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_accounts_platform_key"
        " ON accounts (platform, account_key)"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_accounts_platform ON accounts (platform)")


def _rebuild_from_legacy(conn, cols: set[str]) -> None:
    """v1/v2（id TEXT 主键 + provider/app 列）→ v3 重建：行数据零丢失。"""
    platform_col = "app" if "app" in cols else "provider"
    select = ["id", platform_col, "display_name", "sessions", "created_at"]
    for optional in ("base_url", "device_ref", "entitlement_json", "is_active", "updated_at", "deleted_at"):
        select.append(optional if optional in cols else "NULL")
    rows = conn.execute(f"SELECT {', '.join(select)} FROM accounts").fetchall()
    conn.execute("DROP TABLE accounts")
    conn.executescript(_SCHEMA)
    for row in rows:
        legacy_id, platform, display_name, sessions_raw, created_at = row[:5]
        base_url = row[5] if row[5] is not None else ""
        device_ref = row[6]
        entitlement_json = row[7]
        is_active = 1 if row[8] is None else int(row[8])
        updated_at = row[9] if row[9] else created_at
        deleted_at = row[10]
        account_key = "main"
        prefix = f"{platform}:"
        if legacy_id.startswith(prefix) and ":" not in legacy_id[len(prefix):]:
            account_key = legacy_id[len(prefix):]
        conn.execute(
            f"INSERT OR IGNORE INTO accounts ({_COLS}) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                legacy_id, platform, account_key, display_name, base_url,
                device_ref, sessions_raw, entitlement_json, is_active,
                created_at, updated_at, deleted_at,
            ),
        )
    _recreate_indexes(conn)


class SqliteAccountRepository(AccountRepository):
    def __init__(self, db_path: str | Path) -> None:
        self._db = str(db_path)
        with self._connect() as conn, conn:
            conn.executescript(_SCHEMA)
            _ensure_columns(conn)

    def _connect(self):
        return connect(self._db)

    def save(self, account: Account) -> None:
        from butler_core.shared.time import now_utc

        with self._connect() as conn, conn:
            conn.execute(
                f"INSERT INTO accounts ({_COLS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT (account_id) DO UPDATE SET "
                "platform=excluded.platform, account_key=excluded.account_key, "
                "display_name=excluded.display_name, base_url=excluded.base_url, "
                "device_ref=excluded.device_ref, sessions=excluded.sessions, "
                "entitlement_json=excluded.entitlement_json, is_active=excluded.is_active, "
                "updated_at=excluded.updated_at, deleted_at=excluded.deleted_at",
                (
                    account.id,
                    account.platform,
                    account.account_key,
                    account.display_name,
                    account.base_url,
                    account.device_ref,
                    _dump_sessions(account.sessions),
                    _dump_entitlement(account.entitlement),
                    1 if account.is_active else 0,
                    account.created_at.isoformat(),
                    now_utc().isoformat(),
                    account.deleted_at.isoformat() if account.deleted_at else None,
                ),
            )

    def get(self, account_id: str) -> Account | None:
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT {_COLS} FROM accounts WHERE account_id = ?",
                (account_id,),
            ).fetchone()
        return _load(row)

    def list_by_platform(self, platform: str) -> list[Account]:
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT {_COLS} FROM accounts WHERE platform = ? ORDER BY created_at, account_id",
                (platform,),
            ).fetchall()
        return [_load(r) for r in rows]

    def list_all(self) -> list[Account]:
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT {_COLS} FROM accounts ORDER BY created_at, account_id"
            ).fetchall()
        return [_load(r) for r in rows]


def _dump_sessions(sessions: tuple[Session, ...]) -> str:
    return json.dumps(
        [[s.location, s.kind.value, s.level.value] for s in sessions],
        ensure_ascii=False,
    )


def _dump_entitlement(ent: Entitlement | None) -> str | None:
    if ent is None:
        return None
    return json.dumps(
        {"balance": ent.balance, "streak": ent.streak, "last_claim_window": ent.last_claim_window},
        ensure_ascii=False,
    )


def _load_sessions(raw: str, account_id: str) -> tuple[Session, ...]:
    try:
        rows = json.loads(raw or "[]")
    except ValueError:
        return ()  # 坏行如实空（聚合其余字段照常），不炸名册
    sessions = []
    for location, kind, level in rows:
        sessions.append(
            Session(
                account_id=account_id,  # 聚合内归属 = Account.id（行内不重复存）
                location=location,
                kind=SessionKind(kind),
                level=SessionLevel(level),
            )
        )
    return tuple(sessions)


def _load_entitlement(raw: str | None, account_id: str) -> Entitlement | None:
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None  # 坏行如实空，不炸名册（红线 5：不静默造数据）
    return Entitlement(
        account_id=account_id,
        balance=str(data.get("balance", "")),
        streak=int(data.get("streak", 0)),
        last_claim_window=str(data.get("last_claim_window", "")),
    )


def _load(row) -> Account | None:
    if row is None:
        return None
    return Account(
        id=row[0],  # account_id：规范 id {platform}:{account_key}
        platform=row[1],
        account_key=row[2],
        display_name=row[3],
        base_url=row[4] or "",
        device_ref=row[5],
        sessions=_load_sessions(row[6], row[0]),
        entitlement=_load_entitlement(row[7], row[0]),
        is_active=bool(row[8]),
        created_at=datetime.fromisoformat(row[9]),
        deleted_at=datetime.fromisoformat(row[11]) if row[11] else None,
    )
