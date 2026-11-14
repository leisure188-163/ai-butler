"""R2-A：用量三实体 + UsagePort 端口 + CollectUsage 用例（块①设计，TDD）。

- PackageQuota / UsageSnapshot / UsageAggregate / QuotaLedgerEntry：领域校验
- quota_ratio / is_quota_low：QUOTA_LOW 谓词（阈值 core 单源，端零映射）
- forecast_exhaustion：相邻快照差分耗尽预测（不足两帧 = 空预测，UI 显「采集中」）
- CollectUsage：端口选路 + 落库 + QUOTA_LOW 变更才产事件（首评异常也发）+
  单家失败不拖累（outcome.error 如实上报，绝不静默也绝不打断编排）
"""

from datetime import datetime, timedelta, timezone

import pytest

from butler_core.usage.ports import UsageRequest
from butler_core.usage.usecases.collect_usage import CollectUsage, CollectOutcome
from butler_core.shared.events import EventType, Severity
from butler_core.usage.domain import PackageQuota, QuotaLedgerEntry, UsageAggregate, UsageResult, UsageSnapshot, forecast_exhaustion, is_quota_low, quota_ratio

_T0 = datetime(2026, 11, 12, 12, 0, tzinfo=timezone.utc)


def _pkg(**over) -> PackageQuota:
    base = dict(
        package_id="p1",
        name="签到包",
        total=100.0,
        used=90.0,
        remaining=10.0,
        unit="credits",
        cycle_end=None,
        status="ACTIVE",
    )
    base.update(over)
    return PackageQuota(**base)


def _snap(packages, *, at=_T0, account_id="trae_cn:main", target="trae_cn") -> UsageSnapshot:
    return UsageSnapshot(
        id=f"snap-{at.timestamp()}",
        account_id=account_id,
        target=target,
        collected_at=at,
        packages=tuple(packages),
    )


# --- 领域校验 ---


def test_package_quota_rejects_empty_id_and_negative():
    with pytest.raises(Exception):
        _pkg(package_id=" ")
    with pytest.raises(Exception):
        _pkg(remaining=-1.0)
    with pytest.raises(Exception):
        _pkg(total=-1.0)


def test_quota_ratio_and_low_predicate():
    assert quota_ratio(_pkg(remaining=10, total=100)) == pytest.approx(0.1)
    assert quota_ratio(_pkg(total=0)) is None  # 无总额信息 → 谓词不猜
    assert is_quota_low(_pkg(remaining=20, total=100))  # ≤20%（边界含）
    assert not is_quota_low(_pkg(remaining=21, total=100))
    assert not is_quota_low(_pkg(total=0, remaining=0))  # 无信息不算低


def test_exhausted_package_is_not_quota_low():
    """2026-11-12 真机回归：trae/workbuddy 几十个历史耗尽包（remaining=0）全命中
    低额 → 告警被噪音淹没。耗尽是终态事实（签到/裂变历史包永不恢复），没有
    行动价值——已耗尽 ≠ 低额（QUOTA_LOW 的语义是「快用完了，该行动了」）。"""
    assert not is_quota_low(_pkg(remaining=0, total=100))
    assert not is_quota_low(_pkg(remaining=0.0, total=5.0))


def test_ledger_entry_rejects_empty_record_and_negative_amount():
    with pytest.raises(Exception):
        QuotaLedgerEntry(record_id="", account_id="a", target="t", amount=1, unit="POINT")
    with pytest.raises(Exception):
        QuotaLedgerEntry(record_id="r1", account_id="a", target="t", amount=-1, unit="POINT")


def test_usage_request_rejects_blank():
    with pytest.raises(Exception):
        UsageRequest(target=" ", account_id="a", deadline=_T0)
    with pytest.raises(Exception):
        UsageRequest(target="t", account_id="", deadline=_T0)


def test_usage_result_three_segments_nullable():
    r = UsageResult()
    assert r.snapshot is None and r.aggregate is None and r.ledger is None
    # ledger 三态：None=通道不可得；()=取到了但本期无新流水
    assert UsageResult(ledger=()).ledger == ()


# --- 耗尽预测：相邻快照差分 ---


def test_forecast_needs_two_frames():
    cur = _snap([_pkg(remaining=50)])
    assert forecast_exhaustion(None, cur) == ()  # 不足两帧 → 空预测（UI 显「采集中」）


