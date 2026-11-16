"""SQLite append-only 审计（A4-01 §4）。

- 只 INSERT：无更新/删除接口；credential_ref 一律 sha256 哈希，绝不存明文
- 触发点（A4-01 §4）：凭据存取/轮换（3b 接线）、所有写操作（经 RUN_FINISHED
  订阅者自动覆盖，session.import M4 加入 IDEMPOTENT_KINDS 即自动生效）、
  连接器安装与升级（M1 接线）
- 反代上线（M3）前审计必须就位——这是 L3 的安全底线，不是可选件
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

from butler_core.shared.events import Event, EventType
from butler_core.execution.domain import now_utc

from butler_engine.db.conn import connect

_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    actor TEXT NOT NULL,
    account_id TEXT,
    credential_ref TEXT,
    action TEXT NOT NULL,
    outcome TEXT NOT NULL
);
"""

_COLUMNS = "seq, ts, actor, account_id, credential_ref, action, outcome"


class SqliteAuditLog:
    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)
        with closing(self._connect()) as conn, conn:
            conn.executescript(_SCHEMA)

    def record(
        self,
        *,
        actor: str,
        action: str,
        outcome: str,
        account_id: str | None = None,
        credential_ref: str | None = None,
        ts: datetime | None = None,
    ) -> None:
        """追加一条审计。credential_ref 入库前强制哈希（哈希非明文，A4-01 §4）。"""
        ref = (
            hashlib.sha256(credential_ref.encode("utf-8")).hexdigest()
            if credential_ref
            else None
        )
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "INSERT INTO audit (ts, actor, account_id, credential_ref, action, outcome)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    (ts if ts is not None else now_utc()).isoformat(),
                    actor,
                    account_id,
                    ref,
                    action,
                    outcome,
                ),
            )

    def export_json(self) -> str:
        """排障导出（JSON）。只读，不脱敏结构——credential_ref 本就是哈希。"""
        with closing(self._connect()) as conn, conn:
            rows = conn.execute(f"SELECT {_COLUMNS} FROM audit ORDER BY seq").fetchall()
        return json.dumps(
            [
                {
                    "seq": seq,
                    "ts": ts,
                    "actor": actor,
                    "account_id": account_id,
                    "credential_ref": ref,
                    "action": action,
                    "outcome": outcome,
                }
                for seq, ts, actor, account_id, ref, action, outcome in rows
            ],
            ensure_ascii=False,
            indent=2,
        )

    def purge(self, *, retention_days: int = 90) -> int:
        """保留策略：默认 90 天。返回清除行数。"""
        cutoff = (now_utc() - timedelta(days=retention_days)).isoformat()
        with closing(self._connect()) as conn, conn:
            cursor = conn.execute("DELETE FROM audit WHERE ts < ?", (cutoff,))
            return cursor.rowcount

    # --- 内部 ---

    def _connect(self) -> sqlite3.Connection:
        return connect(self._db_path)


class AuditSubscriber:
    """RUN_FINISHED（领取类写动作）→ 审计落账（A4-01 §4：所有写操作）。

    注册为事件总线订阅者；审计不做通知（通知中心是唯一通知出口）。
    """

    def __init__(self, log: SqliteAuditLog) -> None:
        self._log = log

    def on_event(self, event: Event) -> None:
        if event.type is not EventType.RUN_FINISHED:
            return
        kind = event.payload.get("action", "")
        if kind not in ("provision.run", "provision.claim"):
            return  # 只读动作不审计；session.import M4 起自动纳入
        self._log.record(
            actor=event.payload.get("target", ""),
            action=kind,
            outcome=event.payload.get("status", ""),
            account_id=event.account_id,
        )
