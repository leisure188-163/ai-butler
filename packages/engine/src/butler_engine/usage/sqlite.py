"""SQLite 用量台账（R2-B 块①设计：三实体三表；Repository 接口隔离，SQL 不出本模块）。

- 与 runs 台账同款纪律：SQLite(WAL) 单库、每操作一连接（M0 量级足够）
- usage_snapshots：快照全量留底（相邻帧差分 = 耗尽预测 + QUOTA_LOW 变更检测）
- usage_aggregates：服务端聚合原话（summary_json 不派生不重算）
- quota_ledger：(account_id, record_id) 主键 = record_id 幂等去重（INSERT OR IGNORE）
- 排序契约：collected_at/occurred_at 新→旧，同刻按入库 rowid 决胜（不赌 uuid 字典序）
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from butler_core.usage.ports import UsageStore
from butler_core.usage.domain import PackageQuota, QuotaLedgerEntry, UsageAggregate, UsageSnapshot

_SCHEMA = """
CREATE TABLE IF NOT EXISTS usage_snapshots (
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    target TEXT NOT NULL,
    collected_at TEXT NOT NULL,
    packages_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_usage_snapshots_account
    ON usage_snapshots(account_id, collected_at);

CREATE TABLE IF NOT EXISTS usage_aggregates (
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    target TEXT NOT NULL,
    collected_at TEXT NOT NULL,
    summary_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_usage_aggregates_account
    ON usage_aggregates(account_id, collected_at);

CREATE TABLE IF NOT EXISTS quota_ledger (
    account_id TEXT NOT NULL,
    record_id TEXT NOT NULL,
    target TEXT NOT NULL,
    occurred_at TEXT,
    amount REAL NOT NULL,
    unit TEXT NOT NULL,
    kind TEXT,
    raw_json TEXT,
    PRIMARY KEY (account_id, record_id)
);
CREATE INDEX IF NOT EXISTS idx_quota_ledger_account
    ON quota_ledger(account_id, occurred_at);
"""

_SNAPSHOT_COLUMNS = "id, account_id, target, collected_at, packages_json"


class SqliteUsageStore(UsageStore):
    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)
        with closing(self._connect()) as conn, conn:
            conn.executescript(_SCHEMA)

    # --- UsageStore 端口 ---

    def save_snapshot(self, snapshot: UsageSnapshot) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute(
                f"INSERT OR REPLACE INTO usage_snapshots ({_SNAPSHOT_COLUMNS}) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    snapshot.id,
                    snapshot.account_id,
                    snapshot.target,
                    snapshot.collected_at.isoformat(),
                    json.dumps(
                        [_dump_package(p) for p in snapshot.packages],
                        ensure_ascii=False,
                    ),
                ),
            )

    def list_snapshots(self, account_id: str, *, limit: int) -> list[UsageSnapshot]:
        if limit <= 0:
            return []
        with closing(self._connect()) as conn, conn:
            rows = conn.execute(
                f"SELECT {_SNAPSHOT_COLUMNS} FROM usage_snapshots WHERE account_id = ? "
                "ORDER BY collected_at DESC, rowid DESC LIMIT ?",
                (account_id, limit),
            ).fetchall()
        return [_load_snapshot(row) for row in rows]

    def save_aggregate(self, aggregate: UsageAggregate) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "INSERT OR REPLACE INTO usage_aggregates "
                "(id, account_id, target, collected_at, summary_json) VALUES (?, ?, ?, ?, ?)",
                (
                    aggregate.id,
                    aggregate.account_id,
                    aggregate.target,
                    aggregate.collected_at.isoformat(),
                    json.dumps(dict(aggregate.summary), ensure_ascii=False),
                ),
            )

    def latest_aggregate(self, account_id: str) -> UsageAggregate | None:
        with closing(self._connect()) as conn, conn:
            row = conn.execute(
                "SELECT id, account_id, target, collected_at, summary_json "
                "FROM usage_aggregates WHERE account_id = ? "
                "ORDER BY collected_at DESC, rowid DESC LIMIT 1",
                (account_id,),
            ).fetchone()
        return _load_aggregate(row) if row is not None else None

    def append_ledger(self, entries: Iterable[QuotaLedgerEntry]) -> int:
        added = 0
        with closing(self._connect()) as conn, conn:
            for e in entries:
                cur = conn.execute(
                    "INSERT OR IGNORE INTO quota_ledger "
                    "(account_id, record_id, target, occurred_at, amount, unit, kind, raw_json) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        e.account_id,
                        e.record_id,
                        e.target,
                        e.occurred_at.isoformat() if e.occurred_at else None,
                        e.amount,
                        e.unit,
                        e.kind,
                        json.dumps(dict(e.raw), ensure_ascii=False) if e.raw else None,
                    ),
                )
                added += cur.rowcount if cur.rowcount > 0 else 0
        return added

    def list_ledger(self, account_id: str, *, limit: int) -> list[QuotaLedgerEntry]:
        if limit <= 0:
            return []
        with closing(self._connect()) as conn, conn:
            rows = conn.execute(
                "SELECT account_id, record_id, target, occurred_at, amount, unit, kind, raw_json "
                "FROM quota_ledger WHERE account_id = ? "
                "ORDER BY occurred_at DESC, rowid DESC LIMIT ?",
                (account_id, limit),
            ).fetchall()
        return [_load_entry(row) for row in rows]

    # --- 内部 ---

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn


# --- JSON 往返（形状归一是存储职责，语义仍在 core 实体）---


def _dump_package(p: PackageQuota) -> dict[str, Any]:
    return {
        "package_id": p.package_id,
        "name": p.name,
        "total": p.total,
        "used": p.used,
        "remaining": p.remaining,
        "unit": p.unit,
        "cycle_end": p.cycle_end.isoformat() if p.cycle_end else None,
        "status": p.status,
    }


def _load_package(data: dict[str, Any]) -> PackageQuota:
    return PackageQuota(
        package_id=data["package_id"],
        name=data["name"],
        total=data["total"],
        used=data["used"],
        remaining=data["remaining"],
        unit=data.get("unit", ""),
        cycle_end=(
            datetime.fromisoformat(data["cycle_end"]) if data.get("cycle_end") else None
        ),
        status=data.get("status", ""),
    )


def _load_snapshot(row: tuple) -> UsageSnapshot:
    sid, account_id, target, collected_at, packages_json = row
    return UsageSnapshot(
        id=sid,
        account_id=account_id,
        target=target,
        collected_at=datetime.fromisoformat(collected_at),
        packages=tuple(
            _load_package(p) for p in json.loads(packages_json)
        ),
    )


def _load_aggregate(row: tuple) -> UsageAggregate:
    aid, account_id, target, collected_at, summary_json = row
    return UsageAggregate(
        id=aid,
        account_id=account_id,
        target=target,
        collected_at=datetime.fromisoformat(collected_at),
        summary=json.loads(summary_json),
    )


def _load_entry(row: tuple) -> QuotaLedgerEntry:
    (
        account_id,
        record_id,
        target,
        occurred_at,
        amount,
        unit,
        kind,
        raw_json,
    ) = row
    return QuotaLedgerEntry(
        record_id=record_id,
        account_id=account_id,
        target=target,
        occurred_at=datetime.fromisoformat(occurred_at) if occurred_at else None,
        amount=amount,
        unit=unit,
        kind=kind or "",
        raw=json.loads(raw_json) if raw_json else None,
    )