def test_forecast_diff_rate_and_exhausted_on():
    t0 = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)
    prev = _snap([_pkg(remaining=100)], at=t0)
    cur = _snap([_pkg(remaining=50)], at=_T0)  # 2 天用 50 → 25/天 → 2 天耗尽
    fc = forecast_exhaustion(prev, cur)
    assert len(fc) == 1
    assert fc[0].per_day == pytest.approx(25.0)
    assert fc[0].days_left == pytest.approx(2.0)
    assert fc[0].exhausted_on == datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc).date()


def test_forecast_recharge_is_not_exhausting():
    prev = _snap([_pkg(remaining=10)], at=_T0 - timedelta(days=1))
    cur = _snap([_pkg(remaining=50)], at=_T0)  # 在回血 → 不预测耗尽
    fc = forecast_exhaustion(prev, cur)
    assert fc[0].per_day < 0
    assert fc[0].days_left is None and fc[0].exhausted_on is None


def test_forecast_skips_new_packages():
    prev = _snap([_pkg(package_id="old", remaining=10)], at=_T0 - timedelta(days=1))
    cur = _snap([_pkg(package_id="new", remaining=5)], at=_T0)
    assert forecast_exhaustion(prev, cur) == ()


def test_forecast_requires_minimum_frame_gap():
    """2026-11-12 真机回归：启动补采 + 手动采集仅隔几分钟 → 差分外推爆炸
    （per_day 上万、「今天耗尽」）。太新鲜的两帧不可信 → 仍按「采集中」。"""
    prev = _snap([_pkg(remaining=2000)], at=_T0)
    cur = _snap([_pkg(remaining=1500)], at=_T0 + timedelta(minutes=5))
    assert forecast_exhaustion(prev, cur) == ()


# --- CollectUsage：端口选路 + 落库 + 事件 ---


class _FakeStore:
    """内存 UsageStore：save 全收，list 按时间新→旧。"""

    def __init__(self) -> None:
        self.snapshots: list[UsageSnapshot] = []
        self.aggregates: list[UsageAggregate] = []
        self.ledger: list[QuotaLedgerEntry] = []

    def save_snapshot(self, s: UsageSnapshot) -> None:
        self.snapshots.append(s)

    def list_snapshots(self, account_id: str, *, limit: int) -> list[UsageSnapshot]:
        rows = [s for s in self.snapshots if s.account_id == account_id]
        return sorted(rows, key=lambda s: s.collected_at, reverse=True)[:limit]

    def save_aggregate(self, a: UsageAggregate) -> None:
        self.aggregates.append(a)

    def latest_aggregate(self, account_id: str) -> UsageAggregate | None:
        rows = sorted(
            (a for a in self.aggregates if a.account_id == account_id),
            key=lambda a: a.collected_at,
            reverse=True,
        )
        return rows[0] if rows else None

    def append_ledger(self, entries) -> int:
        known = {e.record_id for e in self.ledger}
        fresh = [e for e in entries if e.record_id not in known]
        self.ledger.extend(fresh)
        return len(fresh)

    def list_ledger(self, account_id: str, *, limit: int) -> list[QuotaLedgerEntry]:
        rows = [e for e in self.ledger if e.account_id == account_id]
        return rows[:limit]


class _FakeSink:
    def __init__(self) -> None:
        self.events = []

    def publish(self, event) -> None:
        self.events.append(event)


class _Port:
    def __init__(self, result=None, *, exc: Exception | None = None) -> None:
        self._result = result
        self._exc = exc
        self.calls: list[UsageRequest] = []

    def collect(self, req: UsageRequest):
        self.calls.append(req)
        if self._exc is not None:
            raise self._exc
        return self._result


def _result(snapshot=None, aggregate=None, ledger=None) -> UsageResult:
    return UsageResult(snapshot=snapshot, aggregate=aggregate, ledger=ledger)


_LOW_PKG = _pkg(remaining=10, total=100)  # 10% ≤ 20% → low
_OK_PKG = _pkg(package_id="p2", name="月度包", remaining=80, total=100)


def test_collect_happy_path_persists_all_segments():
    store, sink = _FakeStore(), _FakeSink()
    port = _Port(
        _result(
            snapshot=_snap([_OK_PKG]),
            aggregate=UsageAggregate(
                id="ag1", account_id="trae_cn:main", target="trae_cn",
                collected_at=_T0, summary={"consumed_amount": 55},
            ),
            ledger=(
                QuotaLedgerEntry(
                    record_id="r1", account_id="trae_cn:main", target="trae_cn",
                    amount=200, unit="POINT", occurred_at=_T0, kind="签到",
                ),
            ),
        )
    )
    uc = CollectUsage(
        ports={"trae_cn": port}, store=store, sink=sink, clock=lambda: _T0
    )
    outcome = uc.execute("trae_cn", "trae_cn:main")
    assert isinstance(outcome, CollectOutcome)
    assert outcome.error is None
    assert outcome.snapshot_saved and outcome.aggregate_saved
    assert outcome.ledger_saved == 1
    assert len(store.snapshots) == 1 and len(store.aggregates) == 1
    assert port.calls[0].account_id == "trae_cn:main"
    assert port.calls[0].deadline > _T0  # 预算硬边界：deadline 在未来


