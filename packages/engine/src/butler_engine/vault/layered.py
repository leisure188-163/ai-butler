"""分层凭据保险库（A4-01 §1 落地）：SQLite 元数据 + 秘密后端调度。

- 秘密只在后端（Keychain / 凭据管理器 / 内存）；SQLite 只存引用与状态
  （有效期 / 版本 / 层名）——库里永远没有明文， credential 列名也不含秘密含义
- rotate：旧值整体挪到 #版本 引用（后端仍可找到，可审计），新值写主引用；
  版本递增记录在 vault_history
- 存/取/轮换同步写审计（A4-01 §4 触发点：凭据存取/轮换）——不走事件总线：
  审计是 L3 反代上线的安全底线，必须同步落账，不依赖异步分发存活
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from butler_core.accounts.ports import VaultPort
from butler_core.accounts.domain import CredentialHealth, Secret, vault_ref

from butler_engine.audit.sqlite import SqliteAuditLog
from butler_engine.db.conn import connect
from butler_engine.vault.backends import SecretBackend
from butler_engine.vault.errors import (
    VaultCredentialMissing,
    VaultCredentialRevoked,
    VaultError,
    VaultLayerUnavailable,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS vault_items (
    account_id TEXT NOT NULL,
    kind       TEXT NOT NULL,
    backend    TEXT NOT NULL,
    expires_at TEXT,
    created_at TEXT NOT NULL,
    rotated_at TEXT,
    revoked_at TEXT,
    revoked_reason TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (account_id, kind)
);
CREATE TABLE IF NOT EXISTS vault_history (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    archived_ref TEXT NOT NULL,
    rotated_at TEXT NOT NULL
);
"""

_COLUMNS = (
    "account_id, kind, backend, expires_at, created_at, rotated_at,"
    " revoked_at, revoked_reason"
)


