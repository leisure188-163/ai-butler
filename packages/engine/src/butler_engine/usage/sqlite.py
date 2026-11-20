"""SQLite 用量台账（R2-B 块①设计：三实体三表；Repository 接口隔离，SQL 不出本模块）。

- 与 runs 台账同款纪律：SQLite(WAL) 单库、每操作一连接（M0 量级足够）
- usage_snapshots：快照全量留底（相邻帧差分 = 耗尽预测 + QUOTA_LOW 变更检测）
- usage_aggregates：服务端聚合原话（summary_json 不派生不重算）
- usage_quota_ledger：(account_id, record_id) 主键 = record_id 幂等去重（INSERT OR IGNORE）
- 排序契约：collected_at/occurred_at 新→旧，同刻按入库 rowid 决胜（不赌 uuid 字典序）

表结构真相源 = `butler_engine/db/migrations/`（ADR-036）：本模块零 DDL，
构造经 `open_db` 迁移链保证 schema 最新；改表 = 新增编号迁移文件。
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from butler_core.usage.ports import UsageStore
from butler_core.usage.domain import (
    PackageQuota,
    QuotaLedgerEntry,
    UsageAggregate,
    UsageSample,
    UsageSnapshot,
)

from butler_engine.db.conn import connect
from butler_engine.db.migrations import open_db

_SNAPSHOT_COLUMNS = "snapshot_id, account_id, target, collected_at, packages_json"


class SqliteUsageStore(UsageStore):
    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)
        open_db(self._db_path)  # 构造即 schema 最新（迁移链保证，ADR-036）

    # --- UsageStore 端口 ---

    def save_snapshot(self, snapshot: UsageSnapshot) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute(
                f"INSERT INTO usage_snapshot ({_SNAPSHOT_COLUMNS}, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, datetime('now'), datetime('now'))"
                " ON CONFLICT(snapshot_id) DO UPDATE SET"
                " account_id = excluded.account_id, target = excluded.target,"
                " collected_at = excluded.collected_at,"
                " packages_json = excluded.packages_json, updated_at = excluded.updated_at",
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
                f"SELECT {_SNAPSHOT_COLUMNS} FROM usage_snapshot WHERE account_id = ? "
                "ORDER BY collected_at DESC, id DESC LIMIT ?",
                (account_id, limit),
            ).fetchall()
        return [_load_snapshot(row) for row in rows]

    def save_aggregate(self, aggregate: UsageAggregate) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "INSERT INTO usage_aggregate"
                " (aggregate_id, account_id, target, collected_at, summary_json,"
                "  created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, datetime('now'), datetime('now'))"
                " ON CONFLICT(aggregate_id) DO UPDATE SET"
                " account_id = excluded.account_id, target = excluded.target,"
                " collected_at = excluded.collected_at,"
                " summary_json = excluded.summary_json, updated_at = excluded.updated_at",
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
                "SELECT aggregate_id, account_id, target, collected_at, summary_json "
                "FROM usage_aggregate WHERE account_id = ? "
                "ORDER BY collected_at DESC, id DESC LIMIT 1",
                (account_id,),
            ).fetchone()
        return _load_aggregate(row) if row is not None else None

    def append_ledger(self, entries: Iterable[QuotaLedgerEntry]) -> int:
        added = 0
        with closing(self._connect()) as conn, conn:
            for e in entries:
                occurred = e.occurred_at.isoformat() if e.occurred_at else None
                cur = conn.execute(
                    "INSERT OR IGNORE INTO usage_quota_ledger "
                    "(account_id, record_id, target, occurred_at, amount, unit, kind, raw_json,"
                    " created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, COALESCE(?, datetime('now')), COALESCE(?, datetime('now')))",
                    (
                        e.account_id,
                        e.record_id,
                        e.target,
                        occurred,
                        e.amount,
                        e.unit,
                        e.kind,
                        json.dumps(dict(e.raw), ensure_ascii=False) if e.raw else None,
                        occurred,
                        occurred,
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
                "FROM usage_quota_ledger WHERE account_id = ? "
                "ORDER BY occurred_at DESC, id DESC LIMIT ?",
                (account_id, limit),
            ).fetchall()
        return [_load_entry(row) for row in rows]

    # --- 样本（R4，ADR-012 裁决 7：只增不改的时序事实）---

    def append_sample(self, sample: UsageSample) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "INSERT INTO usage_sample "
                "(sample_id, account_id, tokens_in, tokens_out, model, ts, source, duration_ms,"
                " created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    sample.id,
                    sample.account_id,
                    sample.tokens_in,
                    sample.tokens_out,
                    sample.model,
                    sample.ts.isoformat(),
                    sample.source,
                    sample.duration_ms,
                    sample.ts.isoformat(),
                    sample.ts.isoformat(),
                ),
            )

    def list_samples(
        self, account_id: str | None = None, *, limit: int
    ) -> list[UsageSample]:
        """样本按 ts 倒序；account_id=None 读全账号（网关/契约观测面用）。"""
        if limit <= 0:
            return []
        with closing(self._connect()) as conn, conn:
            if account_id is None:
                rows = conn.execute(
                    "SELECT sample_id, account_id, tokens_in, tokens_out, model, ts, source, duration_ms "
                    "FROM usage_sample ORDER BY ts DESC, id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT sample_id, account_id, tokens_in, tokens_out, model, ts, source, duration_ms "
                    "FROM usage_sample WHERE account_id = ? "
                    "ORDER BY ts DESC, id DESC LIMIT ?",
                    (account_id, limit),
                ).fetchall()
        return [_load_sample(row) for row in rows]

    # --- 内部 ---

    def _connect(self) -> sqlite3.Connection:
        return connect(self._db_path)


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


def _load_sample(row: tuple) -> UsageSample:
    (
        sid,
        account_id,
        tokens_in,
        tokens_out,
        model,
        ts,
        source,
        duration_ms,
    ) = row
    return UsageSample(
        id=sid,
        account_id=account_id,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        model=model,
        ts=datetime.fromisoformat(ts),
        source=source,
        duration_ms=duration_ms,
    )
