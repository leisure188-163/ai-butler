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

表结构真相源 = `butler_engine/db/migrations/`（ADR-036）：本模块零 DDL，
构造经 `open_db` 迁移链保证 schema 最新；改表 = 新增编号迁移文件。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from butler_core.accounts.ports import AccountRepository
from butler_core.accounts.domain import (
    Account,
    AccountIdentity,
    AccountInvalid,
    Entitlement,
    Session,
    SessionKind,
    SessionLevel,
)

from butler_engine.db.conn import connect
from butler_engine.db.migrations import open_db

#: 列清单（与 001_initial.sql 列序一致；save/get 按 this 顺序读写，id 不在内）
_COLS = (
    "platform_code, source_key, account_id, account_code, account_name, alias, base_url, "
    "device_ref, identity_json, origin, last_seen_at, sessions, entitlement_json, is_active, "
    "created_at, updated_at, deleted_at"
)


class SqliteAccountRepository(AccountRepository):
    def __init__(self, db_path: str | Path) -> None:
        self._db = str(db_path)
        open_db(self._db)  # 构造即 schema 最新（迁移链保证，ADR-036）

    def _connect(self):
        return connect(self._db)  # 迁移已在 __init__ 完成，操作期直连

    def save(self, account: Account) -> None:
        from butler_core.shared.time import now_utc

        with self._connect() as conn, conn:
            row = conn.execute(
                "SELECT platform_code FROM acc_account WHERE account_id = ?",
                (account.id,),
            ).fetchone()
            if row is not None and row[0] != account.platform_code:
                raise AccountInvalid(
                    f"账户平台冻结：{account.id!r} 已登记为 {row[0]!r}，"
                    f"拒绝改写为 {account.platform_code!r}"
                )
            conn.execute(
                f"INSERT INTO acc_account ({_COLS}) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT (account_id) DO UPDATE SET "
                "account_code=excluded.account_code, "
                "account_name=excluded.account_name, alias=excluded.alias, "
                "base_url=excluded.base_url, device_ref=excluded.device_ref, "
                "source_key=excluded.source_key, "
                "identity_json=excluded.identity_json, origin=excluded.origin, "
                "last_seen_at=excluded.last_seen_at, sessions=excluded.sessions, "
                "entitlement_json=excluded.entitlement_json, is_active=excluded.is_active, "
                "updated_at=excluded.updated_at, deleted_at=excluded.deleted_at",
                (
                    account.platform_code,
                    account.identity.source_key,
                    account.id,
                    account.account_code,
                    account.account_name,
                    account.alias,
                    account.base_url,
                    account.device_ref,
                    _dump_identity(account.identity),
                    account.origin,
                    account.last_seen_at.isoformat() if account.last_seen_at else None,
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


_IDENTITY_FIELDS = ("nickname", "email", "uid", "org")


def _dump_identity(identity: AccountIdentity) -> str | None:
    """空身份落 NULL（不写 "{}"），让「未知」在库里也只有一种形状。

    source_key 是身份锚点，单独落 ``source_key`` 列（唯一索引），不进 JSON 副本。
    """
    fields = {name: getattr(identity, name) for name in _IDENTITY_FIELDS if getattr(identity, name)}
    if not fields:
        return None
    return json.dumps(fields, ensure_ascii=False)


def _load_identity(raw: str | None, source_key: str = "") -> AccountIdentity:
    if not raw:
        return AccountIdentity(source_key=source_key or "")
    try:
        data = json.loads(raw)
    except ValueError:
        return AccountIdentity(source_key=source_key or "")  # 坏行如实未知，不炸名册
    if not isinstance(data, dict):
        return AccountIdentity(source_key=source_key or "")
    return AccountIdentity(
        **{
            name: str(data.get(name) or "")
            for name in _IDENTITY_FIELDS
            if name in data
        },
        source_key=source_key or "",
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
    # SELECT {_COLS} 不含 id 列：row[2]=account_id 即聚合 id（不透明主键，ADR-034）
    return Account(
        id=row[2],
        platform_code=row[0],
        account_code=row[3],
        account_name=row[4],
        alias=row[5] or "",
        base_url=row[6] or "",
        device_ref=row[7],
        identity=_load_identity(row[8], row[1]),
        origin=row[9] or "connector",
        last_seen_at=datetime.fromisoformat(row[10]) if row[10] else None,
        sessions=_load_sessions(row[11], row[2]),
        entitlement=_load_entitlement(row[12], row[2]),
        is_active=bool(row[13]),
        created_at=datetime.fromisoformat(row[14]),
        deleted_at=datetime.fromisoformat(row[16]) if row[16] else None,
    )
