"""停靠触发器 CheckinSchedule（A2-01 §4 Trigger=cron，引擎 stdlib 实现）。

- 命中触发位（grace 内）才触发；fired 去重按 (target, account, slot, window)
- 窗口按 core claim_window（结算点语义），触发位跨过结算点不串窗
- 名册为空 = 无人可触发（不闹）；异常隔离到条目级
"""

from datetime import UTC, datetime, timedelta
from typing import Callable

import pytest

from butler_core.accounts.ports import AccountRepository
from butler_core.execution.usecases.execute_action import RunRequest
from butler_core.accounts.domain import Account
from butler_core.execution.domain import Run, RunResult, Status
from butler_core.scheduling.domain import claim_window
from butler_core.shared.health_level import HealthLevel

from butler_engine.scheduling.checkin import CheckinSchedule, ScheduleEntry


class MemAccounts(AccountRepository):
    def __init__(self, *accounts: Account) -> None:
        self.rows = {a.id: a for a in accounts}

    def save(self, account: Account) -> None:
        self.rows[account.id] = account

    def get(self, account_id):
        return self.rows.get(account_id)

    def list_by_platform(self, platform: str) -> list[Account]:
        return [a for a in self.rows.values() if a.platform_code == platform]

    def list_all(self) -> list[Account]:
        return list(self.rows.values())

    def remove(self, account_id):
        return self.rows.pop(account_id, None) is not None


class RecordingUseCase:
    """记录触发的 RunRequest；textbook 立刻攒终态 Run。"""

    def __init__(self, *, seconds_frozen: datetime | None = None):
        self.requests: list[RunRequest] = []
        self.frozen: datetime | None = seconds_frozen  # 供 clock 注入稳态

    def execute(self, request: RunRequest) -> Run:
        self.requests.append(request)
        now = self.frozen or datetime.now(UTC)
        return Run(
            id=f"run-{len(self.requests)}",
            action=request.action,
            account_id=request.account_id,
            idempotency_key="k",
            started_at=now,
            finished_at=now,
            result=RunResult(status=Status.CLAIMED),
        )


def account(platform: str = "trae_cn", name: str = "main") -> Account:
    return Account(
        id=f"{platform}:{name}",
        platform_code=platform,
        account_name=f"{platform} {name}",
        created_at=datetime.now(UTC),
    )


def local_time(day_shift: int, hour: int, minute: int, second: int = 0) -> Callable[[], datetime]:
    """构造"本机墙钟-HH:MM:SS"的冻结 clock：调度语义按本地钟解释（决定论）。"""
    base = datetime.now(UTC).astimezone().replace(
        hour=hour, minute=minute, second=second, microsecond=0
    ) + timedelta(days=day_shift)
    return lambda: base


def entry(target: str = "trae_cn", times=("09:05",), refresh="00:00") -> ScheduleEntry:
    return ScheduleEntry(
        target=target,
        times=tuple(times),
        refresh_at=refresh,
        budget=timedelta(seconds=240),
    )


def schedule(
    usecase: RecordingUseCase,
    accounts: MemAccounts,
    entries: tuple[ScheduleEntry, ...],
    clock: Callable[[], datetime],
    assess=None,
) -> CheckinSchedule:
    return CheckinSchedule(
        execute_action=usecase,  # 鸭子型：RecordingUseCase 提供 execute 协议面
        accounts=accounts,
        entries=entries,
        clock=clock,
        assess_health=assess,
    )


class FakeHealth:
    def __init__(self, level: HealthLevel) -> None:
        self.level = level


def test_health_gate_skips_invalid_and_risk():
    """失效账户不再按班次反复打上游（ADR-015）：invalid/expired/risk 一律跳过。"""
    for level in (HealthLevel.INVALID, HealthLevel.EXPIRED, HealthLevel.RISK):
        usecase, repo = RecordingUseCase(), MemAccounts(account())
        sch = schedule(
            usecase,
            repo,
            (entry("trae_cn", ("09:05",)),),
            clock=local_time(0, 9, 5, 30),
            assess=lambda _aid, level=level: FakeHealth(level),
        )
        assert sch.tick() == []
        assert usecase.requests == []


