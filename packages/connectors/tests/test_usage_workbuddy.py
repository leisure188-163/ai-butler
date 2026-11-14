"""workbuddy_cn 用量通道测试（R2-C）：get-user-resource 85 包分账本。

现用现取零 vault（ADR-006 决策 3）：session_chain 可注入（真实链 =
定位凭据 → 解密 → 建头）。断言字符串时间戳陷阱（PROTOCOL §7.1 踩坑实证）、
TotalCount 翻页、*Precise 字符串后备、401 显式上抛。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from butler_core.usage.ports import UsageRequest
from butler_connectors.workbuddy_cn.usage import WorkbuddyUsagePort, build_usage_port

_T0 = datetime(2026, 11, 12, 8, 0, 0, tzinfo=timezone.utc)
_DEADLINE = datetime(2026, 11, 12, 8, 1, 0, tzinfo=timezone.utc)
_CN = timezone(timedelta(hours=8))  # CycleEndTime 无时区，按 +08:00 解析


def _account(rid: str, *, total=None, used=None, remain=None, name="裂变包", status=0, cycle="2026-12-01 00:00:00") -> dict:
    return {
        "ResourceId": rid,
        "PackageName": name,
        "CapacitySize": total,
        "CapacityUsed": used,
        "CapacityRemain": remain,
        "CapacityUnit": "credits",
        "CycleEndTime": cycle,
        "Status": status,
    }


def _data(accounts: list[dict], *, total_count: int | None = None) -> dict:
    body = {"Response": {"Data": {"Accounts": accounts}}}
    if total_count is not None:
        body["Response"]["Data"]["TotalCount"] = total_count
    return body


class FakeTransport:
    def __init__(self, pages: list[dict], *, status: int = 200):
        self.pages = pages
        self.status = status
        self.calls: list[Any] = []
        self.page_idx = 0

    def __call__(self, request, *, deadline):
        self.calls.append(request)
        payload = self.pages[min(self.page_idx, len(self.pages) - 1)]
        self.page_idx += 1
        from butler_connectors.transport import HttpResponse

        return HttpResponse(status_code=self.status, payload=payload)


def _chain(headers: dict[str, str] | None = None, endpoint: str = "https://wb.example.com"):
    def chain(deadline):
        if headers is None:
            raise RuntimeError("凭据定位失败（测试注入）")
        return headers, endpoint

    return chain


def _port(transport: FakeTransport, chain=None, *, clock=lambda: _T0) -> WorkbuddyUsagePort:
    return WorkbuddyUsagePort(
        transport=transport,
        session_chain=chain if chain is not None else _chain({"Authorization": "Bearer x"}),
        clock=clock,
    )


def _req() -> UsageRequest:
    return UsageRequest(target="workbuddy_cn", account_id="acc1", deadline=_DEADLINE)


def test_request_shape_string_timestamps_and_paging():
    """时间戳必须是字符串（Go 结构体，传数字 400 实证）；TotalCount 驱动翻页。"""
    page1 = _data([_account("r1", total=100, used=30, remain=70)], total_count=2)
    page2 = _data([_account("r2", total=500, used=0, remain=500, name="个人体验版")], total_count=2)
    transport = FakeTransport([page1, page2])
    result = _port(transport).collect(_req())

    assert len(transport.calls) == 2
    req = transport.calls[0]
    assert req.method == "POST"
    assert req.url == "https://wb.example.com/v2/billing/meter/get-user-resource"
    assert req.headers == {"Authorization": "Bearer x"}
    assert req.body["PageNumber"] == 1 and req.body["PageSize"] == 200
    assert req.body["ProductCode"] == "p_tcaca" and req.body["Status"] == [0, 3]
    assert isinstance(req.body["PackageEndTimeRangeBegin"], str)  # 字符串陷阱
    assert isinstance(req.body["PackageEndTimeRangeEnd"], str)
    assert transport.calls[1].body["PageNumber"] == 2
    # 当月月初/月末（本机时区 2026-11）：begin 含 2026-11-01、end 含 2026-11-30
    begin = datetime.fromtimestamp(int(req.body["PackageEndTimeRangeBegin"]), tz=_CN)
    end = datetime.fromtimestamp(int(req.body["PackageEndTimeRangeEnd"]), tz=_CN)
    assert (begin.year, begin.month, begin.day) == (2026, 11, 1)
    assert (end.year, end.month, end.day) == (2026, 11, 30)

    assert result.snapshot is not None
    assert result.aggregate is None and result.ledger is None  # workbuddy 只有包快照
    pkgs = result.snapshot.packages
    assert [p.package_id for p in pkgs] == ["r1", "r2"]
    assert (pkgs[0].total, pkgs[0].used, pkgs[0].remaining) == (100, 30, 70)
    assert pkgs[0].name == "裂变包" and pkgs[0].unit == "credits"
    assert pkgs[0].status == "0"
    assert pkgs[0].cycle_end is not None
    assert pkgs[0].cycle_end.utcoffset() == timedelta(hours=8)  # +08:00 归一
    assert (pkgs[0].cycle_end.year, pkgs[0].cycle_end.month, pkgs[0].cycle_end.day) == (2026, 12, 1)


def test_precise_string_fields_as_fallback():
    """JS number 精度防御：Capacity* 缺失/None 时回退 *Precise 字符串。"""
    account = _account("r1")
    account["CapacitySize"] = None
    account["CapacityUsed"] = None
    account["CapacityRemain"] = None
    account["CapacitySizePrecise"] = "100.5"
    account["CapacityUsedPrecise"] = "0.5"
    account["CapacityRemainPrecise"] = "100"
    transport = FakeTransport([_data([account])])
    result = _port(transport).collect(_req())
    pkg = result.snapshot.packages[0]
    assert (pkg.total, pkg.used, pkg.remaining) == (100.5, 0.5, 100)


def test_name_fallback_chain_and_missing_resource_id():
    """PackageName 缺 → SubProductName → ProductName → ResourceId；缺 ResourceId 显式爆。"""
    account = _account("r1", total=10, used=2, remain=8)
    del account["PackageName"]
    account["SubProductName"] = "子产品名"
    transport = FakeTransport([_data([account])])
    result = _port(transport).collect(_req())
    assert result.snapshot.packages[0].name == "子产品名"

    bad = {"CapacitySize": 1, "CapacityUsed": 0, "CapacityRemain": 1}
    transport2 = FakeTransport([_data([bad])])
    with pytest.raises(Exception, match="ResourceId"):
        _port(transport2).collect(_req())


def test_paging_caps_at_five_pages():
    """TotalCount 一直大于已取数 → 翻页上限 5 页（防御死循环）。"""
    page = _data([_account(f"r{i}", total=10, used=0, remain=10) for i in range(3)], total_count=999)
    transport = FakeTransport([page])
    _port(transport).collect(_req())
    assert len(transport.calls) == 5


def test_401_raises_auth_error():
    transport = FakeTransport([_data([])], status=401)
    with pytest.raises(Exception, match="401"):
        _port(transport).collect(_req())


def test_session_chain_failure_propagates():
    """凭据链失败显式上抛——CollectUsage 收进 outcome.error，不静默。"""
    transport = FakeTransport([_data([])])
    with pytest.raises(Exception, match="凭据"):
        _port(transport, _chain(None)).collect(_req())


def test_http_error_raises():
    transport = FakeTransport([_data([])], status=502)
    with pytest.raises(Exception, match="502"):
        _port(transport).collect(_req())


def test_build_usage_port_defaults_real_chain():
    port = build_usage_port(vault=None, transport=None, auth=None, kinds=())
    assert isinstance(port, WorkbuddyUsagePort)
    assert port.transport is not None
