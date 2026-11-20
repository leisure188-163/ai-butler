"""分层凭据保险库（A4-01 §1 落地）：SQLite 元数据 + 秘密后端调度。

- 秘密只在后端（Keychain / 凭据管理器 / 内存）；SQLite 只存引用与状态
  （有效期 / 版本 / 层名）——库里永远没有明文， credential 列名也不含秘密含义
- 槽位（ADR-033）：同账户同 kind 可有多份凭据；`default` 槽保持旧引用
  `{account}:{kind}`（存量秘密零迁移），非默认槽用 `{account}:{kind}@{slot}`
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
CREATE TABLE IF NOT EXISTS vault_item (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id     TEXT NOT NULL,
    kind           TEXT NOT NULL,
    slot           TEXT NOT NULL DEFAULT 'default',
    label          TEXT NOT NULL DEFAULT '',
    backend        TEXT NOT NULL,
    expires_at     TEXT,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL,
    rotated_at     TEXT,
    revoked_at     TEXT,
    revoked_reason TEXT NOT NULL DEFAULT '',
    UNIQUE (account_id, kind, slot)
);
CREATE TABLE IF NOT EXISTS vault_history (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    slot TEXT NOT NULL DEFAULT 'default',
    archived_ref TEXT NOT NULL,
    rotated_at TEXT NOT NULL
);
"""

_COLUMNS = (
    "account_id, kind, slot, label, backend, expires_at, created_at, updated_at,"
    " rotated_at, revoked_at, revoked_reason"
)


