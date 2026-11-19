"""账号名册适配器（A2-01 §1）：SQLite 单库、与台账/审计同库不同表。

accounts v3（2026-11-17 用户裁决，ADR-019/ADR-020）：
- 每表统一代理键 `id INTEGER PRIMARY KEY AUTOINCREMENT`（DDL 约定见 A4-01 §5）；
  账户规范 id `{platform}:{account_code}` 降级为业务键 `account_id`（UNIQUE）。
- 统一审计列 `created_at / updated_at` 必备；save 用 UPSERT（ON CONFLICT
  account_id）保住代理键不漂移。
- 列名 code 化（ADR-020）：`platform_code`（原 provider→app→platform）/
  `account_code`（原 account_key）/ `account_name`（原 display_name）；
  `is_active` 用户管理开关（不用 enabled——数据库关键字风险）。
- 聚合事实落全：base_url / device_ref / entitlement_json / deleted_at。

老库自迁移（幂等，纯增量不破坏）：
- v1/v2 形状（id TEXT 主键 + provider/app 列）→ 重建式迁移：Python 侧回填
  （account_code 按规范 id 反推、updated_at=created_at 兜底）→ 旧表让位换 v3。
- v3 早期形状（列名 platform/account_key/display_name）→ RENAME COLUMN 一轮改齐。
- v3 现行形状只补缺列/索引。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from butler_core.accounts.ports import AccountRepository
from butler_core.accounts.domain import Account, Entitlement, Session, SessionKind, SessionLevel

from butler_engine.db.conn import connect

_SCHEMA = """
CREATE TABLE IF NOT EXISTS acc_account (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id       TEXT NOT NULL UNIQUE,
    platform_code    TEXT NOT NULL,
    account_code     TEXT NOT NULL DEFAULT 'main',
    account_name     TEXT NOT NULL,
    alias            TEXT NOT NULL DEFAULT '',
    base_url         TEXT,
    device_ref       TEXT,
    sessions         TEXT NOT NULL DEFAULT '[]',
    entitlement_json TEXT,
    is_active        INTEGER NOT NULL DEFAULT 1,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    deleted_at       TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_acc_account_platform_code_key
    ON acc_account (platform_code, account_code);
CREATE INDEX IF NOT EXISTS idx_acc_account_platform_code ON acc_account (platform_code);
"""

_COLS = (
    "account_id, platform_code, account_code, account_name, alias, base_url, device_ref, sessions, "
    "entitlement_json, is_active, created_at, updated_at, deleted_at"
)

# v3 早期列名 → 现行列名（RENAME 一轮改齐；仅认旧名存在且新名缺失时执行）
_RENAME_COLS: tuple[tuple[str, str], ...] = (
    ("platform", "platform_code"),
    ("account_key", "account_code"),
    ("display_name", "account_name"),
)

# 现行形状缺列补丁（幂等；v1/v2 走重建不走这里）
_MISSING_COLS: dict[str, str] = {
    "account_code": "account_code TEXT NOT NULL DEFAULT 'main'",
    "base_url": "base_url TEXT",
    "device_ref": "device_ref TEXT",
    "entitlement_json": "entitlement_json TEXT",
    "is_active": "is_active INTEGER NOT NULL DEFAULT 1",
    "alias": "alias TEXT NOT NULL DEFAULT ''",
    "updated_at": "updated_at TEXT NOT NULL DEFAULT ''",
    "deleted_at": "deleted_at TEXT",
}

# 历史/旧索引名（重建/补索引时一律 DROP）
_LEGACY_INDEXES = (
    "idx_accounts_provider", "idx_accounts_app", "uq_accounts_app_key",
    "uq_accounts_platform_key", "idx_accounts_platform",
    "uq_accounts_platform_code_key", "idx_accounts_platform_code",
)


def _ensure_columns(conn) -> None:
    """老库自迁移（幂等）：v1/v2 重建、v3 早期列名 RENAME、现行只补缺列/索引。"""
    # 表名迁移（ADR-021）：老表名 accounts → acc_account（RENAME 幂等，索引随表走）
    has_old = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='accounts'"
    ).fetchone()
    if has_old:
        conn.execute("ALTER TABLE accounts RENAME TO acc_account")
    cols = {row[1] for row in conn.execute("PRAGMA table_info(acc_account)")}
    if not cols:
        return  # 表由 _SCHEMA 新建，无需迁移
    if "account_id" not in cols:
        _rebuild_from_legacy(conn, cols)
        return
    for old, new in _RENAME_COLS:
        if old in cols and new not in cols:
            conn.execute(f"ALTER TABLE acc_account RENAME COLUMN {old} TO {new}")
            cols.discard(old); cols.add(new)
    for name, ddl in _MISSING_COLS.items():
        if name not in cols:
            conn.execute(f"ALTER TABLE acc_account ADD COLUMN {ddl}")
    conn.execute("UPDATE acc_account SET updated_at = created_at WHERE updated_at = ''")
    _recreate_indexes(conn)


def _recreate_indexes(conn) -> None:
    for idx in _LEGACY_INDEXES:
        conn.execute(f"DROP INDEX IF EXISTS {idx}")
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_acc_account_platform_code_key"
        " ON acc_account (platform_code, account_code)"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_acc_account_platform_code ON acc_account (platform_code)")


def _rebuild_from_legacy(conn, cols: set[str]) -> None:
    """v1/v2（id TEXT 主键 + provider/app 列）→ v3 重建：行数据零丢失。"""
    platform_col = "app" if "app" in cols else "provider"
    name_col = "account_name" if "account_name" in cols else "display_name"
    select = ["id", platform_col, name_col, "sessions", "created_at"]
    for optional in ("base_url", "device_ref", "entitlement_json", "is_active", "updated_at", "deleted_at"):
        select.append(optional if optional in cols else "NULL")
    rows = conn.execute(f"SELECT {', '.join(select)} FROM acc_account").fetchall()
    conn.execute("DROP TABLE acc_account")
    conn.executescript(_SCHEMA)
    for row in rows:
        legacy_id, platform_code, account_name, sessions_raw, created_at = row[:5]
        base_url = row[5] if row[5] is not None else ""
        device_ref = row[6]
        entitlement_json = row[7]
        is_active = 1 if row[8] is None else int(row[8])
        updated_at = row[9] if row[9] else created_at
        deleted_at = row[10]
        account_code = "main"
        prefix = f"{platform_code}:"
        if legacy_id.startswith(prefix) and ":" not in legacy_id[len(prefix):]:
            account_code = legacy_id[len(prefix):]
        conn.execute(
            f"INSERT OR IGNORE INTO acc_account ({_COLS}) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                legacy_id, platform_code, account_code, account_name, "", base_url,
                device_ref, sessions_raw, entitlement_json, is_active,
                created_at, updated_at, deleted_at,
            ),
        )
    _recreate_indexes(conn)


class SqliteAccountRepository(AccountRepository):
    def __init__(self, db_path: str | Path) -> None:
        self._db = str(db_path)
        with self._connect() as conn, conn:
            # 迁移先行、建表在后：老库先 RENAME accounts → acc_account，
            # 再 executescript(_SCHEMA)——顺序反了会先建空 acc_account 撞名（真库首启修复）
            _ensure_columns(conn)
            conn.executescript(_SCHEMA)

    def _connect(self):
        return connect(self._db)

    def save(self, account: Account) -> None:
        from butler_core.shared.time import now_utc

        with self._connect() as conn, conn:
            conn.execute(
                f"INSERT INTO acc_account ({_COLS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT (account_id) DO UPDATE SET "
                "platform_code=excluded.platform_code, account_code=excluded.account_code, "
                "account_name=excluded.account_name, alias=excluded.alias, base_url=excluded.base_url, "
                "device_ref=excluded.device_ref, sessions=excluded.sessions, "
                "entitlement_json=excluded.entitlement_json, is_active=excluded.is_active, "
                "updated_at=excluded.updated_at, deleted_at=excluded.deleted_at",
                (
                    account.id,
                    account.platform_code,
                    account.account_code,
                    account.account_name,
                    account.alias,
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
                f"SELECT {_COLS} FROM acc_account WHERE account_id = ?",
                (account_id,),
            ).fetchone()
        return _load(row)

    def list_by_platform(self, platform_code: str) -> list[Account]:
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT {_COLS} FROM acc_account WHERE platform_code = ? ORDER BY created_at, account_id",
                (platform_code,),
            ).fetchall()
        return [_load(r) for r in rows]

    def list_all(self) -> list[Account]:
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT {_COLS} FROM acc_account ORDER BY created_at, account_id"
            ).fetchall()
        return [_load(r) for r in rows]

    def remove(self, account_id: str) -> bool:
        """删除账户行（2026-11-19）：只删 acc_account，凭据由用例先清。"""
        with self._connect() as conn, conn:
            cur = conn.execute("DELETE FROM acc_account WHERE account_id = ?", (account_id,))
            return cur.rowcount > 0


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
        id=row[0],  # account_id：规范 id {platform}:{account_code}
        platform_code=row[1],
        account_code=row[2],
        account_name=row[3],
        alias=row[4] or "",
        base_url=row[5] or "",
        device_ref=row[6],
        sessions=_load_sessions(row[7], row[0]),
        entitlement=_load_entitlement(row[8], row[0]),
        is_active=bool(row[9]),
        created_at=datetime.fromisoformat(row[10]),
        deleted_at=datetime.fromisoformat(row[12]) if row[12] else None,
    )
