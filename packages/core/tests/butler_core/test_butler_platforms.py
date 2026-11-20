"""平台域 domain 校验（A2-09）：类型词表与调度覆盖时间格式。"""

from __future__ import annotations

from datetime import datetime, UTC

import pytest

from butler_core.platforms.domain import (
    PlatformAlreadyExists,
    PlatformEntry,
    PlatformInvalid,
)


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


# --- 接入源（ADR-033）---


def _provider(**kw) -> PlatformEntry:
    base = dict(
        platform_code="my_relay",
        platform_name="我的中转",
        created_at=datetime(2026, 11, 20, tzinfo=UTC),
        platform_kind="relay",
        base_url="https://relay.example.com/v1",
        protocol="openai",
        models=("gpt-4o-mini",),
        credential_kinds=("api_key",),
        origin="user",
        capabilities=(),
        schedule_times=(),
    )
    base.update(kw)
    return PlatformEntry(**base)


class MemoryPlatforms:
    def __init__(self):
        self.rows: dict[str, PlatformEntry] = {}

    def upsert(self, entry):
        self.rows[entry.platform_code] = entry

    def get(self, code):
        return self.rows.get(code)

    def list_all(self):
        return list(self.rows.values())

    def update_profile(self, code, *, platform_name=None, is_active=None, icon=None,
                       base_url=None, protocol=None, models=None, credential_kinds=None):
        import dataclasses

        row = self.rows.get(code)
        if row is None:
            return None
        changes = {
            k: v
            for k, v in dict(
                platform_name=platform_name, is_active=is_active, icon=icon,
                base_url=base_url, protocol=protocol, models=models,
                credential_kinds=credential_kinds,
            ).items()
            if v is not None
        }
        row = dataclasses.replace(row, **changes)
        self.rows[code] = row
        return row


def test_用户接入源必须三件套() -> None:
    assert _provider().origin == "user"
    for missing in ({"platform_kind": ""}, {"base_url": ""}, {"protocol": ""}):
        with pytest.raises(PlatformInvalid):
            _provider(**missing)


def test_接入源协议与地址形状校验() -> None:
    with pytest.raises(PlatformInvalid):
        _provider(protocol="openai-compatible")
    with pytest.raises(PlatformInvalid):
        _provider(base_url="relay.example.com/v1")
    with pytest.raises(PlatformInvalid):
        _provider(platform_kind="app")  # 不在 PLATFORM_KINDS


def test_create_platform_编码校验与无连接器事实() -> None:
    from butler_core.platforms.usecases.create_platform import CreatePlatform

    repo = MemoryPlatforms()
    uc = CreatePlatform(platforms=repo)
    created = uc.execute(
        "My-Relay", "我的中转", kind="relay",
        base_url="https://relay.example.com/v1", protocol="openai",
        models=(" gpt-4o-mini ",), credential_kinds=("api_key", ""),
    )
    assert created.platform_code == "my-relay"  # 编码转小写
    assert created.origin == "user"
    assert created.capabilities == () and created.schedule_times == ()  # 接入源不排班
    assert created.models == ("gpt-4o-mini",)
    assert created.credential_kinds == ("api_key",)
    with pytest.raises(PlatformInvalid):
        uc.execute("bad:code", "x", kind="relay",
                   base_url="https://x.example.com", protocol="openai")
    with pytest.raises(PlatformAlreadyExists):
        uc.execute("my-relay", "重复", kind="relay",
                   base_url="https://x.example.com", protocol="openai")


def test_update_provider_只改用户接入源() -> None:
    from butler_core.platforms.usecases.update_provider import UpdateProvider

    repo = MemoryPlatforms()
    repo.upsert(_provider())
    repo.upsert(_entry())  # connector 平台
    uc = UpdateProvider(platforms=repo)

    updated = uc.execute("my_relay", base_url="https://relay2.example.com/v1",
                         protocol="anthropic", models=("claude-sonnet",))
    assert updated.base_url == "https://relay2.example.com/v1"
    assert updated.protocol == "anthropic"
    assert updated.models == ("claude-sonnet",)

    with pytest.raises(PlatformInvalid):
        uc.execute("doubao_cn", base_url="https://evil.example.com")  # manifest 申报，不许改
    with pytest.raises(PlatformInvalid):
        uc.execute("my_relay", base_url="ftp://relay.example.com")
    with pytest.raises(PlatformInvalid):
        uc.execute("my_relay", protocol="unknown")
    with pytest.raises(PlatformInvalid):
        uc.execute("ghost", platform_name="x")