class LayeredVault(VaultPort):
    """A4-01 §1 端口的适配器实现。backend 映射自定义，default_backend 兜底层。

    ref 规范（core 单源 vault_ref）：当前版本 `{account}:{kind}`，
    轮换归档 `{account}:{kind}#{seq}`——后端侧条目永不覆盖历史。
    """

    def __init__(
        self,
        db_path: str | Path,
        backends: dict[str, SecretBackend],
        *,
        default_backend: str,
        audit: SqliteAuditLog,
    ) -> None:
        if default_backend not in backends:
            raise VaultLayerUnavailable(f"默认后端 {default_backend!r} 未注册")
        self._backends = dict(backends)
        self._default = default_backend
        self._db_path = str(db_path)
        self._audit = audit
        with closing(self._connect()) as conn, conn:
            conn.executescript(_SCHEMA)
            _ensure_columns(conn)

    # --- VaultPort ---

    def store(
        self,
        account_id: str,
        kind: str,
        secret: Secret,
        *,
        expires_at: datetime | None = None,
        backend: str | None = None,
    ) -> None:
        """入库。backend 覆写参数留给测试/特殊装配用，业务路径用默认层。"""
        ref = vault_ref(account_id, kind)
        backend_name = backend if backend is not None else self._default
        self._backend(backend_name).put(ref, secret.expose())
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "INSERT INTO vault_items"
                " (account_id, kind, backend, expires_at, created_at, rotated_at, revoked_at, revoked_reason)"
                " VALUES (?, ?, ?, ?, datetime('now'), datetime('now'), NULL, '')"
                " ON CONFLICT(account_id, kind) DO UPDATE SET"
                " backend = excluded.backend, expires_at = excluded.expires_at,"
                " rotated_at = datetime('now'),"
                " revoked_at = NULL, revoked_reason = ''",
                (account_id, kind, backend_name, _iso(expires_at)),
            )
        self._audit.record(
            actor="vault", action="vault.store", outcome="ok",
            account_id=account_id, credential_ref=ref,
        )

    def load(self, account_id: str, kinds: list[str]) -> list[Secret]:
        """只解密申报的最小集合（最小授权，A2-02 §5）；缺哪个报哪个，不静默。"""
        missing: list[str] = []
        secrets: list[Secret] = []
        for kind in kinds:
            if kind.strip() == "":
                raise VaultError("load 的 kinds 不能含空白项")
            ref = vault_ref(account_id, kind)
            row = self._row(account_id, kind)
            if row is None:
                missing.append(kind)
                self._audit.record(
                    actor="vault", action="vault.load", outcome=f"denied:missing:{kind}",
                    account_id=account_id, credential_ref=ref,
                )
                continue
            backend, _expires, revoked_at = row
            if revoked_at is not None:
                self._audit.record(
                    actor="vault", action="vault.load", outcome=f"denied:revoked:{kind}",
                    account_id=account_id, credential_ref=ref,
                )
                raise VaultCredentialRevoked(
                    f"账号 {account_id} 的 kind={kind} 凭据已被撤销——"
                    "本地副本已清空，等待重新停靠（客户端会话不受影响）"
                )
            secrets.append(Secret(self._backend(backend).get(ref)))
            self._audit.record(
                actor="vault", action="vault.load", outcome="ok",
                account_id=account_id, credential_ref=ref,
            )
        if missing:
            raise VaultCredentialMissing(
                f"账号 {account_id} 缺凭据 kind={missing}——显式报错，不静默给空集（红线 5）"
            )
        return secrets

    def rotate(
        self,
        account_id: str,
        kind: str,
        new_secret: Secret,
        *,
        expires_at: datetime | None = None,
    ) -> None:
        """换新 + 旧值进历史：旧值移到 #seq 引用（可审计可找回），新值写主引用。

        中断窗口如实登记（2026-11-16）：归档成功后、新值写入前进程中断 →
        主引用悬空，load 将显式报缺（不静默兜底）；旧值仍在 #seq 归档可手工
        找回。单机单用户 rotate 罕见（换 key），接受此窗口，不做跨后端事务。
        """
        ref = vault_ref(account_id, kind)
        row = self._row(account_id, kind)
        if row is None:
            raise VaultCredentialMissing(
                f"账号 {account_id} 无 kind={kind} 凭据，rotate 拒绝（应先 store）"
            )
        backend_name, _, _ = row
        backend = self._backend(backend_name)

        with closing(self._connect()) as conn, conn:
            seq = conn.execute(
                "SELECT COALESCE(MAX(seq), 0) + 1 FROM vault_history"
            ).fetchone()[0]
            archived_ref = f"{ref}#{seq}"
        backend.put(archived_ref, backend.get(ref))  # 旧值先归档——失败即停，不换新
        backend.delete(ref)
        backend.put(ref, new_secret.expose())

        with closing(self._connect()) as conn, conn:
            conn.execute(
                "INSERT INTO vault_history (account_id, kind, archived_ref, rotated_at)"
                " VALUES (?, ?, ?, datetime('now'))",
                (account_id, kind, archived_ref),
            )
            conn.execute(
                "UPDATE vault_items SET expires_at = ?, rotated_at = datetime('now')"
                " WHERE account_id = ? AND kind = ?",
                (_iso(expires_at), account_id, kind),
            )
        self._audit.record(
            actor="vault", action="vault.rotate", outcome="ok",
            account_id=account_id, credential_ref=ref,
        )

    def revoke(self, account_id: str, *, reason: str) -> int:
        """撤销该账户全部本地副本：旧值进 #seq 历史、删主引用、行标记 revoked。

        幂等：已撤销的行直接跳过。后端主引用已缺失也继续标记（证据不因
        二次清理失败而丢）；只有归档写入失败才整体抛出，不假称撤销成功。
        """
        rows = self._items(account_id)
        revoked = 0
        now_iso = datetime.now(timezone.utc).isoformat()
        for kind, backend_name, revoked_at in rows:
            if revoked_at is not None:
                continue
            ref = vault_ref(account_id, kind)
            backend = self._backend(backend_name)
            with closing(self._connect()) as conn, conn:
                seq = conn.execute(
                    "SELECT COALESCE(MAX(seq), 0) + 1 FROM vault_history"
                ).fetchone()[0]
                archived_ref = f"{ref}#{seq}"
            try:
                backend.put(archived_ref, backend.get(ref))  # 先归档，失败即停
                backend.delete(ref)
            except VaultCredentialMissing:
                # 主引用已不在：仍标记撤销（幂等清理，不掩盖已撤销事实）
                pass
            with closing(self._connect()) as conn, conn:
                conn.execute(
                    "INSERT INTO vault_history (account_id, kind, archived_ref, rotated_at)"
                    " VALUES (?, ?, ?, datetime('now'))",
                    (account_id, kind, archived_ref),
                )
                conn.execute(
                    "UPDATE vault_items SET revoked_at = ?, revoked_reason = ?"
                    " WHERE account_id = ? AND kind = ?",
                    (now_iso, reason, account_id, kind),
                )
            revoked += 1
        if revoked:
            self._audit.record(
                actor="vault", action="vault.revoke", outcome=f"ok:revoked={revoked}",
                account_id=account_id, credential_ref=f"{account_id}:*",
            )
        return revoked

    def health(self) -> list[CredentialHealth]:
        with closing(self._connect()) as conn, conn:
            rows = conn.execute(
                f"SELECT {_COLUMNS} FROM vault_items ORDER BY account_id, kind"
            ).fetchall()
        return [
            CredentialHealth.build(
                account_id=account_id,
                kind=kind,
                expires_at=_parse(expires_at),
                revoked_at=_parse_utc(revoked_at),
                revoked_reason=revoked_reason or "",
                stored_at=_parse_utc(rotated_at or created_at),
            )
            for account_id, kind, _backend, expires_at, created_at, rotated_at, revoked_at, revoked_reason in rows
        ]

    # --- engine 内部能力 ---

    def history(self, account_id: str, kind: str) -> list[tuple[str, str]]:
        """轮换历史（引擎侧排障用）：[(archived_ref, rotated_at)]，新→旧。"""
        with closing(self._connect()) as conn, conn:
            rows = conn.execute(
                "SELECT archived_ref, rotated_at FROM vault_history"
                " WHERE account_id = ? AND kind = ? ORDER BY seq DESC",
                (account_id, kind),
            ).fetchall()
        return [(ref, ts) for ref, ts in rows]

    # --- 内部 ---

    def _backend(self, name: str) -> SecretBackend:
        try:
            return self._backends[name]
        except KeyError as e:
            raise VaultLayerUnavailable(
                f"存储层 {name!r} 不在本装配中（可用：{sorted(self._backends)}）"
            ) from e

    def _row(self, account_id: str, kind: str) -> tuple[str, datetime | None, str | None] | None:
        with closing(self._connect()) as conn, conn:
            row = conn.execute(
                "SELECT backend, expires_at, revoked_at FROM vault_items"
                " WHERE account_id = ? AND kind = ?",
                (account_id, kind),
            ).fetchone()
        if row is None:
            return None
        backend, expires_at, revoked_at = row
        return backend, _parse(expires_at), revoked_at

    def _items(self, account_id: str) -> list[tuple[str, str, str | None]]:
        """账户下全部条目：(kind, backend, revoked_at)，新→旧按 kind 稳定排序。"""
        with closing(self._connect()) as conn, conn:
            rows = conn.execute(
                "SELECT kind, backend, revoked_at FROM vault_items"
                " WHERE account_id = ? ORDER BY kind",
                (account_id,),
            ).fetchall()
        return [(kind, backend, revoked_at) for kind, backend, revoked_at in rows]

    def _connect(self) -> sqlite3.Connection:
        return connect(self._db_path)


def _ensure_columns(conn: sqlite3.Connection) -> None:
    """老库自迁移：vault_items 缺撤销列则补（纯增量，默认未撤销）。"""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(vault_items)")}
    if "revoked_at" not in cols:
        conn.execute("ALTER TABLE vault_items ADD COLUMN revoked_at TEXT")
    if "revoked_reason" not in cols:
        conn.execute(
            "ALTER TABLE vault_items ADD COLUMN revoked_reason TEXT NOT NULL DEFAULT ''"
        )


def _iso(dt: datetime | None) -> str | None:
    return None if dt is None else dt.isoformat()


def _parse(text: str | None) -> datetime | None:
    return None if text in (None, "") else datetime.fromisoformat(text)


def _parse_utc(text: str | None) -> datetime | None:
    """撤销时间统一带时区：老行（SQLite datetime('now')）无时区按 UTC 补齐。"""
    parsed = _parse(text)
    if parsed is not None and parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed
