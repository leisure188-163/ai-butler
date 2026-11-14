"""A2-01 §3~5 领域模型形状基线：Action / Run / Event。

字面量冻结（多一个少一个都是协议事故）、终态不可回退、severity 在 core 推导。
"""

import pytest

from butler_core.execution.domain import Action, ActionInvalid, ActionKind
from butler_core.shared.events import Event, EventType, Severity, run_finished_event
from butler_core.shared.errors import DomainError
from butler_core.shared.results import Status
from butler_core.execution.domain import Run, RunAlreadyFinished, RunResult

EXPECTED_ACTION_KINDS = {
    "provision.run",
    "provision.claim",
    "usage.collect",
    "usage.query",
    "session.export",
    "session.import",
    "health.check",
    "gateway.route",
}


def test_action_kind_literals_frozen():
    assert {k.value for k in ActionKind} == EXPECTED_ACTION_KINDS
    assert len(ActionKind) == 8


def test_action_target_required():
    with pytest.raises(ActionInvalid):
        Action(kind=ActionKind.PROVISION_RUN, target="  ")


def test_idempotent_write_kinds():
    assert ActionKind.PROVISION_RUN.is_idempotent_write
    assert ActionKind.PROVISION_CLAIM.is_idempotent_write
    assert not ActionKind.USAGE_QUERY.is_idempotent_write
    assert not ActionKind.HEALTH_CHECK.is_idempotent_write


def _finished_run(status: Status) -> Run:
    action = Action(kind=ActionKind.PROVISION_RUN, target="trae_cn")
    run = Run(id="r1", action=action, account_id="acc1", idempotency_key="k")
    run.finish(RunResult(status=status))
    return run


def test_run_finish_lifecycle():
    action = Action(kind=ActionKind.HEALTH_CHECK, target="trae_cn")
    run = Run(id="r1", action=action, account_id="acc1", idempotency_key="")
    assert not run.is_terminal
    run.finish(RunResult(status=Status.CLAIMED))
    assert run.is_terminal
    assert run.finished_at is not None
    with pytest.raises(RunAlreadyFinished):
        run.finish(RunResult(status=Status.FAILED))  # 终态不可回退


def test_event_type_literals_frozen():
    assert {t.value for t in EventType} == {
        "RUN_FINISHED",
        "CREDENTIAL_EXPIRING",
        "CREDENTIAL_EXPIRED",
        "QUOTA_LOW",
        "PROTOCOL_CHANGED",
        "ACCOUNT_HEALTH_CHANGED",
    }


def test_severity_literals_frozen():
    assert {s.value for s in Severity} == {"silent", "badge", "push"}


@pytest.mark.parametrize(
    "status,expected",
    [
        (Status.CLAIMED, Severity.SILENT),
        (Status.ALREADY, Severity.SILENT),
        (Status.NO_AUTH, Severity.BADGE),
        (Status.EXPIRED, Severity.BADGE),
        (Status.FAILED, Severity.SILENT),  # A2-01 §5 字面：仅 attention 产生可见通知
        (Status.PENDING, Severity.SILENT),
        (Status.SKIPPED, Severity.SILENT),
    ],
)
def test_run_finished_severity_derivation(status, expected):
    event = run_finished_event(_finished_run(status))
    assert event.severity is expected
    assert event.type is EventType.RUN_FINISHED
    assert event.payload["run_id"] == "r1"
    assert event.payload["status"] == status.value


def test_run_finished_requires_terminal():
    action = Action(kind=ActionKind.HEALTH_CHECK, target="trae_cn")
    run = Run(id="r2", action=action, account_id="a", idempotency_key="")
    with pytest.raises(DomainError):
        run_finished_event(run)


def test_event_has_id_and_ts():
    event = Event.new(EventType.QUOTA_LOW, severity=Severity.PUSH, account_id="acc1")
    assert event.id  # 可追溯（A4-01 §3）
    assert event.ts.tzinfo is not None
    assert event.account_id == "acc1"
