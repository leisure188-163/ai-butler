"""A4-01 §1/§2：Vault 领域模型 + 健康评定用例基线（core 侧）。

- Secret 全链路脱敏（红线级安全不变量）
- ScanCredentialExpiry：变更才产事件 / 恢复清记忆不产事件 / 不重发
- AssessAccountHealth：五级优先级（risk > expired > invalid > expiring > healthy）
"""

from datetime import datetime, timedelta, timezone

import pytest

from butler_core.shared.events import EventSink
from butler_core.health.ports import HealthStateStore
from butler_core.execution.ports import RunLedger
from butler_core.accounts.ports import VaultPort
from butler_core.health.usecases.health_scan import AssessAccountHealth, ScanCredentialExpiry
from butler_core.execution.domain import Action, ActionKind
from butler_core.shared.events import EventType, Severity
from butler_core.health.domain import HealthLevel, account_repair_hint, credential_level
from butler_core.shared.results import Status
from butler_core.execution.domain import Run, RunResult
from butler_core.accounts.domain import CredentialHealth, Secret, vault_ref

_T0 = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)


def _clock_at(t0: datetime):
    return lambda: t0


# --- Secret：脱敏是安全不变量 ---


def test_secret_redacts_repr_and_str():
    s = Secret("plain-hunter2")
    assert "[REDACTED]" in repr(s)
    assert str(s) == "[REDACTED]"
    assert "hunter2" not in repr(s) and "hunter2" not in str(s)


def test_secret_expose_only_way_out():
    assert Secret("p").expose() == "p"


def test_empty_secret_rejected():
    from butler_core.accounts.domain import EmptySecret

    with pytest.raises(EmptySecret):
        Secret("")


def test_vault_ref_requires_clean_parts():
    assert vault_ref("acc1", "cookie") == "acc1:cookie"
    with pytest.raises(Exception):
        vault_ref(" ", "cookie")
    with pytest.raises(Exception):
        vault_ref("acc1", "  ")


def test_credential_level_by_expiry():
    day = timedelta(days=1)
    assert credential_level(None, _T0, warn_window_days=3) is HealthLevel.HEALTHY
    assert (
        credential_level(_T0 + 4 * day, _T0, warn_window_days=3) is HealthLevel.HEALTHY
    )
    assert (
        credential_level(_T0 + 3 * day, _T0, warn_window_days=3) is HealthLevel.EXPIRING
    )
    assert credential_level(_T0 + day, _T0, warn_window_days=3) is HealthLevel.EXPIRING
    assert (
        credential_level(_T0 - timedelta(seconds=1), _T0, warn_window_days=3)
        is HealthLevel.EXPIRED
    )
    assert (
        credential_level(_T0 - 30 * day, _T0, warn_window_days=3) is HealthLevel.EXPIRED
    )


def test_account_repair_hint_copy_from_core():
    assert account_repair_hint(HealthLevel.EXPIRED) == "重新打开客户端登录"  # A4-01 §2 字面
    assert account_repair_hint(HealthLevel.INVALID) == "打开登录页"
    assert account_repair_hint(HealthLevel.EXPIRING) is None
    assert account_repair_hint(HealthLevel.HEALTHY) is None


def test_health_level_signal_buckets():
    """UI 染色分类 core 单源（A3-01 §4）：端不认识 level 字面量本身。"""
    assert HealthLevel.HEALTHY.signal == "ok"
    assert HealthLevel.EXPIRING.signal == "notice"
    assert HealthLevel.EXPIRED.signal == "attention"
    assert HealthLevel.INVALID.signal == "attention"
    assert HealthLevel.RISK.signal == "danger"


# --- 假件（进程内，零 mock IO，R8）---


class FakeVault(VaultPort):
    def __init__(self, creds: list[CredentialHealth], *, revoke_result: int = 0):
        self._creds = creds
        self.revoke_result = revoke_result
        self.revoked: list[tuple[str, str]] = []

    def store(self, a, k, s, *, expires_at=None, backend=None):
        raise NotImplementedError

    def load(self, a, kinds):
        raise NotImplementedError

    def rotate(self, a, k, s, *, expires_at=None):
        raise NotImplementedError

    def revoke(self, account_id, *, reason):
        self.revoked.append((account_id, reason))
        return self.revoke_result

    def purge(self, account_id):
        return 0

    def health(self):
        return self._creds


