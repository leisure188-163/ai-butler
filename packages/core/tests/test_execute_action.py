"""ExecuteAction 编排语义基线（A2-01 §3 / R6）。

幂等回放 / 时间预算硬约束 / dry_run 硬承诺 / 协议变更探测 / 只读动作不去重。
core 用例纯 pytest、毫秒级、零 mock IO（R8）——端口用进程内假实现。
"""

import time
from datetime import timedelta

import pytest

from butler_core.execution.ports import Capabilities, ProvisionRequest, routing_ports
from butler_core.execution.usecases.execute_action import DryRunNotSupported, ExecuteAction, InvalidRequest, RunRequest, UnsupportedAction, idempotency_key
from butler_core.execution.domain import Action, ActionKind
from butler_core.shared.events import EventType
from butler_core.shared.results import Status, UnknownEngineCode
from butler_core.execution.domain import Run, RunResult


class FakePort:
    """进程内假端口（结构化满足 ProvisionPort 协议，不继承）。"""

    def __init__(self, caps=None, result=None, error=None, delay=0.0):
        self._caps = caps
        self._result = result
        self._error = error
        self._delay = delay
        self.calls: list[ProvisionRequest] = []

    def capabilities(self):
        return self._caps if self._caps is not None else Capabilities(dry_run=True)

    def run(self, req):
        self.calls.append(req)
        if self._delay:
            time.sleep(self._delay)
        if self._error is not None:
            raise self._error
        return self._result


class MemLedger:
    def __init__(self):
        self.runs: dict[str, Run] = {}

    def save(self, run: Run) -> None:
        self.runs[run.id] = run

    def find_by_idempotency_key(self, key: str) -> Run | None:
        for run in self.runs.values():
            if run.idempotency_key == key:
                return run
        return None


class CollectSink:
    def __init__(self):
        self.events: list = []

    def publish(self, event) -> None:
        self.events.append(event)


CLAIM_ACTION = Action(kind=ActionKind.PROVISION_RUN, target="trae_cn")


def _usecase(port):
    ledger, sink = MemLedger(), CollectSink()
    uc = ExecuteAction(
        ledger=ledger,
        sink=sink,
        ports=routing_ports(
            {ActionKind.PROVISION_RUN: port, ActionKind.HEALTH_CHECK: port}, {}
        ),
    )
    return uc, ledger, sink


def test_happy_path_claims_and_publishes():
    port = FakePort(result=RunResult(status=Status.CLAIMED))
    uc, ledger, sink = _usecase(port)
    run = uc.execute(
        RunRequest(action=CLAIM_ACTION, account_id="acc1", window="2026-11-10")
    )
    assert run.is_terminal and run.result.status is Status.CLAIMED
    assert len(port.calls) == 1
    assert [e.type for e in sink.events] == [EventType.RUN_FINISHED]
    assert ledger.runs[run.id] is run  # 台账必有记录


def test_deadline_equals_started_plus_budget():
    port = FakePort(result=RunResult(status=Status.CLAIMED))
    uc, _, _ = _usecase(port)
    run = uc.execute(
        RunRequest(
            action=CLAIM_ACTION,
            account_id="a",
            window="w",
            budget=timedelta(seconds=7),
        )
    )
    assert port.calls[0].deadline - run.started_at == timedelta(seconds=7)


def test_idempotency_key_format():
    assert (
        idempotency_key(CLAIM_ACTION, "acc1", "2026-11-10")
        == "provision.run:acc1:2026-11-10"
    )


def test_idempotent_replay_on_claimed():
    port = FakePort(result=RunResult(status=Status.CLAIMED))
    uc, _, _ = _usecase(port)
    req = RunRequest(action=CLAIM_ACTION, account_id="a", window="2026-11-10")
    first = uc.execute(req)
    second = uc.execute(req)  # 重复触发同窗口
    assert second is first  # 回放原 Run
    assert len(port.calls) == 1  # 绝不重复发起


def test_failed_run_is_not_replayed():
    port = FakePort(result=RunResult(status=Status.FAILED))
    uc, _, _ = _usecase(port)
    req = RunRequest(action=CLAIM_ACTION, account_id="a", window="w")
    first = uc.execute(req)
    second = uc.execute(req)
    assert second is not first  # 失败可重试
    assert len(port.calls) == 2


def test_dry_run_rejected_when_unsupported():
    port = FakePort(
        caps=Capabilities(dry_run=False), result=RunResult(status=Status.CLAIMED)
    )
    uc, ledger, _ = _usecase(port)
    with pytest.raises(DryRunNotSupported):
        uc.execute(
            RunRequest(action=CLAIM_ACTION, account_id="a", window="w", dry_run=True)
        )
    assert port.calls == []  # 绝不静默降级成真实执行
    assert ledger.runs == {}  # 拒绝发生在建 Run 之前


