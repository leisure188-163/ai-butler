"""doubao_cn 用量通道测试（R2-C）：CDP 现取 Cookie + quota/records 流水翻页。

零凭据设计（ADR-007）：无 vault/auth 参与；环境束与 CDP 通道全假件离线。
断言翻页游标、流水字段映射、probe 失败显式上抛。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from butler_core.usage.ports import UsageRequest
from butler_connectors.cdp import CdpError
from butler_connectors.doubao_cn.usage import DoubaoUsagePort, build_usage_port

_T0 = datetime(2026, 11, 12, 8, 0, 0, tzinfo=timezone.utc)
_DEADLINE = datetime(2026, 11, 12, 8, 1, 0, tzinfo=timezone.utc)
MAIN_SEC_UID = "MS4wTESTMAIN000000"


@pytest.fixture(autouse=True)
def _main_identity_baseline(tmp_path, monkeypatch):
    """身份守卫前提：main 基线文件预置（与 adapter 测试同口径）。"""
    from butler_connectors.doubao_cn import identity as doubao_identity

    monkeypatch.setenv("DOUBAO_IDENTITY_PATH", str(tmp_path / "doubao_identity.json"))
    doubao_identity.save_main_baseline(
        doubao_identity.ActiveIdentity(sec_uid=MAIN_SEC_UID, nickname="逍遥酒鬼")
    )


class FakeEnv:
    def resolve_port(self) -> int:
        return 9222

    def read_version(self) -> str:
        return "2.36.6"


def _record(rid: str, amount: int, ms: int, task: str = "daily_signin") -> dict:
    return {
        "amount": amount,
        "create_time_ms": ms,
        "record_id": rid,
        "task_code": task,
        "task_name": "签到" if task == "daily_signin" else "看播",
        "unit": "POINT",
    }


def _page(records: list[dict], *, has_more: bool, next_cursor: str = "") -> dict:
    return {"code": "0", "data": {"has_more": has_more, "next_cursor": next_cursor, "records": records}}


class FakeConn:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class FakeChannel:
    """probe 可达 + 一枚可附着目标 + 固定 Cookie；记录翻页请求序列。

    identity：活跃账户身份（identity.py 守卫查询用）；None = 无聊天页 → 守卫空采。
    Cookie 走浏览器级 storage_cookies（ADR-028）：不依附页面、不建页。"""

    def __init__(
        self,
        transport: FakeTransport | None = None,
        *,
        fail_probe: bool = False,
        identity: dict | None = None,
        cookies: list[dict] | None = None,
    ):
        self.transport = transport
        self.fail_probe = fail_probe
        self.identity = identity if identity is not None else {
            "sec_uid": MAIN_SEC_UID, "nickname": "逍遥酒鬼"
        }
        self.attached: list[Any] = []
        self.opened: list[str] = []
        self.conns: list[FakeConn] = []
        self.cookie_domains: list[str | None] = []
        self._cookies = cookies if cookies is not None else [
            {"name": "sid_tt", "value": "s1"},
            {"name": "sid_tt", "value": "dup-ignored"},  # 同名先到先得
            {"name": "sessionid", "value": "s2"},
        ]

    def probe(self):
        if self.fail_probe:
            raise CdpError("调试端口不可达")

    def targets(self):
        pages = [
            {
                "id": "page-1",
                "type": "page",
                "url": "https://www.doubao.com/pc/agent-explore",
                "webSocketDebuggerUrl": "ws://127.0.0.1/devtools/page/1",
            }
        ]
        if self.identity is not None:
            pages.insert(0, {
                "id": "chat-1", "type": "page",
                "url": "doubao://doubao-chat/chat",
                "webSocketDebuggerUrl": "ws://127.0.0.1/devtools/page/chat",
            })
        return pages

    def attach(self, target):
        self.attached.append(target)
        conn = FakeConn()
        self.conns.append(conn)
        return conn

    def open_activity(self, url: str):
        self.opened.append(url)
        conn = FakeConn()
        self.conns.append(conn)
        return conn

    def evaluate(self, conn, expression: str, *, wait: float = 20.0):
        if "for_ban_appeal_sec_user_id" in expression:
            return dict(self.identity) if self.identity else None
        raise AssertionError("unexpected evaluate")  # usage 编排无其他求值

    def storage_cookies(self, domain: str | None = None):
        self.cookie_domains.append(domain)
        return [dict(c) for c in self._cookies]

    def cookies(self, conn):
        raise AssertionError("用量采集不该依附页面取 Cookie（ADR-028）")


class FakeTransport:
    def __init__(self, pages: list[dict]):
        self.pages = pages
        self.calls: list[Any] = []
        self.page_idx = 0

    def __call__(self, request, *, deadline):
        self.calls.append(request)
        payload = self.pages[min(self.page_idx, len(self.pages) - 1)]
        self.page_idx += 1
        from butler_connectors.transport import HttpResponse

        return HttpResponse(status_code=200, payload=payload)


def _port(transport: FakeTransport, channel: FakeChannel) -> DoubaoUsagePort:
    return DoubaoUsagePort(transport=transport, env=FakeEnv(), channel=channel)


def _req() -> UsageRequest:
    return UsageRequest(target="doubao_cn", account_id="doubao_cn:逍遥酒鬼", deadline=_DEADLINE)


def test_ledger_paginates_and_maps_records():
    transport = FakeTransport(
        [
            _page([_record("r1", 200, 1764000000000)], has_more=True, next_cursor="CUR1"),
            _page([_record("r2", 400, 1764600000000)], has_more=False),
        ]
    )
    channel = FakeChannel(transport)
    result = _port(transport, channel).collect(_req())

    # 翻页：第二页带 next_cursor；首页 cursor 为空串
    assert transport.calls[0].body == {"cursor": "", "page_size": 100}
    assert transport.calls[1].body == {"cursor": "CUR1", "page_size": 100}
    url = transport.calls[0].url
    assert url.startswith("https://www.doubao.com/alice/ug/campaign/quota/records/")
    assert "version_code=" in url and "aid=497858" in url  # AGW 公共参数缺一不可
    assert transport.calls[0].headers["Cookie"] == "sid_tt=s1; sessionid=s2"
    assert "SamanthaDoubao/2.36.6" in transport.calls[0].headers["User-Agent"]

    # 流水映射：三段只落 ledger（doubao 无余额快照，PROTOCOL §7.1）
    assert result.snapshot is None and result.aggregate is None
    assert result.ledger is not None and len(result.ledger) == 2
    r1, r2 = result.ledger
    assert (r1.record_id, r1.amount, r1.unit, r1.kind) == ("r1", 200, "POINT", "签到")
    assert r1.occurred_at is not None and r1.occurred_at.year == 2025  # 1764000000 = 2025-11
    assert (r2.record_id, r2.amount) == ("r2", 400)
    assert r1.account_id == "doubao_cn:逍遥酒鬼" and r1.target == "doubao_cn"


def test_usage_never_opens_page_or_attaches_for_cookies():
    """ADR-028：读额度不产生界面动作——不新建页面、不依附活动页取 Cookie。

    历史事故：活动页缺失时 open_activity 会在豆包客户端里新开页面，客户端窗口被
    拉到前台（用户点「刷新」就跳豆包）。"""
    transport = FakeTransport([_page([], has_more=False)])
    channel = FakeChannel(transport)
    _port(transport, channel).collect(_req())
    assert channel.opened == []
    assert channel.cookie_domains == ["doubao.com"]
    # 唯一的 attach 来自身份查询（只读已有聊天页），Cookie/流水路径零连接
    assert [t["id"] for t in channel.attached] == ["chat-1"]


def test_missing_cookies_is_explicit_error():
    transport = FakeTransport([_page([], has_more=False)])
    channel = FakeChannel(transport, cookies=[])
    with pytest.raises(Exception, match="会话 Cookie"):
        _port(transport, channel).collect(_req())


def test_probe_failure_propagates():
    """probe 失败显式上抛（CdpError）——CollectUsage 收进 outcome.error，不静默。"""
    transport = FakeTransport([])
    with pytest.raises(CdpError):
        _port(transport, FakeChannel(transport, fail_probe=True)).collect(_req())


def test_missing_version_raises():
    class NoVersionEnv(FakeEnv):
        def read_version(self) -> str:
            return ""

    transport = FakeTransport([_page([], has_more=False)])
    port = DoubaoUsagePort(transport=transport, env=NoVersionEnv(), channel=FakeChannel(transport))
    with pytest.raises(Exception, match="版本"):
        port.collect(_req())


def test_record_without_id_raises():
    bad = _record("", 100, 1764000000000)
    transport = FakeTransport([_page([bad], has_more=False)])
    with pytest.raises(Exception, match="record_id"):
        _port(transport, FakeChannel(transport)).collect(_req())


def test_amount_as_numeric_string_accepted():
    """2026-11-12 真机回归：doubao 服务端把 amount 发成数字串（16/16 实证 type=str）。

    数字串收编（workbuddy *Precise 兜底同款先例）；非数字串仍显式拒绝（红线 5）。
    """
    rec = _record("r1", 200, 1764000000000)
    rec["amount"] = "200"
    transport = FakeTransport([_page([rec], has_more=False)])
    result = _port(transport, FakeChannel(transport)).collect(_req())
    assert result.ledger is not None and result.ledger[0].amount == 200.0

    rec_bad = _record("r2", 100, 1764000000000)
    rec_bad["amount"] = "两百"
    transport2 = FakeTransport([_page([rec_bad], has_more=False)])
    with pytest.raises(Exception, match="amount"):
        _port(transport2, FakeChannel(transport2)).collect(_req())


def test_build_usage_port_defaults_real_env():
    """registry entry 契约：vault/auth/kinds 收下但零凭据设计不用（ADR-007）。"""
    port = build_usage_port(vault=None, transport=None, auth=None, kinds=())
    assert isinstance(port, DoubaoUsagePort)
    assert port.transport is not None
