"""R2-B：bridge 装配用量回路（register_usage_ports → collect_usage → 落库/事件）。"""

from datetime import datetime, timedelta, timezone

from kabao_core.application.ports import UsageRequest
from kabao_core.domain.event import EventType
from kabao_core.domain.usage import (
    PackageQuota,
    QuotaLedgerEntry,
    UsageResult,
    UsageSnapshot,
)
from kabao_core.domain.vault import Secret
from kabao_engine.bridge import build_engine

_T0 = datetime(2026, 11, 12, 12, 0, tzinfo=timezone.utc)


class FakeUsagePort:
    def __init__(self, result: UsageResult) -> None:
        self._result = result
        self.calls: list[UsageRequest] = []

    def collect(self, req: UsageRequest) -> UsageResult:
        self.calls.append(req)
        return self._result


def _snap(account: str, target: str, remaining: float = 10.0) -> UsageSnapshot:
    return UsageSnapshot(
        id=f"snap-{target}-{remaining}",
        account_id=account,
        target=target,
        collected_at=_T0,
        packages=(
            PackageQuota(
                package_id="p1", name="签到包", total=100.0, used=100.0 - remaining,
                remaining=remaining, unit="credits",
            ),
        ),
    )


def test_bridge_usage_wiring(tmp_path):
    kit = build_engine(tmp_path / "kabao.db")
    port = FakeUsagePort(
        UsageResult(
            snapshot=_snap("trae_cn:main", "trae_cn"),
            ledger=(
                QuotaLedgerEntry(
                    record_id="r1", account_id="trae_cn:main", target="trae_cn",
                    amount=200, unit="POINT", occurred_at=_T0, kind="签到",
                ),
            ),
        )
    )
    kit.register_usage_ports(targets={"trae_cn": port})

    outcome = kit.collect_usage.execute("trae_cn", "trae_cn:main")
    assert outcome.snapshot_saved and outcome.ledger_saved == 1
    assert outcome.quota_low == ("签到包",)  # 首评 10% 低 → 事件

    kit.bus.drain()
    assert len(kit.notify.items) == 1
    assert kit.notify.items[0].type is EventType.QUOTA_LOW

    # 台账读回：快照 + 流水都在库（跨 kit 重启可查）
    kit.close()
    kit2 = build_engine(tmp_path / "kabao.db")
    assert len(kit2.usage_store.list_snapshots("trae_cn:main", limit=10)) == 1
    assert len(kit2.usage_store.list_ledger("trae_cn:main", limit=10)) == 1
    # 重启后重挂同端口对象 = 幂等续订；换新端口对象才是装配 bug，显式拒绝
    kit2.register_usage_ports(targets={"trae_cn": port})
    try:
        kit2.register_usage_ports(targets={"trae_cn": FakeUsagePort(UsageResult())})
        raise AssertionError("换端口重复挂载应显式拒绝")
    except ValueError:
        pass
    kit2.close()


def test_daily_usage_scan_job(tmp_path):
    """R2-F：每日用量调度 job——端显式启动（同到期扫描纪律），_daily_usage 全账号采集。"""
    kit = build_engine(tmp_path / "kabao.db")
    port = FakeUsagePort(UsageResult(snapshot=_snap("trae_cn:main", "trae_cn")))
    kit.register_usage_ports(targets={"trae_cn": port})
    kit.register_account.execute("trae_cn", "Trae")  # 名册账号：provider=trae_cn
    kit.vault.store("acc-lonely", "cookie", Secret("x"), expires_at=None)  # vault-only：无 provider
    try:
        assert kit.usage_job is None  # 默认不启动，由端显式 start

        kit._daily_usage()  # 同步驱动一轮（start 的补扫跑同一 fn）
        assert [req.account_id for req in port.calls] == ["trae_cn:main"]

        kit.start_usage_scans()  # 启动即补扫一轮（IntervalJob 语义，异步）
        assert kit.usage_job is not None and kit.usage_job.running
        kit.start_usage_scans()  # 幂等：running 时不叠加
        assert kit.usage_job.running
    finally:
        kit.close()
    assert kit.usage_job is None  # close 排空 job（同 checkin/scan）
