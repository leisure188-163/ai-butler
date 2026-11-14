"""执行域：幂等键按账号 / 回放 / dry_run 硬承诺 / 时间预算一等属性。"""

from datetime import timedelta

import pytest

from butler_core.execution.domain import (
    Action,
    ActionKind,
    BudgetExceeded,
    Run,
    RunAlreadyFinished,
    RunResult,
    idempotency_key,
)
from butler_core.execution.ports import Capabilities, ProvisionRequest, RunLedger
from butler_core.execution.usecases.execute_action import (
    DryRunNotSupported,
    ExecuteAction,
    InvalidRequest,
    RunRequest,
    UnsupportedAction,
)
from butler_core.shared.events import Event, EventSink
from butler_core.shared.results import Status


class MemoryLedger(RunLedger):
    def __init__(self):
        self.rows = []

    def save(self, run):
        self.rows.append(run)

    def find_by_idempotency_key(self, key):
        return next((r for r in self.rows if r.idempotency_key == key and r.is_terminal), None)

    def list_for_account(self, account_id, *, limit):
        return [r for r in reversed(self.rows) if r.account_id == account_id][:limit]

    def list_recent(self, *, limit):
        return list(reversed(self.rows))[:limit]


class MemorySink(EventSink):
    def __init__(self):
        self.events = []

    def publish(self, event):
        self.events.append(event)


class Port:
    def __init__(self, *, dry_run=False, result=None):
        self._caps = Capabilities(dry_run=dry_run, multi_account=True)
        self.calls = []
        self.result = result or RunResult(status=Status.CLAIMED)

    def capabilities(self):
        return self._caps

    def run(self, req: ProvisionRequest):
        self.calls.append(req)
        return self.result


def _request(**kw):
    params = dict(
        action=Action(kind=ActionKind.PROVISION_RUN, target="trae_cn"),
        account_id="trae_cn:main",
        budget=timedelta(seconds=1),
        window="2026-11-14",
    )
    params.update(kw)
    return RunRequest(**params)


def test_idempotency_key_is_per_account():
    action = Action(kind=ActionKind.PROVISION_CLAIM, target="trae_cn")
    k1 = idempotency_key(action, "trae_cn:work", "2026-11-14")
    k2 = idempotency_key(action, "trae_cn:personal", "2026-11-14")
    assert k1 != k2
    assert k1 == idempotency_key(action, "trae_cn:work", "2026-11-14")


def test_replay_does_not_call_port_twice():
    ledger, sink, port = MemoryLedger(), MemorySink(), Port()
    uc = ExecuteAction(ledger=ledger, sink=sink, ports=lambda a: port)
    first = uc.execute(_request())
    second = uc.execute(_request())
    assert second.id == first.id
    assert len(port.calls) == 1
    assert first.result.status is Status.CLAIMED


def test_dry_run_not_supported_is_rejected_explicitly():
    ledger, sink, port = MemoryLedger(), MemorySink(), Port(dry_run=False)
    uc = ExecuteAction(ledger=ledger, sink=sink, ports=lambda a: port)
    with pytest.raises(DryRunNotSupported):
        uc.execute(_request(dry_run=True))
    assert port.calls == []


def test_dry_run_supported_calls_port():
    ledger, sink, port = MemoryLedger(), MemorySink(), Port(dry_run=True)
    uc = ExecuteAction(ledger=ledger, sink=sink, ports=lambda a: port)
    uc.execute(_request(dry_run=True))
    assert port.calls[0].dry_run is True


def test_unsupported_action_and_invalid_request():
    ledger, sink = MemoryLedger(), MemorySink()
    uc = ExecuteAction(ledger=ledger, sink=sink, ports=lambda a: None)
    with pytest.raises(UnsupportedAction):
        uc.execute(_request())
    with pytest.raises(InvalidRequest):
        _request(budget=timedelta(0))
    with pytest.raises(InvalidRequest):
        uc.execute(_request(window=""))


def test_budget_is_first_class_and_run_terminal_immutable():
    action = Action(kind=ActionKind.USAGE_QUERY, target="trae_cn")
    run = Run(id="r", action=action, account_id="trae_cn:main",
              idempotency_key="", budget=timedelta(seconds=5))
    assert run.budget == timedelta(seconds=5)
    run.finish(RunResult(status=Status.FAILED))
    assert run.is_terminal
    with pytest.raises(RunAlreadyFinished):
        run.finish(RunResult(status=Status.CLAIMED))
    assert BudgetExceeded(run.budget).budget == run.budget


def test_run_finished_event_published():
    ledger, sink, port = MemoryLedger(), MemorySink(), Port()
    uc = ExecuteAction(ledger=ledger, sink=sink, ports=lambda a: port)
    uc.execute(_request())
    assert len(sink.events) == 1
    assert isinstance(sink.events[0], Event)
    assert sink.events[0].payload["status"] == "CLAIMED"