class FakeLedger(RunLedger):
    def __init__(self, runs: list):
        self._runs = runs

    def save(self, run):
        raise NotImplementedError

    def find_by_idempotency_key(self, key):
        raise NotImplementedError

    def list_for_account(self, account_id, *, limit):
        return [
            run
            for run in self._runs
            if run.account_id == account_id
        ][:limit]

    def list_recent(self, *, limit):
        return self._runs[:limit]


class MemStates(HealthStateStore):
    def __init__(self):
        self._data: dict[str, str] = {}

    def get_credential_notified_level(self, a, k):
        return self._data.get(f"cred:{a}:{k}")

    def set_credential_notified_level(self, a, k, level):
        self._data[f"cred:{a}:{k}"] = level.value

    def get_account_level(self, a):
        return HealthLevel(self._data[f"acct:{a}"]) if f"acct:{a}" in self._data else None

    def set_account_level(self, a, level):
        self._data[f"acct:{a}"] = level.value


class CollectSink(EventSink):
    def __init__(self):
        self.events = []

    def publish(self, event):
        self.events.append(event)


def _run(account: str, status: Status, seq: int) -> "Run":
    run = Run(
        id=f"run{seq}",
        action=Action(kind=ActionKind.HEALTH_CHECK, target="trae_cn"),
        account_id=account,
        idempotency_key="",
    )
    run.finish(RunResult(status=status))
    return run


# --- ScanCredentialExpiry ---


def test_scan_publishes_expiring_and_expired_once():
    vault = FakeVault(
        [
            CredentialHealth(account_id="a", kind="cookie", expires_at=_T0 + timedelta(days=2)),
            CredentialHealth(account_id="a", kind="token", expires_at=_T0 - timedelta(days=1)),
        ]
    )
    states, sink = MemStates(), CollectSink()
    scan = ScanCredentialExpiry(
        vault=vault, sink=sink, states=states, clock=_clock_at(_T0)
    )
    events = scan.execute()
    assert [e.type for e in events] == [
        EventType.CREDENTIAL_EXPIRING,
        EventType.CREDENTIAL_EXPIRED,
    ]

    # 重复扫描同状态：不再重发（防每日 job 刷屏）
    assert scan.execute() == []

    # 恢复（有效期被轮换刷新）：只清记忆，不产恢复事件
    vault2 = FakeVault(
        [CredentialHealth(account_id="a", kind="cookie", expires_at=_T0 + timedelta(days=90))]
    )
    scan2 = ScanCredentialExpiry(
        vault=vault2, sink=sink, states=states, clock=_clock_at(_T0)
    )
    assert scan2.execute() == []


def test_scan_skips_revoked_credentials():
    hp = CredentialHealth.build(
        account_id="a", kind="cookie", expires_at=_T0 - timedelta(days=1),
        revoked_at=_T0, revoked_reason="登录态失效", clock=_clock_at(_T0),
    )
    sink, states = CollectSink(), MemStates()
    ScanCredentialExpiry(
        vault=FakeVault([hp]), sink=sink, states=states, clock=_clock_at(_T0)
    ).execute()
    assert sink.events == []  # 已撤销副本不再报到/到期事件（ADR-016）


def test_scan_event_carries_kind_and_expiry():
    hp = CredentialHealth(account_id="a", kind="cookie", expires_at=_T0 - timedelta(days=5))
    sink, states = CollectSink(), MemStates()
    ScanCredentialExpiry(
        vault=FakeVault([hp]), sink=sink, states=states, clock=_clock_at(_T0)
    ).execute()
    event = sink.events[0]
    assert event.type is EventType.CREDENTIAL_EXPIRED
    assert event.severity is Severity.BADGE  # 预警=徽标，不 push
    assert event.payload["kind"] == "cookie"
    assert event.account_id == "a"


