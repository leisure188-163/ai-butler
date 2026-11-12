"""SqliteAuditLog 行为基线（A4-01 §4）：append-only、哈希、导出、保留策略。"""

import json
import sqlite3
from contextlib import closing
from datetime import timedelta

from kabao_core.domain.action import Action, ActionKind
from kabao_core.domain.results import Status
from kabao_core.domain.run import Run, RunResult, now_utc
from kabao_engine.audit.sqlite import AuditSubscriber, SqliteAuditLog


def test_record_hashes_credential_ref(tmp_path):
    audit = SqliteAuditLog(tmp_path / "m.db")
    audit.record(
        actor="trae_cn",
        action="provision.run",
        outcome="CLAIMED",
        account_id="acc1",
        credential_ref="acc1:ss_aes:secret-part",
    )
    with closing(sqlite3.connect(tmp_path / "m.db")) as conn:
        row = conn.execute(
            "SELECT credential_ref FROM audit WHERE actor = 'trae_cn'"
        ).fetchone()
    assert row[0] != "acc1:ss_aes:secret-part"  # 绝不存明文
    assert len(row[0]) == 64  # sha256 hexdigest


def test_export_and_purge(tmp_path):
    audit = SqliteAuditLog(tmp_path / "m.db")
    old_ts = now_utc() - timedelta(days=120)
    audit.record(actor="a", action="vault.rotate", outcome="OK", ts=old_ts)
    audit.record(actor="b", action="provision.run", outcome="CLAIMED")
    assert len(json.loads(audit.export_json())) == 2
    removed = audit.purge(retention_days=90)
    assert removed == 1  # 只清超龄的
    assert len(json.loads(audit.export_json())) == 1


def test_audit_subscriber_only_writes_for_provision(tmp_path):
    audit = SqliteAuditLog(tmp_path / "m.db")
    sub = AuditSubscriber(audit)
    from kabao_core.domain.event import Event, EventType, Severity

    write_done = Event.new(
        EventType.RUN_FINISHED,
        severity=Severity.SILENT,
        account_id="acc1",
        payload={
            "run_id": "r1",
            "status": Status.CLAIMED.value,
            "action": "provision.run",
            "target": "trae_cn",
        },
    )
    read_only = Event.new(
        EventType.RUN_FINISHED,
        severity=Severity.SILENT,
        account_id="acc1",
        payload={
            "run_id": "r2",
            "status": Status.CLAIMED.value,
            "action": "health.check",
            "target": "trae_cn",
        },
    )
    sub.on_event(write_done)
    sub.on_event(read_only)
    sub.on_event(Event.new(EventType.QUOTA_LOW, severity=Severity.BADGE))  # 非终态事件
    assert len(json.loads(audit.export_json())) == 1  # 只记写操作


def test_subscriber_end_to_end_via_real_run(tmp_path):
    """RUN_FINISHED（领取类）→ 审计落账，字段对得上。"""
    audit = SqliteAuditLog(tmp_path / "m.db")
    sub = AuditSubscriber(audit)
    action = Action(kind=ActionKind.PROVISION_CLAIM, target="workbuddy_cn")
    run = Run(id="r9", action=action, account_id="acc7", idempotency_key="k9")
    run.finish(RunResult(status=Status.ALREADY))
    from kabao_core.domain.event import run_finished_event

    sub.on_event(run_finished_event(run))
    rows = json.loads(audit.export_json())
    assert rows[0]["actor"] == "workbuddy_cn"
    assert rows[0]["action"] == "provision.claim"
    assert rows[0]["outcome"] == "ALREADY"
    assert rows[0]["account_id"] == "acc7"
