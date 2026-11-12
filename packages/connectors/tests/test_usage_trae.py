"""trae_cn 用量通道测试（R2-C）：鉴权复用声明式主链 + 包分账本映射。

离线全假件：FakeVault 给解锁字段（unlock_all monkeypatch 绕过真加密），
FakeTransport 断言请求形状并回放取证响应形状（PROTOCOL §7.1）。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from kabao_core.application.ports import CredentialMissing, UsageRequest
from kabao_core.domain.usage import UsageResult

from kabao_connectors.manifest import AuthSpec, HeaderPair
from kabao_connectors.trae_cn.usage import TraeUsagePort, build_usage_port

_T0 = datetime(2026, 11, 12, 8, 0, 0, tzinfo=timezone.utc)
_DEADLINE = datetime(2026, 11, 12, 8, 1, 0, tzinfo=timezone.utc)

_AUTH = AuthSpec(
    kind="ss_aes",
    token_header=HeaderPair(name="Authorization", prefix="Cloud-IDE-JWT "),
    static_headers={"X-User-Region": "cn"},
    dynamic_headers={"x-device-id": "{device_dn}"},
)

_FIELDS = {"token": "jwt-token", "device_dn": "aha-device-1"}

#: 取证响应形状（2026-11-12 真机；只取字段骨架，数值换测试值）
_PAYLOAD = {
    "usage_summary": {"consumed_amount": 2643.87, "consumption_ratio": 0.826, "total_amount": 3200},
    "user_entitlement_pack_list": [
        {   # 正常签到包：有 id/面额/用量/过期
            "entitlement_base_info": {
                "entitlement_id": "ent-sign-1",
                "display_desc": "签到奖励包",
                "quota": {"credits_limit": 200},
            },
            "group_name": "signin",
            "usage": {"credits_amount": 50},
            "expire_time": 1795564800,  # 2026-11-25（unix 秒）
            "status": 1,
        },
        {   # 无限包：credits_limit=-1 → 跳过（无余量语义）
            "entitlement_base_info": {
                "entitlement_id": "ent-unlimited",
                "display_desc": "无限包",
                "quota": {"credits_limit": -1},
            },
            "usage": {"credits_amount": 0},
        },
        {   # 无 credits 语义包：quota 缺 credits_limit → 跳过
            "entitlement_base_info": {
                "entitlement_id": "ent-nocredit",
                "display_desc": "权益包",
                "quota": {},
            },
            "usage": {},
        },
        {   # 缺 entitlement_id → 回退合成 id（group_name:expire）
            "entitlement_base_info": {
                "display_desc": "月度登录包",
                "quota": {"credits_limit": 500},
            },
            "group_name": "monthly-login",
            "usage": {"credits_amount": 100},
            "expire_time": 1798675200,  # 2026-12-31
        },
    ],
}


class FakeVault:
    """声明 kinds → Secret（值 = kind 本身；unlock_all 被打桩不真解）。"""

    def load(self, account_id: str, kinds: list[str]):
        if account_id != "acc1":
            raise CredentialMissing(account_id, kinds)
        from kabao_core.domain.vault import Secret

        return [Secret(kind) for kind in kinds]


class FakeTransport:
    def __init__(self, payload: Any, status: int = 200):
        self.payload = payload
        self.status = status
        self.requests: list[Any] = []

    def __call__(self, request, *, deadline):
        self.requests.append(request)
        from kabao_connectors.transport import HttpResponse

        return HttpResponse(status_code=self.status, payload=self.payload)


@pytest.fixture
def fake_unlock(monkeypatch):
    """unlock_all 打桩（适配器模块命名空间）：返回固定字段字典，离线免真解密。"""
    import kabao_connectors.trae_cn.usage as mod

    monkeypatch.setattr(mod, "unlock_all", lambda kinds, secrets: dict(_FIELDS))


def _port(transport: FakeTransport, *, clock=lambda: _T0) -> TraeUsagePort:
    return TraeUsagePort(
        vault=FakeVault(), transport=transport, auth=_AUTH, kinds=("ss_aes", "device_dn"), clock=clock
    )


def _req() -> UsageRequest:
    return UsageRequest(target="trae_cn", account_id="acc1", deadline=_DEADLINE)


def test_request_shape_uses_declared_auth_chain(fake_unlock):
    transport = FakeTransport(_PAYLOAD)
    result = _port(transport).collect(_req())
    req = transport.requests[0]
    assert req.method == "POST"
    assert req.url == "https://api.trae.cn/trae/api/v2/pay/ide_user_ent_usage"
    assert req.headers["Authorization"] == "Cloud-IDE-JWT jwt-token"
    assert req.headers["x-device-id"] == "aha-device-1"
    assert req.headers["X-User-Region"] == "cn"
    assert req.body == {"require_usage": True, "req_source": 1}  # 数字枚举（PROTOCOL §7.1）
    assert isinstance(result, UsageResult)


def test_packages_mapped_and_unlimited_skipped(fake_unlock):
    transport = FakeTransport(_PAYLOAD)
    result = _port(transport).collect(_req())
    assert result.snapshot is not None
    assert result.aggregate is not None
    assert result.ledger is None  # trae 无流水通道（PROTOCOL §7.3），如实 None
    packages = result.snapshot.packages
    assert [p.package_id for p in packages] == ["ent-sign-1", "monthly-login:1798675200"]
    sign = packages[0]
    assert sign.name == "签到奖励包"
    assert (sign.total, sign.used, sign.remaining) == (200, 50, 150)
    assert sign.unit == "credits"
    assert sign.cycle_end is not None and sign.cycle_end.year == 2026
    monthly = packages[1]
    assert monthly.name == "月度登录包"
    assert monthly.remaining == 400


def test_aggregate_keeps_server_summary_verbatim(fake_unlock):
    transport = FakeTransport(_PAYLOAD)
    result = _port(transport).collect(_req())
    assert result.aggregate is not None
    assert result.aggregate.summary == _PAYLOAD["usage_summary"]  # 原话不派生


def test_collected_at_stamped_by_port_clock(fake_unlock):
    transport = FakeTransport(_PAYLOAD)
    result = _port(transport).collect(_req())
    assert result.snapshot is not None
    assert result.snapshot.collected_at == _T0


def test_http_error_raises(fake_unlock):
    transport = FakeTransport({"error": "boom"}, status=500)
    with pytest.raises(Exception, match="500"):
        _port(transport).collect(_req())


def test_business_code_nonzero_raises(fake_unlock):
    transport = FakeTransport({"code": "1001", "msg": "unauthorized"})
    with pytest.raises(Exception, match="1001"):
        _port(transport).collect(_req())


def test_missing_credential_propagates(fake_unlock):
    """凭据缺失显式上抛（最小授权语义）——CollectUsage 收进 outcome.error。"""
    from kabao_connectors.transport import HttpResponse

    transport = FakeTransport(_PAYLOAD)
    port = TraeUsagePort(vault=FakeVault(), transport=transport, auth=_AUTH, kinds=("ss_aes", "device_dn"))
    with pytest.raises(CredentialMissing):
        port.collect(UsageRequest(target="trae_cn", account_id="acc2", deadline=_DEADLINE))


def test_build_usage_port_defaults_real_transport(fake_unlock):
    """registry entry 契约：build_usage_port(vault=, transport=, auth=, kinds=)。"""
    port = build_usage_port(vault=FakeVault(), transport=None, auth=_AUTH, kinds=("ss_aes",))
    assert isinstance(port, TraeUsagePort)
    assert port.transport is not None  # 默认 httpx_transport
