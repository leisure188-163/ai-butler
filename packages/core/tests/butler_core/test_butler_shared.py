"""shared 内核：七字面量 / 方言注册表 / 六型事件 / 严重级别。"""

from datetime import datetime, timezone

import pytest

from butler_core.shared.events import (
    Event,
    EventType,
    Severity,
    run_finished_event,
)
from butler_core.shared.results import (
    DialectError,
    Status,
    UnknownEngineCode,
    from_engine,
    register_dialect,
)


def test_seven_literals_exact():
    assert {s.value for s in Status} == {
        "CLAIMED", "ALREADY", "NO_AUTH", "EXPIRED", "FAILED", "PENDING", "SKIPPED"
    }


@pytest.mark.parametrize("status", [Status.CLAIMED, Status.ALREADY])
def test_pass_kind(status):
    assert status.kind.is_pass and not status.kind.is_attention
    assert status.kind.signal == "ok"


@pytest.mark.parametrize("status", [Status.NO_AUTH, Status.EXPIRED])
def test_attention_kind(status):
    assert status.kind.is_attention and not status.kind.is_fail


def test_fail_and_quiet_kind():
    assert Status.FAILED.kind.is_fail
    assert Status.FAILED.kind.signal == "danger"
    assert Status.PENDING.kind.signal == "quiet"
    assert Status.SKIPPED.kind.signal == "quiet"


def test_dialect_unknown_code_explicit():
    with pytest.raises(UnknownEngineCode):
        from_engine("NOT_A_CODE")
    with pytest.raises(DialectError):
        from_engine("X", dialect="missing")
    register_dialect("dialect_test", {"401": Status.EXPIRED})
    assert from_engine("401", dialect="dialect_test") is Status.EXPIRED
    with pytest.raises(DialectError):
        register_dialect("", {"x": Status.FAILED})


def test_six_event_types():
    assert {e.value for e in EventType} == {
        "RUN_FINISHED", "CREDENTIAL_EXPIRING", "CREDENTIAL_EXPIRED",
        "QUOTA_LOW", "PROTOCOL_CHANGED", "ACCOUNT_HEALTH_CHANGED",
    }
    assert {s.value for s in Severity} == {"silent", "badge", "push"}


class _FakeKind:
    def __init__(self, attention):
        self.is_attention = attention


class _FakeResult:
    def __init__(self, attention):
        self.kind = _FakeKind(attention)
        self.status = Status.PENDING


class _FakeAction:
    kind = type("K", (), {"value": "provision.run"})()
    target = "trae_cn"


class _FakeRun:
    id = "r1"
    account_id = "trae_cn:main"
    action = _FakeAction()
    result = _FakeResult(True)


def test_run_finished_event_severity():
    event = run_finished_event(_FakeRun())
    assert event.type is EventType.RUN_FINISHED
    assert event.severity is Severity.BADGE
    assert event.account_id == "trae_cn:main"
    assert event.payload["target"] == "trae_cn"


def test_event_new_has_ts_and_id():
    event = Event.new(EventType.QUOTA_LOW, severity=Severity.BADGE)
    assert event.id and isinstance(event.ts, datetime)
    assert event.ts.tzinfo == timezone.utc
