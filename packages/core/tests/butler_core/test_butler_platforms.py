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


def test_图标_默认空串表示无图标() -> None:
    assert _entry().icon == ""  # "" = 无图标（前端回落内置图标/身份色点）


def test_图标_只接受png_data_uri且限长() -> None:
    ok = _entry(icon="data:image/png;base64,AAAA")
    assert ok.icon.startswith("data:image/png;base64,")
    for bad in (
        "https://example.com/icon.png",  # 外链不落库：图标要跟着平台数据走
        "data:image/svg+xml;base64,AAAA",  # 只认 png（前端上传前统一转码）
        "data:image/png;base64," + "A" * 200_001,  # 超长说明不是 96px 图标
    ):
        with pytest.raises(PlatformInvalid):
            _entry(icon=bad)
