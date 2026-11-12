"""账号名册适配器（A2-01 §1）：SQLite 单库、与台账/审计同库不同表。

upsert 语义：Account 聚合不可变（identity 冻结），重复 save = 覆盖同内容
（组合根重启幂等）。provider 索引服务调度器按连接器取名册。
"""

from __future__ import annotations

from pathlib import Path

from kabao_core.application.ports import AccountRepository
from kabao_core.domain.account import Account

_SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id            TEXT PRIMARY KEY,
    provider      TEXT NOT NULL,
    display_name  TEXT NOT NULL,
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_accounts_provider ON accounts (provider);
"""


class SqliteAccountRepository(AccountRepository):
    def __init__(self, db_path: str | Path) -> None:
        self._db = str(db_path)
        with self._connect() as conn, conn:
            conn.executescript(_SCHEMA)

    def _connect(self):
        import sqlite3

        return sqlite3.connect(self._db)

    def save(self, account: Account) -> None:
        with self._connect() as conn, conn:
            conn.execute(
                "INSERT OR REPLACE INTO accounts (id, provider, display_name, created_at) "
                "VALUES (?, ?, ?, ?)",
                (
                    account.id,
                    account.provider,
                    account.display_name,
                    account.created_at.isoformat(),
                ),
            )

    def get(self, account_id: str) -> Account | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, provider, display_name, created_at FROM accounts "
                "WHERE id = ?",
                (account_id,),
            ).fetchone()
        return _load(row)

    def list_by_provider(self, provider: str) -> list[Account]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, provider, display_name, created_at FROM accounts "
                "WHERE provider = ? ORDER BY created_at, id",
                (provider,),
            ).fetchall()
        return [_load(r) for r in rows]

    def list_all(self) -> list[Account]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, provider, display_name, created_at FROM accounts "
                "ORDER BY created_at, id"
            ).fetchall()
        return [_load(r) for r in rows]


def _load(row) -> Account | None:
    from datetime import datetime

    if row is None:
        return None
    return Account(
        id=row[0],
        provider=row[1],
        display_name=row[2],
        created_at=datetime.fromisoformat(row[3]),
    )