# --- AssessAccountHealth ---


def _run_at(account: str, status: Status, seq: int, at: datetime) -> "Run":
    run = Run(
        id=f"run{seq}",
        action=Action(kind=ActionKind.HEALTH_CHECK, target="trae_cn"),
        account_id=account,
        idempotency_key="",
        started_at=at,
    )
    run.finish(RunResult(status=status), at=at)
    return run


def _assess(creds, runs, states):
    sink = CollectSink()
    uc = AssessAccountHealth(
        vault=FakeVault(list(creds)),
        ledger=FakeLedger(runs),
        sink=sink,
        states=states,
        clock=_clock_at(_T0),
    )
    return uc, sink


def test_failures_before_restore_do_not_count_against_new_credential():
    """重新停靠后，旧凭据时代的 NO_AUTH 不再拖累新凭据。"""
    hp = CredentialHealth.build(
        account_id="a", kind="cookie", expires_at=_T0 + timedelta(days=30),
        stored_at=_T0 + timedelta(hours=1), clock=_clock_at(_T0),
    )
    runs = [
        _run_at("a", Status.NO_AUTH, 4, _T0 - timedelta(hours=2)),
        _run_at("a", Status.NO_AUTH, 3, _T0 - timedelta(hours=1)),
        _run_at("a", Status.NO_AUTH, 2, _T0),
    ]
    states = MemStates()
    uc, _ = _assess([hp], runs, states)
    health = uc.execute("a")
    assert health.level is HealthLevel.HEALTHY  # 旧连败属于旧凭据时代
    assert uc.vault.revoked == []  # 新副本不能被旧账撤销


def test_failure_after_restore_counts_and_revokes():
    hp = CredentialHealth.build(
        account_id="a", kind="cookie", expires_at=_T0 + timedelta(days=30),
        stored_at=_T0 + timedelta(hours=1), clock=_clock_at(_T0),
    )
    runs = [
        _run_at("a", Status.NO_AUTH, 2, _T0 + timedelta(hours=2)),
        _run_at("a", Status.NO_AUTH, 1, _T0),
    ]
    states = MemStates()
    uc, _ = _assess([hp], runs, states)
    health = uc.execute("a")
    assert health.level is HealthLevel.INVALID  # 新副本确实又失败了一次
    assert uc.vault.revoked[0][0] == "a"


def test_healthy_when_no_evidence():
    states = MemStates()
    uc, sink = _assess([], [], states)
    health = uc.execute("a")
    assert health.level is HealthLevel.HEALTHY
    assert health.repair_hint is None
    # 首评 healthy：变更检测空转，无事件
    assert sink.events == []


def test_single_no_auth_is_invalid_with_hint():
    states = MemStates()
    runs = [_run("a", Status.NO_AUTH, 2), _run("a", Status.CLAIMED, 1)]
    uc, sink = _assess([], runs, states)
    health = uc.execute("a")
    assert health.level is HealthLevel.INVALID
    assert health.repair_hint == "打开登录页"
    assert sink.events[0].severity is Severity.PUSH  # 阻塞性事实升级 push（ADR-015）
    assert uc.vault.revoked[0][0] == "a"  # 失效即撤销本地副本（ADR-016）


def test_three_streak_is_risk_with_push():
    states = MemStates()
    runs = [
        _run("a", Status.NO_AUTH, 4),
        _run("a", Status.NO_AUTH, 3),
        _run("a", Status.NO_AUTH, 2),
        _run("a", Status.CLAIMED, 1),
    ]
    uc, sink = _assess([], runs, states)
    health = uc.execute("a")
    assert health.level is HealthLevel.RISK
    assert health.repair_hint is not None
    assert sink.events[0].severity is Severity.PUSH  # 封号风险 push（A4-01 §2）
    assert uc.vault.revoked[0][0] == "a"  # NO_AUTH 连败判出的 risk 同样撤销副本


def test_broken_streak_resets():
    runs = [_run("a", Status.NO_AUTH, 4), _run("a", Status.CLAIMED, 3),
            _run("a", Status.NO_AUTH, 2)]
    states = MemStates()
    uc, _ = _assess([], runs, states)
    assert uc.execute("a").level is HealthLevel.INVALID  # 非连续不成 risk


