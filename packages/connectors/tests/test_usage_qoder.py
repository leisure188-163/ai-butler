"""qoder_cn 用量通道测试（R2-C）：usage 端点直读 qoderUsage 快照。

鉴权复用声明式主链（Bearer + Cosy 8 头组）；userQuota/addOnQuota 条件成包；
9999 占位时间戳 → cycle_end=None（真机取证 PROTOCOL §7.1）。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from kabao_core.application.ports import UsageRequest
from kabao_connectors.manifest import AuthSpec, HeaderPair
from kabao_connectors.qoder_cn.usage import QoderUsagePort, build_usage_port

_T0 = datetime(2026, 11, 12, 8, 0, 0, tzinfo=timezone.utc)
_DEADLINE = datetime(2026, 11, 12, 8, 1, 0, tzinfo=timezone.utc)

_AUTH = AuthSpec(
    kind="dpapi_gcm_v10",
    token_header=HeaderPair(name="Authorization", prefix="Bearer "),
    static_headers={"Cosy-ClientType": "10"},
    dynamic_headers={"Cosy-MachineId": "{cosy_machine_id}"},
)

_FIELDS = {"token": "dt-token", "cosy_machine_id": "cosy-id-1"}

#: 取证响应形状（2026-11-12 真机骨架；数值换测试值）
_PAYLOAD = {
    "displayMode": "qoder",
    "qoderUsage": {
        "totalUsagePercentage": 0.78,
        "userQuota": {"total": 0, "used": 0, "remaining": 0},  # 当前账号无套餐
        "addOnQuota": {
            "total": 2300,
            "used": 1786,
            "remaining": 514,
            "unit": "credits",
            "detailUrl": "https://qoder.cn/account/usage",
        },
        "expiresAt": 253402214400000,  # 9999-12-31 占位（无月度重置）
        "refreshAt": 253402214400000,
    },
}

_PAYLOAD_WITH_PLAN = {
    "displayMode": "qoder",
    "qoderUsage": {
        "totalUsagePercentage": 0.4,
        "userQuota": {"total": 1000, "used": 300, "remaining": 700, "unit": "credits"},
        "addOnQuota": {"total": 0, "used": 0, "remaining": 0, "unit": "credits"},
        "expiresAt": 1798675200000,  # 2026-12-31 真实未来时间戳（非 9999 占位）
        "refreshAt": 1795526400000,
    },
}


class FakeVault:
    def load(self, account_id: str, kinds: list[str]):
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
    import kabao_connectors.qoder_cn.usage as mod

    monkeypatch.setattr(mod, "unlock_all", lambda kinds, secrets: dict(_FIELDS))


def _port(transport: FakeTransport, *, clock=lambda: _T0) -> QoderUsagePort:
    return QoderUsagePort(
        vault=FakeVault(), transport=transport, auth=_AUTH, kinds=("dpapi_gcm_v10", "umid_cosy"), clock=clock
    )


def _req() -> UsageRequest:
    return UsageRequest(target="qoder_cn", account_id="acc1", deadline=_DEADLINE)


def test_request_shape_bearer_and_cosy_headers(fake_unlock):
    transport = FakeTransport(_PAYLOAD)
    _port(transport).collect(_req())
    req = transport.requests[0]
    assert req.method == "GET"
    assert req.url == "https://openapi.qoder.com.cn/sash/api/v2/me/usage"
    assert req.headers["Authorization"] == "Bearer dt-token"
    assert req.headers["Cosy-ClientType"] == "10"  # 缺此头静默空列表的老坑（PROTOCOL §2）
    assert req.headers["Cosy-MachineId"] == "cosy-id-1"
    assert req.body is None


def test_add_on_quota_becomes_package_plan_quota_skipped(fake_unlock):
    transport = FakeTransport(_PAYLOAD)
    result = _port(transport).collect(_req())
    assert result.snapshot is not None
    packages = result.snapshot.packages
    assert [p.package_id for p in packages] == ["add_on_quota"]  # userQuota total=0 不成包
    addon = packages[0]
    assert (addon.total, addon.used, addon.remaining) == (2300, 1786, 514)
    assert addon.unit == "credits"
    assert addon.cycle_end is None  # 9999 占位 = 无月度重置语义


def test_plan_quota_included_when_total_positive(fake_unlock):
    transport = FakeTransport(_PAYLOAD_WITH_PLAN)
    result = _port(transport).collect(_req())
    assert result.snapshot is not None
    packages = result.snapshot.packages
    assert [p.package_id for p in packages] == ["plan_quota"]  # addOnQuota total=0 不成包
    plan = packages[0]
    assert (plan.total, plan.used, plan.remaining) == (1000, 300, 700)
    assert plan.cycle_end is not None and plan.cycle_end.year == 2026  # 真实时间戳保留


def test_aggregate_keeps_qoder_usage_verbatim(fake_unlock):
    transport = FakeTransport(_PAYLOAD)
    result = _port(transport).collect(_req())
    assert result.aggregate is not None
    assert result.aggregate.summary == _PAYLOAD["qoderUsage"]  # 原话不派生
    assert result.ledger is None  # qoder 无流水通道


def test_missing_qoder_usage_shape_raises(fake_unlock):
    transport = FakeTransport({"displayMode": "qoder"})  # 缺 qoderUsage = 协议形状变
    with pytest.raises(Exception, match="qoderUsage"):
        _port(transport).collect(_req())


def test_http_error_raises(fake_unlock):
    transport = FakeTransport({"error": "boom"}, status=503)
    with pytest.raises(Exception, match="503"):
        _port(transport).collect(_req())


def test_build_usage_port_defaults(fake_unlock):
    port = build_usage_port(vault=FakeVault(), transport=None, auth=_AUTH, kinds=("dpapi_gcm_v10",))
    assert isinstance(port, QoderUsagePort)
    assert port.transport is not None
