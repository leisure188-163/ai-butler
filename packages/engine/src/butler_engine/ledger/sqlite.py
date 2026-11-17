"""SQLite Run 台账（A4-01 §5：runs 表；Repository 接口隔离，SQL 不出本模块）。

- SQLite 单库（连接口径单源 butler_engine.db.conn）；每操作一连接
  （线程安全，M0 量级足够；性能要求出现时再池化）
- 幂等查询语义：同键存在已成功（core ResultKind.is_pass 谓词判定）的 Run
  → 返回它（重复触发不重复领取）；否则返回最新一条（失败可重试）
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

from butler_engine.db.conn import connect

_SCHEMA = """
CREATE TABLE IF NOT EXISTS exe_run (
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
CREATE INDEX IF NOT EXISTS idx_exe_run_idempotency ON exe_run(idempotency_key);
"""

_COLUMNS = (
    "id, kind, target, params_json, account_id, idempotency_key, "
    "started_at, budget_seconds, finished_at, status, result_json"
)


class SqliteRunLedger(RunLedger):
    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)
        with closing(self._connect()) as conn, conn:
            # 表名迁移（ADR-021 域前缀纪律）：老表 RENAME 幂等，旧索引随行清理
            if conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='runs'"
            ).fetchone():
                conn.execute("ALTER TABLE runs RENAME TO exe_run")
            conn.execute("DROP INDEX IF EXISTS idx_runs_idempotency")
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
                "INSERT OR REPLACE INTO exe_run (%s) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
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
            rows = conn.execute(
                f"SELECT {_COLUMNS} FROM exe_run WHERE idempotency_key = ? "
                "ORDER BY started_at DESC, id DESC",
                (key,),
            ).fetchall()
        # 「哪些算成功」只认 core 谓词（ResultKind.is_pass 单源）——SQL 不再
        # 硬编码 CLAIMED/ALREADY 字面量：语义判断回 core，本层只管存取（红线 2 同源）
        for row in rows:
            run = _load_run(row)
            if run.result is not None and run.result.kind.is_pass:
                return run  # 已成功的最新一条：命中即回放，重复触发不重复领取
        return _load_run(rows[0]) if rows else None

    def list_for_account(self, account_id: str, *, limit: int) -> list[Run]:
        """该账号最近 Run（新→旧）：健康中心判 NO_AUTH 连败（A4-01 §2）。"""
        if limit <= 0:
            return []
        with closing(self._connect()) as conn, conn:
            rows = conn.execute(
                f"SELECT {_COLUMNS} FROM exe_run WHERE account_id = ? "
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
                f"SELECT {_COLUMNS} FROM exe_run ORDER BY started_at DESC, id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [_load_run(row) for row in rows]

    # --- 内部 ---

    def _connect(self) -> sqlite3.Connection:
        return connect(self._db_path)


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