def test_expired_credential_outranks_invalid():
    # 连败 1 次（invalid）+ 凭据已过期（expired）→ expired 优先，risk 未触发
    runs = [_run("a", Status.NO_AUTH, 1)]
    hp = CredentialHealth.build(
        account_id="a", kind="cookie", expires_at=_T0 - timedelta(days=1),
        clock=_clock_at(_T0),
    )
    states = MemStates()
    uc, _ = _assess([hp], runs, states)
    health = uc.execute("a")
    assert health.level is HealthLevel.EXPIRED
    assert any("cookie" in e for e in health.evidence)
    assert uc.vault.revoked[0][0] == "a"  # 到期同样撤销本地副本


def test_revoked_credential_is_evidence_not_expiry():
    """ADR-016：已撤销副本只作证据，不再用它的有效期把账户判成 expired。"""
    runs = [_run("a", Status.NO_AUTH, 1)]
    hp = CredentialHealth.build(
        account_id="a",
        kind="cookie",
        expires_at=_T0 - timedelta(days=1),
        revoked_at=_T0,
        revoked_reason="登录态失效",
        clock=_clock_at(_T0),
    )
    states = MemStates()
    uc, _ = _assess([hp], runs, states)
    health = uc.execute("a")
    assert health.level is HealthLevel.INVALID  # 连败 1 次；revoked 不再贡献 expired
    assert any("本地副本已撤销" in e for e in health.evidence)


def test_all_revoked_credentials_are_invalid_not_healthy():
    """副本全撤销 = 当前无机可用，不能因为没有连败就报 healthy。"""
    hp = CredentialHealth.build(
        account_id="a", kind="cookie", expires_at=_T0 + timedelta(days=30),
        revoked_at=_T0, revoked_reason="登录态失效", clock=_clock_at(_T0),
    )
    states = MemStates()
    uc, _ = _assess([hp], [], states)
    health = uc.execute("a")
    assert health.level is HealthLevel.INVALID
    assert any("全部撤销" in e for e in health.evidence)


def test_revoke_success_is_reported_in_evidence():
    states, sink = MemStates(), CollectSink()
    uc = AssessAccountHealth(
        vault=FakeVault([], revoke_result=2),
        ledger=FakeLedger([_run("a", Status.NO_AUTH, 1)]),
        sink=sink,
        states=states,
        clock=_clock_at(_T0),
    )
    health = uc.execute("a")
    assert health.level is HealthLevel.INVALID
    assert any("已自动撤销 butler 本地凭据副本 2 项" in e for e in health.evidence)


def test_expiring_only_is_badge_not_push():
    hp = CredentialHealth.build(
        account_id="a", kind="token", expires_at=_T0 + timedelta(days=2),
        clock=_clock_at(_T0),
    )
    states = MemStates()
    uc, sink = _assess([hp], [], states)
    health = uc.execute("a")
    assert health.level is HealthLevel.EXPIRING
    assert health.repair_hint is None
    assert sink.events[0].severity is Severity.BADGE


def test_account_level_change_detection_no_resend():
    runs = [_run("a", Status.NO_AUTH, 1)]
    states = MemStates()
    uc, sink = _assess([], runs, states)
    first = uc.execute("a")
    assert first.level is HealthLevel.INVALID
    second = uc.execute("a")  # 同状态重评
    assert second.level is first.level
    assert [e.type for e in sink.events] == [EventType.ACCOUNT_HEALTH_CHANGED]  # 只发一次


def test_recovery_to_healthy_is_silent_event():
    runs = [_run("a", Status.NO_AUTH, 1)]
    states = MemStates()
    uc, sink = _assess([], runs, states)
    uc.execute("a")
    uc.ledger = FakeLedger([_run("a", Status.CLAIMED, 1)])  # 登录修复
    health = uc.execute("a")
    assert health.level is HealthLevel.HEALTHY
    assert sink.events[-1].severity is Severity.SILENT  # 恢复零打扰