def test_collect_ledger_dedup_by_record_id():
    store, sink = _FakeStore(), _FakeSink()
    entry = lambda: (  # noqa: E731
        QuotaLedgerEntry(
            record_id="r1", account_id="trae_cn:main", target="trae_cn",
            amount=200, unit="POINT", occurred_at=_T0, kind="签到",
        ),
    )
    port = _Port(_result(ledger=entry()))
    uc = CollectUsage(
        ports={"trae_cn": port}, store=store, sink=sink, clock=lambda: _T0
    )
    assert uc.execute("trae_cn", "trae_cn:main").ledger_saved == 1
    assert uc.execute("trae_cn", "trae_cn:main").ledger_saved == 0


def test_collect_missing_port_reports_error_not_raise():
    store, sink = _FakeStore(), _FakeSink()
    outcome = CollectUsage(
        ports={}, store=store, sink=sink, clock=lambda: _T0
    ).execute("trae_cn", "trae_cn:main")
    assert outcome.error is not None
    assert not outcome.snapshot_saved


def test_collect_port_crash_reports_error_not_raise():
    store, sink = _FakeStore(), _FakeSink()
    port = _Port(exc=RuntimeError("网络断了"))
    uc = CollectUsage(
        ports={"trae_cn": port}, store=store, sink=sink, clock=lambda: _T0
    )
    outcome = uc.execute("trae_cn", "trae_cn:main")
    assert outcome.error is not None and "网络断了" in outcome.error
    assert not outcome.snapshot_saved


def test_collect_quota_low_transition_emits_event_once():
    store, sink = _FakeStore(), _FakeSink()
    port = _Port()
    uc = CollectUsage(
        ports={"trae_cn": port}, store=store, sink=sink, clock=lambda: _T0
    )

    # 第一帧：p1 已低（首评即异常 → 发事件）
    port._result = _result(snapshot=_snap([_LOW_PKG, _OK_PKG], at=_T0))
    first = uc.execute("trae_cn", "trae_cn:main")
    assert first.quota_low == ("签到包",)
    assert len(sink.events) == 1
    ev = sink.events[0]
    assert ev.type is EventType.QUOTA_LOW and ev.severity is Severity.BADGE
    assert ev.account_id == "trae_cn:main"

    # 第二帧：p1 仍然低 → 变更检测不重发
    port._result = _result(snapshot=_snap([_LOW_PKG, _OK_PKG], at=_T0 + timedelta(days=1)))
    second = uc.execute("trae_cn", "trae_cn:main")
    assert second.quota_low == ()
    assert len(sink.events) == 1

    # 第三帧：p1 回到 50% → 恢复不产事件（A2-01 §5 无恢复事件类型）
    recovered = _snap([_pkg(remaining=50, total=100), _OK_PKG], at=_T0 + timedelta(days=2))
    port._result = _result(snapshot=recovered)
    third = uc.execute("trae_cn", "trae_cn:main")
    assert third.quota_low == ()
    assert len(sink.events) == 1

    # 第四帧：又跌回低 → 新事实再发
    port._result = _result(snapshot=_snap([_LOW_PKG, _OK_PKG], at=_T0 + timedelta(days=3)))
    fourth = uc.execute("trae_cn", "trae_cn:main")
    assert fourth.quota_low == ("签到包",)
    assert len(sink.events) == 2


def test_collect_event_payload_carries_numbers_as_strings():
    store, sink = _FakeStore(), _FakeSink()
    port = _Port(_result(snapshot=_snap([_LOW_PKG], at=_T0)))
    CollectUsage(
        ports={"trae_cn": port}, store=store, sink=sink, clock=lambda: _T0
    ).execute("trae_cn", "trae_cn:main")
    payload = sink.events[0].payload
    assert all(isinstance(v, str) for v in payload.values())  # Event.payload 契约
    assert payload["package_id"] == "p1"
    assert payload["ratio"] == "0.10"