def test_health_gate_allows_healthy_account():
    """健康账户照常触发；闸门不误拦（评估结果只读）。"""
    usecase, repo = RecordingUseCase(), MemAccounts(account())
    sch = schedule(
        usecase,
        repo,
        (entry("trae_cn", ("09:05",)),),
        clock=local_time(0, 9, 5, 30),
        assess=lambda _aid: FakeHealth(HealthLevel.HEALTHY),
    )
    assert len(sch.tick()) == 1
    assert len(usecase.requests) == 1


def test_fires_at_slot_within_grace():
    """slot 09:05：09:04:30 不到点不触发；09:05:30 命中；重复 tick 同位不重复。"""
    usecase, repo = RecordingUseCase(), MemAccounts(account())
    sch = schedule(
        usecase, repo, (entry("trae_cn", ("09:05",)),),
        clock=local_time(0, 9, 4, 30),
    )
    assert sch.tick() == []
    assert usecase.requests == []

    sch.clock = local_time(0, 9, 5, 30)
    started = sch.tick()
    assert len(usecase.requests) == 1
    assert started == ["run-1"]
    # 同 tick 再跑：fired 命中，不再触发
    assert sch.tick() == []
    assert len(usecase.requests) == 1
    # 窗口归属 = 当日（00:00 结算后）
    assert usecase.requests[0].window == (
        datetime.now(UTC).astimezone().date().isoformat()
    )


def test_grace_expired_no_fire():
    """09:12 已出 grace → 等下一个触发位，不补发（错过 = 错过）。"""
    usecase, repo = RecordingUseCase(), MemAccounts(account())
    sch = schedule(
        usecase, repo, (entry("trae_cn", ("09:05",)),),
        clock=local_time(0, 9, 12),
    )
    assert sch.tick() == []


def test_before_slot_no_fire():
    usecase, repo = RecordingUseCase(), MemAccounts(account())
    sch = schedule(
        usecase, repo, (entry("trae_cn", ("09:05", "13:05")),),
        clock=local_time(0, 8, 0),
    )
    assert sch.tick() == []


def test_window_rolls_over_midnight_anchor():
    """23:55 触发、结算点 00:00：窗口按 core 规则 = 前一日，触发照发。"""
    usecase, repo = RecordingUseCase(), MemAccounts(account())
    sch = schedule(
        usecase, repo, (entry("trae_cn", ("23:55",)),),
        clock=local_time(0, 23, 55),
    )
    sch.tick()
    # 规则同源自证：claim_window(同一 clock, "00:00") 应给出同一窗口
    assert usecase.requests[0].window == claim_window(sch.clock(), "00:00")


def test_fires_per_account_and_no_roster_no_fire():
    repo_full = MemAccounts(account("trae_cn", "main"), account("trae_cn", "second"))
    empty = MemAccounts()
    for repo, expected in ((repo_full, 2), (empty, 0)):
        usecase = RecordingUseCase()
        sch = schedule(
            usecase, repo, (entry("trae_cn", ("09:05",)),),
            clock=local_time(0, 9, 5, 30),
        )
        sch.tick()
        assert len(usecase.requests) == expected


def test_other_app_not_affected():
    """其他 platform 的账号不受本条目影响（target 路由纪律）。"""
    usecase = RecordingUseCase()
    repo = MemAccounts(account("qoder", "main"), account("trae_cn", "main"))
    sch = schedule(
        usecase, repo, (entry("trae_cn", ("09:05",)),),
        clock=local_time(0, 9, 5, 30),
    )
    sch.tick()
    assert [r.account_id for r in usecase.requests] == ["trae_cn:main"]


def test_entry_validation():
    with pytest.raises(ValueError):
        entry("trae_cn", times=())  # 空 times
    with pytest.raises(ValueError):
        ScheduleEntry(
            target="t", times=("09:00",), refresh_at="00:00", budget=timedelta(0)
        )
