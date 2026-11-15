"""R4 Meter（ADR-012 裁决 7）：UsageSample 不变量 + RecordUsageSample 用例。

- 口径：source 固定 gateway；tokens 优先读上游 usage 字段、缺失 = 0/0 不猜；
  duration_ms 记请求时长；输入非法显式抛（红线 5）
- 台账语义（A2-06 §2 不变量 1）：落库失败不影响主流程——审计留痕 + 返回 False
"""

from datetime import datetime, timezone

import pytest

from butler_core.usage.domain import UsageInvalid, UsageSample
from butler_core.usage.usecases.record_sample import RecordUsageSample

_T0 = datetime(2026, 11, 15, 8, 0, tzinfo=timezone.utc)


class _FakeStore:
    def __init__(self) -> None:
        self.samples: list[UsageSample] = []
        self.fail = False

    def append_sample(self, sample: UsageSample) -> None:
        if self.fail:
            raise RuntimeError("disk full")
        self.samples.append(sample)

    def list_samples(self, account_id=None, *, limit):
        return self.samples[:limit]


class _FakeAudit:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    def record(self, **kw) -> None:
        self.rows.append(kw)


def _sample(**over) -> UsageSample:
    base = dict(
        id="s1",
        account_id="acct",
        tokens_in=10,
        tokens_out=20,
        model="gpt-x",
        ts=_T0,
        source="gateway",
    )
    return UsageSample(**{**base, **over})


# ── UsageSample 领域不变量（A2-06 §2）──

def test_sample_defaults_and_accepts_valid() -> None:
    s = _sample()
    assert s.duration_ms is None  # 时长可缺省（None = 该来源无时长语义）
    assert s.source == "gateway"


def test_sample_rejects_bad_source() -> None:
    with pytest.raises(UsageInvalid, match="source 非法"):
        _sample(source="web")


def test_sample_rejects_negative_tokens_and_duration() -> None:
    with pytest.raises(UsageInvalid, match="token"):
        _sample(tokens_in=-1)
    with pytest.raises(UsageInvalid, match="token"):
        _sample(tokens_out=-5)
    with pytest.raises(UsageInvalid, match="duration_ms"):
        _sample(duration_ms=-0.1)


def test_sample_rejects_blank_model_and_account() -> None:
    with pytest.raises(UsageInvalid, match="model"):
        _sample(model="  ")
    with pytest.raises(UsageInvalid, match="account_id"):
        _sample(account_id="")


# ── RecordUsageSample 用例 ──

def _meter(store, audit, clock=lambda: _T0) -> RecordUsageSample:
    return RecordUsageSample(store=store, audit=audit, clock=clock)


def test_record_success_fixed_gateway_source() -> None:
    store, audit = _FakeStore(), _FakeAudit()
    assert _meter(store, audit).record(
        account_id="acct",
        model="m1",
        tokens_in=7,
        tokens_out=9,
        duration_ms=123.4,
    ) is True
    assert len(store.samples) == 1
    s = store.samples[0]
    assert s.source == "gateway"  # 裁决 7：网关入账固定来源
    assert s.id and s.ts == _T0  # id/ts 由用例产（clock 可注入）
    assert (s.tokens_in, s.tokens_out) == (7, 9)
    assert s.duration_ms == 123.4
    assert audit.rows == []  # 成功不写审计：样本本身就是持久事实


def test_record_missing_usage_records_zero_not_guess() -> None:
    """上游 usage 缺失：0/0 如实入账（请求级计数 = 样本条数），不猜 token 数。"""
    store, audit = _FakeStore(), _FakeAudit()
    assert _meter(store, audit).record(account_id="acct", model="m1") is True
    s = store.samples[0]
    assert (s.tokens_in, s.tokens_out) == (0, 0)


def test_record_store_failure_ledger_semantics() -> None:
    """落库失败：不影响主流程（返回 False），但审计必须留痕（不静默）。"""
    store, audit = _FakeStore(), _FakeAudit()
    store.fail = True
    assert _meter(store, audit).record(account_id="acct", model="m1") is False
    assert store.samples == []
    assert len(audit.rows) == 1
    row = audit.rows[0]
    assert row["actor"] == "gateway-meter"
    assert row["action"] == "meter.record"
    assert row["outcome"].startswith("error:")
    assert row["account_id"] == "acct"


def test_record_invalid_input_raises_no_audit() -> None:
    """输入非法 = 协议面 bug：UsageInvalid 上抛（红线 5），不落审计不落库。"""
    store, audit = _FakeStore(), _FakeAudit()
    with pytest.raises(UsageInvalid):
        _meter(store, audit).record(account_id="acct", model="m1", tokens_in=-1)
    assert store.samples == []
    assert audit.rows == []
