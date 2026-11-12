"""健康扫描状态存储（core HealthStateStore 落地）：记录已通知级别，变更才产事件。"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from kabao_core.application.ports import HealthStateStore
from kabao_core.domain.health import HealthLevel
from kabao_core.domain.errors import DomainError

_SCHEMA = """
CREATE TABLE IF NOT EXISTS health_state (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def credential_key(account_id: str, kind: str) -> str:
    return f"cred:{account_id}:{kind}"


def account_key(account_id: str) -> str:
    return f"acct:{account_id}"


class SqliteHealthStateStore(HealthStateStore):
    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)
        with closing(self._connect()) as conn, conn:
            conn.executescript(_SCHEMA)

    def get_credential_notified_level(self, account_id: str, kind: str) -> str | None:
        return self._get(credential_key(account_id, kind))

    def set_credential_notified_level(
        self, account_id: str, kind: str, level: HealthLevel
    ) -> None:
        self._set(credential_key(account_id, kind), level)

    def get_account_level(self, account_id: str) -> HealthLevel | None:
        text = self._get(account_key(account_id))
        return None if text is None else HealthLevel(text)

    def set_account_level(self, account_id: str, level: HealthLevel) -> None:
        self._set(account_key(account_id), level)

    # --- 内部 ---

    def _get(self, key: str) -> str | None:
        with closing(self._connect()) as conn, conn:
            row = conn.execute(
                "SELECT value FROM health_state WHERE key = ?", (key,)
            ).fetchone()
        return None if row is None else row[0]

    def _set(self, key: str, level: HealthLevel) -> None:
        if not isinstance(level, HealthLevel):
            raise DomainError(f"健康级别必须是 HealthLevel，收到 {type(level).__name__}")
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "INSERT INTO health_state (key, value, updated_at)"
                " VALUES (?, ?, datetime('now'))"
                " ON CONFLICT(key) DO UPDATE SET value = excluded.value,"
                " updated_at = excluded.updated_at",
                (key, level.value),
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn
