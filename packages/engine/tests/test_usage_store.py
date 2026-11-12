"""R2-B：SqliteUsageStore 三表 + record_id 幂等去重 + 新→旧读取（TDD）。

- 快照/聚合：JSON 往返保真（frozen dataclass 相等），新→旧（同秒按入库序决胜）
- 流水：(account_id, record_id) 主键幂等，append 返回新增条数
"""

from datetime import datetime, timedelta, timezone

import pytest

from kabao_core.domain.usage import (
    PackageQuota,
    QuotaLedgerEntry,
    UsageAggregate,
    UsageSnapshot,
)
from kabao_engine.usage.sqlite import SqliteUsageStore

_T0 = datetime(2026, 11, 12, 12, 0, tzinfo=timezone.utc)


def _snap(at=_T0, account="trae_cn:main", target="trae_cn", sid="s1", packages=None):
    return UsageSnapshot(
        id=sid,
        account_id=account,
        target=target,
        collected_at=at,
        packages=tuple(
            packages
            if packages is not None
            else [
                PackageQuota(
                    package_id="p1",
                    name="签到包",
                    total=100.0,
                    used=90.0,
                    remaining=10.0,
                    unit="credits",
                    cycle_end=_T0 + timedelta(days=19),
                    status="ACTIVE",
                )
            ]
        ),
    )


@pytest.fixture
def store(tmp_path):
    return SqliteUsageStore(tmp_path / "test.db")


def test_snapshot_roundtrip_preserves_fields(store):
    s = _snap()
    store.save_snapshot(s)
    [row] = store.list_snapshots("trae_cn:main", limit=10)
    assert row == s  # JSON 往返后 frozen dataclass 全字段相等


def test_snapshots_newest_first(store):
    store.save_snapshot(_snap(at=_T0, sid="s1"))
    store.save_snapshot(_snap(at=_T0 + timedelta(hours=1), sid="s2"))
    assert [r.id for r in store.list_snapshots("trae_cn:main", limit=2)] == ["s2", "s1"]


def test_snapshots_same_second_ordering_by_insertion(store):
    """同秒两帧：后者是更新帧——rowid 决胜，不赌 uuid 字典序。"""
    store.save_snapshot(_snap(at=_T0, sid="first"))
    store.save_snapshot(_snap(at=_T0, sid="second"))
    assert store.list_snapshots("trae_cn:main", limit=1)[0].id == "second"


def test_snapshots_isolated_by_account(store):
    store.save_snapshot(_snap(account="qoder_cn:main", target="qoder_cn", sid="q1"))
    assert store.list_snapshots("trae_cn:main", limit=10) == []


def test_snapshots_limit_zero(store):
    store.save_snapshot(_snap())
    assert store.list_snapshots("trae_cn:main", limit=0) == []


def test_aggregate_roundtrip_and_latest(store):
    a1 = UsageAggregate(
        id="a1", account_id="trae_cn:main", target="trae_cn",
        collected_at=_T0, summary={"consumed_amount": 55, "consumption_ratio": 0.31},
    )
    a2 = UsageAggregate(
        id="a2", account_id="trae_cn:main", target="trae_cn",
        collected_at=_T0 + timedelta(hours=1), summary={"consumed_amount": 60},
    )
    store.save_aggregate(a1)
    store.save_aggregate(a2)
    assert store.latest_aggregate("trae_cn:main") == a2
    assert store.latest_aggregate("nope:main") is None


def test_ledger_dedup_and_new_count(store):
    e1 = QuotaLedgerEntry(
        record_id="r1", account_id="doubao_cn:main", target="doubao_cn",
        amount=200, unit="POINT", occurred_at=_T0, kind="签到",
    )
    e2 = QuotaLedgerEntry(
        record_id="r2", account_id="doubao_cn:main", target="doubao_cn",
        amount=400, unit="POINT", occurred_at=_T0, kind="周一双倍",
    )
    assert store.append_ledger([e1, e2]) == 2
    assert store.append_ledger([e1]) == 0  # 幂等：同 (account, record_id) 不重
    assert store.append_ledger([]) == 0
    rows = store.list_ledger("doubao_cn:main", limit=10)
    assert [(r.record_id, r.amount, r.unit, r.kind) for r in rows] == [
        ("r2", 400.0, "POINT", "周一双倍"),  # 新→旧（同刻按入库序倒序）
        ("r1", 200.0, "POINT", "签到"),
    ]


def test_ledger_raw_and_none_time_roundtrip(store):
    e = QuotaLedgerEntry(
        record_id="r9", account_id="doubao_cn:main", target="doubao_cn",
        amount=1, unit="POINT", occurred_at=None,
        raw={"task_code": "daily_signin", "create_time_ms": 1770000000000},
    )
    store.append_ledger([e])
    [row] = store.list_ledger("doubao_cn:main", limit=1)
    assert row == e
    assert row.occurred_at is None and row.raw["task_code"] == "daily_signin"
