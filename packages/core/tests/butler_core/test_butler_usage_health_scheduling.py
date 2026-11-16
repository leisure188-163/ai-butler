"""用量域 / 健康域 / 调度域：谓词 oracle、样本不变量、窗口单源、待办去重。"""

from datetime import datetime, timedelta, timezone

import pytest

from butler_core.execution.domain import Action, ActionKind, Run, RunResult
from butler_core.execution.ports import RunLedger
from butler_core.health.domain import HealthLevel, credential_level
from butler_core.health.ports import HealthStateStore
from butler_core.health.usecases.health_scan import ScanCredentialExpiry
from butler_core.scheduling.domain import Trigger, TriggerKind, WindowInvalid, claim_window
from butler_core.scheduling.usecases.list_pending import ListPending
from butler_core.shared.events import EventSink, EventType
from butler_core.shared.results import Status
from butler_core.usage.domain import (
    PackageQuota,
    QUOTA_LOW_RATIO,
    UsageSample,
    UsageSnapshot,
    UsageInvalid,
    forecast_exhaustion,
    is_quota_low,
    quota_ratio,
)

NOW = datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc)


def _pkg(remaining, total=100, pid="p1"):
    return PackageQuota(package_id=pid, name="包", total=total, used=total - remaining,
                        remaining=remaining)


def test_quota_predicates_unchanged_oracle():
    assert is_quota_low(_pkg(20)) is True  # 恰好 20%
    assert is_quota_low(_pkg(0)) is False  # 已耗尽不算低
    assert is_quota_low(_pkg(50)) is False
    no_total = PackageQuota(package_id="p0", name="包", total=0, used=0, remaining=10)
    assert is_quota_low(no_total) is False  # 无总额信息不猜
    assert quota_ratio(_pkg(25)) == 0.25
    assert QUOTA_LOW_RATIO == 0.2


def test_forecast_needs_two_frames_and_gap():
    prev = UsageSnapshot(id="s1", account_id="a", target="trae_cn",
                         collected_at=NOW - timedelta(days=1), packages=(_pkg(80),))
    cur = UsageSnapshot(id="s2", account_id="a", target="trae_cn",
                        collected_at=NOW, packages=(_pkg(60),))
    out = forecast_exhaustion(prev, cur)
    assert len(out) == 1 and out[0].per_day == 20 and out[0].days_left == 3
    assert forecast_exhaustion(None, cur) == ()
    close = UsageSnapshot(id="s3", account_id="a", target="trae_cn",
                          collected_at=NOW + timedelta(minutes=1), packages=(_pkg(50),))
    assert forecast_exhaustion(cur, close) == ()  # 帧距 <1h 不外推


def test_usage_sample_requires_source():
    with pytest.raises(UsageInvalid):
        UsageSample(id="x", account_id="a", tokens_in=1, tokens_out=2,
                    model="m", ts=NOW, source="unknown")
    sample = UsageSample(id="x", account_id="a", tokens_in=1, tokens_out=2,
                         model="m", ts=NOW, source="gateway")
    assert sample.source == "gateway"


def test_health_level_is_pure_function():
    assert credential_level(None, NOW, warn_window_days=3) is HealthLevel.HEALTHY
    assert credential_level(NOW - timedelta(seconds=1), NOW, warn_window_days=3) is HealthLevel.EXPIRED
    assert credential_level(NOW + timedelta(days=1), NOW, warn_window_days=3) is HealthLevel.EXPIRING
    assert credential_level(NOW + timedelta(days=10), NOW, warn_window_days=3) is HealthLevel.HEALTHY


class _Vault:
    def __init__(self, healths):
        self._healths = healths

    def health(self):
        return self._healths


class _Sink(EventSink):
    def __init__(self):
        self.events = []

    def publish(self, event):
        self.events.append(event)


class _States(HealthStateStore):
    def __init__(self):
        self.cred = {}

    def get_credential_notified_level(self, account_id, kind):
        return self.cred.get((account_id, kind))

    def set_credential_notified_level(self, account_id, kind, level):
        self.cred[(account_id, kind)] = level.value

    def get_account_level(self, account_id):
        return None

    def set_account_level(self, account_id, level):
        pass


class _Cred:
    def __init__(self, account_id, kind, expires_at):
        self.account_id = account_id
        self.kind = kind
        self.expires_at = expires_at


def test_expiry_scan_emits_badge_and_dedups():
    vault = _Vault([_Cred("a", "cookie", NOW + timedelta(days=1))])
    sink, states = _Sink(), _States()
    uc = ScanCredentialExpiry(vault=vault, sink=sink, states=states, clock=lambda: NOW)
    first = uc.execute()
    assert len(first) == 1 and first[0].type is EventType.CREDENTIAL_EXPIRING
    assert uc.execute() == []  # 同级别不重发


def test_claim_window_and_trigger_validation():
    # refresh_at 按本机墙钟解读：用本地 9/11 点避开时区差
    assert claim_window(datetime(2026, 11, 14, 9, 0).astimezone(), "10:00") == "2026-11-13"
    assert claim_window(datetime(2026, 11, 14, 11, 0).astimezone(), "10:00") == "2026-11-14"
    with pytest.raises(WindowInvalid):
        claim_window(NOW, "25:00")
    trigger = Trigger(kind=TriggerKind.CRON, key="daily", target="trae_cn")
    assert trigger.enabled and trigger.account_key == "main"
    with pytest.raises(WindowInvalid):
        Trigger(kind=TriggerKind.EVENT, key="", target="trae_cn")


class _Ledger(RunLedger):
    def __init__(self, rows):
        self.rows = rows

    def save(self, run):
        pass

    def find_by_idempotency_key(self, key):
        return None

    def list_for_account(self, account_id, *, limit):
        return []

    def list_recent(self, *, limit):
        return self.rows


def test_list_pending_dedups_by_idempotency_key():
    action = Action(kind=ActionKind.PROVISION_RUN, target="trae_cn")
    run = Run(id="r1", action=action, account_id="a", idempotency_key="k1")
    run.finish(RunResult(status=Status.NO_AUTH))
    duplicate = Run(id="r2", action=action, account_id="a", idempotency_key="k1")
    duplicate.finish(RunResult(status=Status.EXPIRED))
    assert len(ListPending(ledger=_Ledger([run, duplicate])).execute()) == 1


def test_list_pending_latest_result_supersedes_older_failure():
    """最新已恢复 → 旧 NO_AUTH 不再挂待办（修好后待办必须消失，ADR-015）。"""
    action = Action(kind=ActionKind.PROVISION_RUN, target="trae_cn")
    old = Run(id="old", action=action, account_id="a", idempotency_key="k1")
    old.finish(RunResult(status=Status.NO_AUTH))
    fixed = Run(id="fixed", action=action, account_id="a", idempotency_key="k2")
    fixed.finish(RunResult(status=Status.CLAIMED))
    assert ListPending(ledger=_Ledger([fixed, old])).execute() == []


def test_list_pending_latest_attention_is_kept():
    """最新仍是 attention → 保留最新一条，不显示更旧的同类失败。"""
    action = Action(kind=ActionKind.PROVISION_RUN, target="qoder_cn")
    older = Run(id="older", action=action, account_id="q", idempotency_key="k1")
    older.finish(RunResult(status=Status.NO_AUTH))
    latest = Run(id="latest", action=action, account_id="q", idempotency_key="k2")
    latest.finish(RunResult(status=Status.NO_AUTH))
    rows = ListPending(ledger=_Ledger([latest, older])).execute()
    assert [r.id for r in rows] == ["latest"]
