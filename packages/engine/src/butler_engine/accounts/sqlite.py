"""账号名册适配器（A2-01 §1）：SQLite 单库、与台账/审计同库不同表。

upsert 语义：Account 聚合 identity 冻结（id = {app}:{account_key}），重复
save = 覆盖同内容（组合根重启幂等）。app 索引服务调度器按连接器取名册。

accounts v2（2026-11-17 用户裁决）：显式 account_key 列 + UNIQUE(app, account_key)
兜底不变量；base_url/device_ref/enabled/entitlement_json/deleted_at 把聚合事实
落全；updated_at 统一审计列（id/created_at/updated_at 所有表必备——本表先行，
其余域分批跟进）。

老库自迁移（幂等，纯增量不破坏）：app→app 改名（RENAME COLUMN）、
缺列 ALTER、account_key 按 id 反推回填、updated_at 回填 created_at、
旧索引 idx_accounts_provider 更名语义后由新索引替代（旧的 DROP）。
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
    id               TEXT PRIMARY KEY,
    app              TEXT NOT NULL,
    account_key      TEXT NOT NULL DEFAULT 'main',
    display_name     TEXT NOT NULL,
    base_url         TEXT,
    device_ref       TEXT,
    sessions         TEXT NOT NULL DEFAULT '[]',
    entitlement_json TEXT,
    enabled          INTEGER NOT NULL DEFAULT 1,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    deleted_at       TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_accounts_app_key ON accounts (app, account_key);
CREATE INDEX IF NOT EXISTS idx_accounts_app ON accounts (app);
"""

_COLS = (
    "id, app, account_key, display_name, base_url, device_ref, sessions, "
    "entitlement_json, enabled, created_at, updated_at, deleted_at"
)

# 老库缺列时的纯增量补丁（列名 → ALTER 片段）；app→app 走 RENAME 单独处理
_MISSING_COLS: dict[str, str] = {
    "account_key": "account_key TEXT NOT NULL DEFAULT 'main'",
    "base_url": "base_url TEXT",
    "device_ref": "device_ref TEXT",
    "entitlement_json": "entitlement_json TEXT",
    "enabled": "enabled INTEGER NOT NULL DEFAULT 1",
    "updated_at": "updated_at TEXT NOT NULL DEFAULT ''",
    "deleted_at": "deleted_at TEXT",
}


def _ensure_columns(conn) -> None:
    """老库自迁移（幂等）：改名 / 补列 / 回填 / 换索引。"""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(accounts)")}
    if not cols:
        return  # 表由 _SCHEMA 新建，无需迁移
    if "app" in cols and "app" not in cols:
        conn.execute("ALTER TABLE accounts RENAME COLUMN app TO app")
        cols = {row[1] for row in conn.execute("PRAGMA table_info(accounts)")}
    for name, ddl in _MISSING_COLS.items():
        if name not in cols:
            conn.execute(f"ALTER TABLE accounts ADD COLUMN {ddl}")
    # account_key 回填：规范 id = {app}:{account_key}，反推账号序（非 main 多账号防丢）
    conn.execute(
        "UPDATE accounts SET account_key = substr(id, length(app) + 2) "
        "WHERE account_key = 'main' AND id LIKE (app || ':%') "
        "AND substr(id, length(app) + 2) NOT LIKE '%:%'"
    )
    # updated_at 回填：老数据无更新时间，用创建时间兜底（审计列不留空）
    conn.execute("UPDATE accounts SET updated_at = created_at WHERE updated_at = ''")
    conn.execute("DROP INDEX IF EXISTS idx_accounts_provider")
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_accounts_app_key ON accounts (app, account_key)"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_accounts_app ON accounts (app)")


class SqliteAccountRepository(AccountRepository):
    def __init__(self, db_path: str | Path) -> None:
        self._db = str(db_path)
        with self._connect() as conn, conn:
            conn.executescript(_SCHEMA)
            _ensure_columns(conn)

    def _connect(self):
        return connect(self._db)

    def save(self, account: Account) -> None:
        with self._connect() as conn, conn:
            conn.execute(
                f"INSERT OR REPLACE INTO accounts ({_COLS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    account.id,
                    account.app,
                    account.account_key,
                    account.display_name,
                    account.base_url,
                    account.device_ref,
                    _dump_sessions(account.sessions),
                    _dump_entitlement(account.entitlement),
                    1 if account.enabled else 0,
                    account.created_at.isoformat(),
                    _now_iso(),
                    account.deleted_at.isoformat() if account.deleted_at else None,
                ),
            )

    def get(self, account_id: str) -> Account | None:
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT {_COLS} FROM accounts WHERE id = ?",
                (account_id,),
            ).fetchone()
        return _load(row)

    def list_by_app(self, app: str) -> list[Account]:
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT {_COLS} FROM accounts WHERE app = ? ORDER BY created_at, id",
                (app,),
            ).fetchall()
        return [_load(r) for r in rows]

    def list_all(self) -> list[Account]:
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT {_COLS} FROM accounts ORDER BY created_at, id"
            ).fetchall()
        return [_load(r) for r in rows]


def _now_iso() -> str:
    from butler_core.shared.time import now_utc

    return now_utc().isoformat()


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
        id=row[0],
        app=row[1],
        account_key=row[2],
        display_name=row[3],
        base_url=row[4] or "",
        device_ref=row[5],
        sessions=_load_sessions(row[6], row[0]),
        entitlement=_load_entitlement(row[7], row[0]),
        enabled=bool(row[8]),
        created_at=datetime.fromisoformat(row[9]),
        deleted_at=datetime.fromisoformat(row[11]) if row[11] else None,
    )
