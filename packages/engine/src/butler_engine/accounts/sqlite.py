"""账号名册适配器（A2-01 §1）：SQLite 单库、与台账/审计同库不同表。

upsert 语义：Account 聚合不可变（identity 冻结），重复 save = 覆盖同内容
（组合根重启幂等）。provider 索引服务调度器按连接器取名册。
sessions 列（R5-S1）：JSON 数组 [location, kind, level]，随聚合整体替换
（会话清单是小集合，无独立表必要）；老库自迁移 = 缺列 ALTER 兜底（纯增量
默认 '[]'，无破坏性变更）。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from butler_core.accounts.ports import AccountRepository
from butler_core.accounts.domain import Account, Session, SessionKind, SessionLevel

from butler_engine.db.conn import connect

_SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id            TEXT PRIMARY KEY,
    provider      TEXT NOT NULL,
    display_name  TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    sessions      TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS idx_accounts_provider ON accounts (provider);
"""

_COLS = "id, provider, display_name, created_at, sessions"


def _ensure_columns(conn) -> None:
    """老库自迁移：accounts 表缺 sessions 列则补（幂等；纯增量默认值）。"""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(accounts)")}
    if cols and "sessions" not in cols:
        conn.execute("ALTER TABLE accounts ADD COLUMN sessions TEXT NOT NULL DEFAULT '[]'")


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
                f"INSERT OR REPLACE INTO accounts ({_COLS}) VALUES (?, ?, ?, ?, ?)",
                (
                    account.id,
                    account.provider,
                    account.display_name,
                    account.created_at.isoformat(),
                    _dump_sessions(account.sessions),
                ),
            )

    def get(self, account_id: str) -> Account | None:
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT {_COLS} FROM accounts WHERE id = ?",
                (account_id,),
            ).fetchone()
        return _load(row)

    def list_by_provider(self, provider: str) -> list[Account]:
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT {_COLS} FROM accounts WHERE provider = ? ORDER BY created_at, id",
                (provider,),
            ).fetchall()
        return [_load(r) for r in rows]

    def list_all(self) -> list[Account]:
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT {_COLS} FROM accounts ORDER BY created_at, id"
            ).fetchall()
        return [_load(r) for r in rows]


def _dump_sessions(sessions: tuple[Session, ...]) -> str:
    return json.dumps(
        [[s.location, s.kind.value, s.level.value] for s in sessions],
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


def _load(row) -> Account | None:
    if row is None:
        return None
    return Account(
        id=row[0],
        provider=row[1],
        display_name=row[2],
        created_at=datetime.fromisoformat(row[3]),
        sessions=_load_sessions(row[4], row[0]),
    )
