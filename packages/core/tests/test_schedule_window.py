"""claim_window / ScheduleEntry 窗口语义（A2-01 §3：签到日≠自然日）。

结论测试：
- 结算点之后 → 属当日窗口
- 结算点之前 → 属前一日窗口（ Qoder 每日 10:00 刷新的滑窗事实）
- 非法 anchor 显式爆（红线 5）
"""

from datetime import UTC, datetime, timedelta, timezone

import pytest

from kabao_core.domain.errors import DomainError
from kabao_core.domain.schedule import claim_window


def test_window_is_calendar_day_at_and_after_anchor():
    # 2026-11-11 09:05（本地）在 09:00 结算点后 → 窗口 = 当日
    now = datetime(2026, 11, 11, 9, 5, tzinfo=UTC).astimezone()
    assert claim_window(now, "09:00") == now.date().isoformat()
    exactly = datetime(2026, 11, 11, 9, 0, tzinfo=UTC).astimezone()
    assert claim_window(exactly, "09:00") == exactly.date().isoformat()


def test_window_falls_back_to_previous_day_before_anchor():
    # 本地时间 08:59 发起 → 属前一日业务窗（9074 圈走的都是同一窗口）
    utc8 = timezone(timedelta(hours=8))
    now = datetime(2026, 11, 11, 8, 59, tzinfo=utc8)
    assert claim_window(now, "09:00") == "2026-11-10"


def test_utc_input_derives_local_wall_clock():
    """refresh_at 是本机墙钟语义：UTC 输入先换本地时区再裁界。"""
    utc8 = timezone(timedelta(hours=8))
    # UTC 2026-11-10 16:30 == UTC+8 2026-11-11 00:30 → 已过 00:00 结算 → 窗口 = 11-11
    now = datetime(2026, 11, 10, 16, 30, tzinfo=UTC)
    assert claim_window(now, "00:00") == "2026-11-11"


def test_default_anchor_is_midnight():
    now = datetime(2026, 11, 11, 0, 30, tzinfo=UTC)
    assert claim_window(now) == now.astimezone().date().isoformat()


def test_invalid_anchor_raises():
    with pytest.raises(DomainError):
        claim_window(datetime.now(UTC), "24:00")
    with pytest.raises(DomainError):
        claim_window(datetime.now(UTC), "9:00")
