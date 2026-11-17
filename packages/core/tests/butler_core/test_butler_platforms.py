"""平台域 domain 校验（A2-09）：类型词表与调度覆盖时间格式。"""

from __future__ import annotations

from datetime import datetime, UTC

import pytest

from butler_core.platforms.domain import PlatformEntry, PlatformInvalid


def _entry(**kw) -> PlatformEntry:
    base = dict(
        platform_code="doubao_cn",
        platform_name="豆包",
        created_at=datetime(2026, 11, 18, tzinfo=UTC),
        platform_kind="client",
        capabilities=("provision.run",),
        credential_kinds=("cookie",),
        schedule_times=("09:15",),
    )
    base.update(kw)
    return PlatformEntry(**base)


def test_调度覆盖_合法HHMM通过() -> None:
    entry = _entry(schedule_override=("21:15", "09:15"))
    assert entry.schedule_override == ("21:15", "09:15")


def test_调度覆盖_非法格式显式抛() -> None:
    for bad in ("9:15", "24:00", "09:60", "晚上九点"):
        with pytest.raises(PlatformInvalid):
            _entry(schedule_override=(bad,))


def test_schedule_override_默认None表示跟随manifest() -> None:
    assert _entry().schedule_override is None


def test_平台类型词表校验() -> None:
    with pytest.raises(PlatformInvalid):
        _entry(platform_kind="app")