def test_dry_run_supported_passes_through():
    port = FakePort(caps=Capabilities(dry_run=True), result=RunResult(status=Status.PENDING))
    uc, _, _ = _usecase(port)
    run = uc.execute(
        RunRequest(action=CLAIM_ACTION, account_id="a", window="w", dry_run=True)
    )
    assert port.calls[0].dry_run is True
    assert run.result.status is Status.PENDING  # 只报告不领取


def test_dry_run_invalid_for_non_provision():
    port = FakePort(result=RunResult(status=Status.CLAIMED))
    uc, _, _ = _usecase(port)
    check = Action(kind=ActionKind.HEALTH_CHECK, target="trae_cn")
    with pytest.raises(InvalidRequest):
        uc.execute(RunRequest(action=check, account_id="a", dry_run=True))


def test_provision_requires_window():
    uc, _, _ = _usecase(FakePort(result=RunResult(status=Status.CLAIMED)))
    with pytest.raises(InvalidRequest):
        uc.execute(RunRequest(action=CLAIM_ACTION, account_id="a"))  # 缺窗口


def test_unsupported_kind_rejected():
    uc = ExecuteAction(
        ledger=MemLedger(), sink=CollectSink(), ports=routing_ports({}, {})
    )
    with pytest.raises(UnsupportedAction):
        uc.execute(RunRequest(action=CLAIM_ACTION, account_id="a", window="w"))


def test_unsupported_target_rejected():
    """ADR-005：target 精确路由优先；未注册 target 的连接器显式拒绝。"""
    other = Action(kind=ActionKind.PROVISION_RUN, target="ghost")
    uc = ExecuteAction(
        ledger=MemLedger(), sink=CollectSink(), ports=routing_ports({}, {"qoder": FakePort()})
    )
    with pytest.raises(UnsupportedAction):
        uc.execute(RunRequest(action=other, account_id="a", window="w"))


def test_budget_preempts_slow_port():
    port = FakePort(result=RunResult(status=Status.CLAIMED), delay=0.5)
    uc, _, sink = _usecase(port)
    started = time.monotonic()
    run = uc.execute(
        RunRequest(
            action=CLAIM_ACTION,
            account_id="a",
            window="w",
            budget=timedelta(milliseconds=50),
        )
    )
    elapsed = time.monotonic() - started
    assert run.result.status is Status.FAILED
    assert "预算" in run.result.evidence[0].summary  # 如实上报，不静默截断
    assert elapsed < 0.4  # 立即停止等待，不等慢调用自然结束
    assert [e.type for e in sink.events] == [EventType.RUN_FINISHED]


def test_budget_generous_completes():
    port = FakePort(result=RunResult(status=Status.CLAIMED), delay=0.05)
    uc, _, _ = _usecase(port)
    run = uc.execute(
        RunRequest(
            action=CLAIM_ACTION,
            account_id="a",
            window="w",
            budget=timedelta(seconds=5),
        )
    )
    assert run.result.status is Status.CLAIMED


def test_unknown_code_becomes_failed_and_protocol_changed():
    port = FakePort(error=UnknownEngineCode("VOUCHER_GONE", "trae_dialect"))
    uc, _, sink = _usecase(port)
    run = uc.execute(RunRequest(action=CLAIM_ACTION, account_id="a", window="w"))
    assert run.result.status is Status.FAILED
    assert run.result.evidence[0].raw_code == "VOUCHER_GONE"  # 证据保留原始码
    assert [e.type for e in sink.events] == [
        EventType.RUN_FINISHED,
        EventType.PROTOCOL_CHANGED,
    ]
    assert sink.events[1].payload["raw_code"] == "VOUCHER_GONE"
    assert sink.events[1].payload["run_id"] == run.id


def test_port_exception_recorded_then_reraised():
    port = FakePort(error=RuntimeError("boom"))
    uc, ledger, sink = _usecase(port)
    with pytest.raises(RuntimeError):
        uc.execute(RunRequest(action=CLAIM_ACTION, account_id="a", window="w"))
    saved = list(ledger.runs.values())
    assert len(saved) == 1 and saved[0].result.status is Status.FAILED  # 台账必有记录
    assert [e.type for e in sink.events] == [EventType.RUN_FINISHED]


def test_readonly_kind_executes_every_time():
    port = FakePort(result=RunResult(status=Status.CLAIMED))
    uc, _, _ = _usecase(port)
    check = Action(kind=ActionKind.HEALTH_CHECK, target="trae_cn")
    req = RunRequest(action=check, account_id="a")
    uc.execute(req)
    uc.execute(req)
    assert len(port.calls) == 2  # 只读动作不去重


def test_invalid_budget_rejected():
    with pytest.raises(InvalidRequest):
        RunRequest(
            action=CLAIM_ACTION, account_id="a", window="w", budget=timedelta(0)
        )


def test_empty_account_rejected():
    with pytest.raises(InvalidRequest):
        RunRequest(action=CLAIM_ACTION, account_id="  ", window="w")
