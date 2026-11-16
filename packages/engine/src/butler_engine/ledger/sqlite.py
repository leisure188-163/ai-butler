"""SQLite Run 台账（A4-01 §5：runs 表；Repository 接口隔离，SQL 不出本模块）。

- SQLite(WAL) 单库；每操作一连接（线程安全，M0 量级足够；性能要求出现时再池化）
- 幂等查询语义：同键存在已成功（CLAIMED/ALREADY）的 Run → 返回它
  （重复触发不重复领取）；否则返回最新一条（失败可重试）
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from butler_core.execution.ports import RunLedger
from butler_core.execution.domain import Action, ActionKind
from butler_core.shared.results import Status
from butler_core.execution.domain import Evidence, RepairHint, Run, RunResult

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    target TEXT NOT NULL,
    params_json TEXT NOT NULL,
    account_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    started_at TEXT NOT NULL,
    budget_seconds REAL NOT NULL,
    finished_at TEXT,
    status TEXT,
    result_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_runs_idempotency ON runs(idempotency_key);
"""

_COLUMNS = (
    "id, kind, target, params_json, account_id, idempotency_key, "
    "started_at, budget_seconds, finished_at, status, result_json"
)


class SqliteRunLedger(RunLedger):
    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)
        with closing(self._connect()) as conn, conn:
            conn.executescript(_SCHEMA)

    # --- core RunLedger 端口 ---

    def save(self, run: Run) -> None:
        result_json = (
            json.dumps(_dump_result(run.result), ensure_ascii=False)
            if run.result is not None
            else None
        )
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "INSERT OR REPLACE INTO runs (%s) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                % _COLUMNS,
                (
                    run.id,
                    run.action.kind.value,
                    run.action.target,
                    json.dumps(dict(run.action.params), ensure_ascii=False),
                    run.account_id,
                    run.idempotency_key,
                    run.started_at.isoformat(),
                    run.budget.total_seconds(),
                    run.finished_at.isoformat() if run.finished_at else None,
                    run.result.status.value if run.result else None,
                    result_json,
                ),
            )

    def find_by_idempotency_key(self, key: str) -> Run | None:
        if not key:
            return None  # 空键 = 只读动作，无幂等语义
        with closing(self._connect()) as conn, conn:
            # 先找已成功的最新一条（命中即回放，重复触发不重复领取）
            row = conn.execute(
                f"SELECT {_COLUMNS} FROM runs WHERE idempotency_key = ? "
                "AND status IN ('CLAIMED', 'ALREADY') ORDER BY started_at DESC LIMIT 1",
                (key,),
            ).fetchone()
            if row is None:
                row = conn.execute(
                    f"SELECT {_COLUMNS} FROM runs WHERE idempotency_key = ? "
                    "ORDER BY started_at DESC LIMIT 1",
                    (key,),
                ).fetchone()
        return _load_run(row) if row is not None else None

    def list_for_account(self, account_id: str, *, limit: int) -> list[Run]:
        """该账号最近 Run（新→旧）：健康中心判 NO_AUTH 连败（A4-01 §2）。"""
        if limit <= 0:
            return []
        with closing(self._connect()) as conn, conn:
            rows = conn.execute(
                f"SELECT {_COLUMNS} FROM runs WHERE account_id = ? "
                "ORDER BY started_at DESC, id DESC LIMIT ?",
                (account_id, limit),
            ).fetchall()
        return [_load_run(row) for row in rows]

    def list_recent(self, *, limit: int) -> list[Run]:
        """全库最近 Run（新→旧）：台账页数据源（A3-01 记录页，M0 三页之一）。"""
        if limit <= 0:
            return []
        with closing(self._connect()) as conn, conn:
            rows = conn.execute(
                f"SELECT {_COLUMNS} FROM runs ORDER BY started_at DESC, id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [_load_run(row) for row in rows]

    # --- 内部 ---

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        # OFF 而非 WAL/DELETE：本机文件虚拟化层拦截一切新建 -wal/-shm/-journal 伴生文件
        # （2026-11-16 实证 probe.db-journal 创建即被回收），无伴生文件才能写库；
        # 代价 = 崩溃时最后一条写丢失（单机台账可接受，动作幂等重试兜底）
        conn.execute("PRAGMA journal_mode=OFF")
        return conn


def _dump_result(result: RunResult) -> dict[str, Any]:
    return {
        "status": result.status.value,
        "evidence": [
            {"summary": ev.summary, "raw_code": ev.raw_code}
            for ev in result.evidence
        ],
        "repair_hint": (
            {"reason": result.repair_hint.reason, "action_id": result.repair_hint.action_id}
            if result.repair_hint is not None
            else None
        ),
    }


def _load_run(row: tuple) -> Run:
    (
        run_id,
        kind,
        target,
        params_json,
        account_id,
        idempotency_key,
        started_at,
        budget_seconds,
        finished_at,
        status,
        result_json,
    ) = row
    result: RunResult | None = None
    if result_json is not None:
        data = json.loads(result_json)
        result = RunResult(
            status=Status(data["status"]),
            evidence=tuple(
                Evidence(summary=ev["summary"], raw_code=ev.get("raw_code"))
                for ev in data["evidence"]
            ),
            repair_hint=(
                RepairHint(**data["repair_hint"]) if data["repair_hint"] else None
            ),
        )
    return Run(
        id=run_id,
        action=Action(kind=ActionKind(kind), target=target, params=json.loads(params_json)),
        account_id=account_id,
        idempotency_key=idempotency_key,
        started_at=datetime.fromisoformat(started_at),
        budget=timedelta(seconds=budget_seconds),
        finished_at=datetime.fromisoformat(finished_at) if finished_at else None,
        result=result,
    )