class LayeredVault(VaultPort):
    """A4-01 §1 端口的适配器实现。backend 映射自定义，default_backend 兜底层。

    ref 规范（core 单源 vault_ref）：默认槽 `{account}:{kind}`，非默认槽
    `{account}:{kind}@{slot}`；轮换归档再追加 `#{seq}`——后端侧条目永不覆盖历史。
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
            # 表名迁移（ADR-021 域前缀纪律）：老表 RENAME 幂等，旧索引随行清理
            if conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='vault_items'"
            ).fetchone():
                conn.execute("ALTER TABLE vault_items RENAME TO vault_item")
            conn.executescript(_SCHEMA)
            _ensure_schema(conn)

    # --- VaultPort ---

    def store(
        self,
        account_id: str,
        kind: str,
        secret: Secret,
        *,
        slot: str = "default",
        label: str = "",
        expires_at: datetime | None = None,
        backend: str | None = None,
    ) -> None:
        """入库。backend 覆写参数留给测试/特殊装配用，业务路径用默认层。"""
        ref = vault_ref(account_id, kind, slot)
        backend_name = backend if backend is not None else self._default
        self._backend(backend_name).put(ref, secret.expose())
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "INSERT INTO vault_item"
                " (account_id, kind, slot, label, backend, expires_at,"
                "  created_at, updated_at, rotated_at, revoked_at, revoked_reason)"
                " VALUES (?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'),"
                "         datetime('now'), NULL, '')"
                " ON CONFLICT(account_id, kind, slot) DO UPDATE SET"
                " label = excluded.label, backend = excluded.backend,"
                " expires_at = excluded.expires_at, updated_at = datetime('now'),"
                " rotated_at = datetime('now'),"
                " revoked_at = NULL, revoked_reason = ''",
                (account_id, kind, slot, label[:40], backend_name, _iso(expires_at)),
            )
        self._audit.record(
            actor="vault", action="vault.store", outcome="ok",
            account_id=account_id, credential_ref=ref,
        )

    def load(
        self, account_id: str, kinds: list[str], *, slot: str = "default"
    ) -> list[Secret]:
        """只解密申报的最小集合（最小授权，A2-02 §5）；缺哪个报哪个，不静默。

        槽位（ADR-033）：默认只取 default 槽；调用方要备用 key 必须显式传 slot。
        """
        missing: list[str] = []
        secrets: list[Secret] = []
        for kind in kinds:
            if kind.strip() == "":
                raise VaultError("load 的 kinds 不能含空白项")
            ref = vault_ref(account_id, kind, slot)
            row = self._row(account_id, kind, slot)
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
                    f"账号 {account_id} 的 kind={kind} slot={slot} 凭据已被撤销——"
                    "本地副本已清空，等待重新停靠（客户端会话不受影响）"
                )
            secrets.append(Secret(self._backend(backend).get(ref)))
            self._audit.record(
                actor="vault", action="vault.load", outcome="ok",
                account_id=account_id, credential_ref=ref,
            )
        if missing:
            raise VaultCredentialMissing(
                f"账号 {account_id} 缺凭据 kind={missing} slot={slot}——"
                "显式报错，不静默给空集（红线 5）"
            )
        return secrets

    def rotate(
        self,
        account_id: str,
        kind: str,
        new_secret: Secret,
        *,
        slot: str = "default",
        expires_at: datetime | None = None,
    ) -> None:
        """换新 + 旧值进历史：旧值移到 #seq 引用（可审计可找回），新值写主引用。

        中断窗口如实登记（2026-11-16）：归档成功后、新值写入前进程中断 →
        主引用悬空，load 将显式报缺（不静默兜底）；旧值仍在 #seq 归档可手工
        找回。单机单用户 rotate 罕见（换 key），接受此窗口，不做跨后端事务。
        """
        ref = vault_ref(account_id, kind, slot)
        row = self._row(account_id, kind, slot)
        if row is None:
            raise VaultCredentialMissing(
                f"账号 {account_id} 无 kind={kind} slot={slot} 凭据，rotate 拒绝（应先 store）"
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
                "INSERT INTO vault_history (account_id, kind, slot, archived_ref, rotated_at)"
                " VALUES (?, ?, ?, ?, datetime('now'))",
                (account_id, kind, slot, archived_ref),
            )
            conn.execute(
                "UPDATE vault_item SET expires_at = ?, rotated_at = datetime('now'),"
                " updated_at = datetime('now')"
                " WHERE account_id = ? AND kind = ? AND slot = ?",
                (_iso(expires_at), account_id, kind, slot),
            )
        self._audit.record(
            actor="vault", action="vault.rotate", outcome="ok",
            account_id=account_id, credential_ref=ref,
        )

    def revoke(self, account_id: str, *, reason: str) -> int:
        """撤销该账户全部本地副本（所有槽位）：旧值进 #seq 历史、删主引用、标记 revoked。

        幂等：已撤销的行直接跳过。后端主引用已缺失也继续标记（证据不因
        二次清理失败而丢）；只有归档写入失败才整体抛出，不假称撤销成功。
        """
        rows = self._items(account_id)
        revoked = 0
        now_iso = datetime.now(timezone.utc).isoformat()
        for kind, slot, backend_name, revoked_at in rows:
            if revoked_at is not None:
                continue
            self._revoke_one(account_id, kind, slot, backend_name, reason, now_iso)
            revoked += 1
        if revoked:
            self._audit.record(
                actor="vault", action="vault.revoke", outcome=f"ok:revoked={revoked}",
                account_id=account_id, credential_ref=f"{account_id}:*",
            )
        return revoked

    def revoke_slot(self, account_id: str, kind: str, slot: str, *, reason: str) -> bool:
        """撤销单个槽位（ADR-033）：不存在或已撤销 = False（幂等）。"""
        row = self._row(account_id, kind, slot)
        if row is None:
            return False
        backend_name, _, revoked_at = row
        if revoked_at is not None:
            return False
        self._revoke_one(
            account_id, kind, slot, backend_name, reason,
            datetime.now(timezone.utc).isoformat(),
        )
        self._audit.record(
            actor="vault", action="vault.revoke_slot", outcome="ok",
            account_id=account_id, credential_ref=vault_ref(account_id, kind, slot),
        )
        return True

    def purge(self, account_id: str) -> int:
        """彻底清除账户凭据（2026-11-19 删除账户）：主引用、历史归档、DB 行全删。

        不留 revoked 行、不留 history——账户都不存在了，任何残留都是无主脏数据。
        后端秘密已缺失按已清理跳过（幂等）；返回清掉的条目数。
        """
        items = self._items(account_id)
        backend_by_slot = {(kind, slot): backend_name for kind, slot, backend_name, _ in items}
        for kind, slot, backend_name, _ in items:
            ref = vault_ref(account_id, kind, slot)
            try:
                self._backend(backend_name).delete(ref)
            except VaultCredentialMissing:
                pass
        with closing(self._connect()) as conn, conn:
            history = conn.execute(
                "SELECT kind, slot, archived_ref FROM vault_history WHERE account_id = ?",
                (account_id,),
            ).fetchall()
        for kind, slot, archived_ref in history:
            backend_name = backend_by_slot.get((kind, slot), self._default)
            try:
                self._backend(backend_name).delete(archived_ref)
            except VaultCredentialMissing:
                pass
        with closing(self._connect()) as conn, conn:
            conn.execute("DELETE FROM vault_item WHERE account_id = ?", (account_id,))
            conn.execute("DELETE FROM vault_history WHERE account_id = ?", (account_id,))
        if items:
            self._audit.record(
                actor="vault", action="vault.purge", outcome=f"ok:purged={len(items)}",
                account_id=account_id, credential_ref=f"{account_id}:*",
            )
        return len(items)

    def health(self) -> list[CredentialHealth]:
        with closing(self._connect()) as conn, conn:
            rows = conn.execute(
                f"SELECT {_COLUMNS} FROM vault_item ORDER BY account_id, kind, slot"
            ).fetchall()
        return [
            CredentialHealth.build(
                account_id=account_id,
                kind=kind,
                slot=slot,
                label=label,
                expires_at=_parse(expires_at),
                revoked_at=_parse_utc(revoked_at),
                revoked_reason=revoked_reason or "",
                stored_at=_parse_utc(rotated_at or updated_at or created_at),
            )
            for account_id, kind, slot, label, _backend, expires_at, created_at, updated_at, rotated_at, revoked_at, revoked_reason in rows
        ]

    # --- engine 内部能力 ---

    def history(
        self, account_id: str, kind: str, *, slot: str | None = None
    ) -> list[tuple[str, str]]:
        """轮换历史（引擎侧排障用）：[(archived_ref, rotated_at)]，新→旧。"""
        with closing(self._connect()) as conn, conn:
            if slot is None:
                rows = conn.execute(
                    "SELECT archived_ref, rotated_at FROM vault_history"
                    " WHERE account_id = ? AND kind = ? ORDER BY seq DESC",
                    (account_id, kind),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT archived_ref, rotated_at FROM vault_history"
                    " WHERE account_id = ? AND kind = ? AND slot = ? ORDER BY seq DESC",
                    (account_id, kind, slot),
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

    def _revoke_one(
        self,
        account_id: str,
        kind: str,
        slot: str,
        backend_name: str,
        reason: str,
        now_iso: str,
    ) -> None:
        """归档 + 删主引用 + 标记 revoked（单槽位）。"""
        ref = vault_ref(account_id, kind, slot)
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
                "INSERT INTO vault_history (account_id, kind, slot, archived_ref, rotated_at)"
                " VALUES (?, ?, ?, ?, datetime('now'))",
                (account_id, kind, slot, archived_ref),
            )
            conn.execute(
                "UPDATE vault_item SET revoked_at = ?, revoked_reason = ?,"
                " updated_at = datetime('now')"
                " WHERE account_id = ? AND kind = ? AND slot = ?",
                (now_iso, reason, account_id, kind, slot),
            )

    def _row(
        self, account_id: str, kind: str, slot: str
    ) -> tuple[str, datetime | None, str | None] | None:
        with closing(self._connect()) as conn, conn:
            row = conn.execute(
                "SELECT backend, expires_at, revoked_at FROM vault_item"
                " WHERE account_id = ? AND kind = ? AND slot = ?",
                (account_id, kind, slot),
            ).fetchone()
        if row is None:
            return None
        backend, expires_at, revoked_at = row
        return backend, _parse(expires_at), revoked_at

    def _items(self, account_id: str) -> list[tuple[str, str, str, str | None]]:
        """账户下全部条目：(kind, slot, backend, revoked_at)，稳定排序。"""
        with closing(self._connect()) as conn, conn:
            rows = conn.execute(
                "SELECT kind, slot, backend, revoked_at FROM vault_item"
                " WHERE account_id = ? ORDER BY kind, slot",
                (account_id,),
            ).fetchall()
        return [(kind, slot, backend, revoked_at) for kind, slot, backend, revoked_at in rows]

    def _connect(self) -> sqlite3.Connection:
        return connect(self._db_path)


def _ensure_schema(conn: sqlite3.Connection) -> None:
    """老库自迁移（ADR-033）：vault_item 补槽位需要改主键，SQLite 只能重建表。

    - 旧形状（PK account_id, kind）→ 重建：全部行落 `slot=default`，后端引用
      不变，秘密零迁移；
    - 已新形状只补 label/updated_at（幂等）；
    - vault_history 补 slot 列（旧行 default）。
    """
    cols = {row[1] for row in conn.execute("PRAGMA table_info(vault_item)")}
    if "slot" not in cols or "id" not in cols:
        _rebuild_items(conn, cols)
    else:
        if "label" not in cols:
            conn.execute("ALTER TABLE vault_item ADD COLUMN label TEXT NOT NULL DEFAULT ''")
        if "updated_at" not in cols:
            conn.execute("ALTER TABLE vault_item ADD COLUMN updated_at TEXT NOT NULL DEFAULT ''")
            conn.execute(
                "UPDATE vault_item SET updated_at = COALESCE(rotated_at, created_at)"
                " WHERE updated_at = ''"
            )
    history_cols = {row[1] for row in conn.execute("PRAGMA table_info(vault_history)")}
    if "slot" not in history_cols:
        conn.execute(
            "ALTER TABLE vault_history ADD COLUMN slot TEXT NOT NULL DEFAULT 'default'"
        )


def _rebuild_items(conn: sqlite3.Connection, old_cols: set[str]) -> None:
    """旧 vault_item → 新三列主键表：行数据零丢失，秘密引用不变。"""
    conn.execute("ALTER TABLE vault_item RENAME TO vault_item__rebuild")
    conn.executescript(_SCHEMA)
    label = "label" if "label" in old_cols else "''"
    updated = (
        "COALESCE(updated_at, rotated_at, created_at)"
        if "updated_at" in old_cols
        else "COALESCE(rotated_at, created_at)"
    )
    revoked_reason = "COALESCE(revoked_reason, '')" if "revoked_reason" in old_cols else "''"
    revoked_at = "revoked_at" if "revoked_at" in old_cols else "NULL"
    conn.execute(
        "INSERT INTO vault_item"
        " (account_id, kind, slot, label, backend, expires_at, created_at,"
        "  updated_at, rotated_at, revoked_at, revoked_reason)"
        f" SELECT account_id, kind, 'default', {label}, backend, expires_at, created_at,"
        f" {updated}, rotated_at, {revoked_at}, {revoked_reason}"
        " FROM vault_item__rebuild"
    )
    conn.execute("DROP TABLE vault_item__rebuild")


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
