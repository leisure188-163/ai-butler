"""cdp.py 离线测试（A2-02 §8）：不起浏览器，假 http_get / 假 ws 注入。"""

from __future__ import annotations

import json
import sys
import types

import pytest

from kabao_connectors import cdp
from kabao_connectors.cdp import CdpChannel, CdpConnection, CdpError, pick_activity_target


class EchoWs:
    """按发送 id 回 result 帧（CDP 假端最小实现）；可预置应答/混入事件帧。"""

    def __init__(self, result: dict | None = None, noise: list[dict] | None = None) -> None:
        self._result = result or {}
        self._noise = list(noise or [])
        self.staged: list[dict] = []  # 预置应答（error 帧等），优先于回声
        self.sent: list[dict] = []
        self.closed = False

    def stage(self, msg: dict) -> None:
        self.staged.append(msg)

    def send(self, text: str) -> None:
        msg = json.loads(text)
        self.sent.append(msg)
        self.staged.append({"id": msg["id"], "result": dict(self._result)})

    def recv(self) -> str:
        return json.dumps(self.staged.pop(0) if self.staged else self._noise.pop(0))

    def close(self) -> None:
        self.closed = True


class DeadWs:
    """永不回帧（超时路径）。"""

    def send(self, text: str) -> None: ...

    def recv(self) -> str:
        raise TimeoutError("no reply")

    def close(self) -> None: ...


def test_call_matches_id_and_skips_events():
    conn = CdpConnection(EchoWs({"value": 1}, noise=[{"method": "X.y", "params": {}}]))
    assert conn.call("Runtime.evaluate") == {"value": 1}


def test_call_error_frame_raises_cdp_error():
    ws = EchoWs()
    ws.stage({"id": 1, "error": {"message": "bad method"}})
    conn = CdpConnection(ws)
    with pytest.raises(CdpError, match="bad method"):
        conn.call("No.method")


def test_call_timeout_raises_cdp_error():
    conn = CdpConnection(DeadWs())
    with pytest.raises(CdpError, match="超时"):
        conn.call("Runtime.evaluate", wait=0.01)


def test_ws_connect_suppresses_origin(monkeypatch):
    recorded = {}

    def fake_create_connection(url, timeout=None, **kwargs):
        recorded.update(url=url, timeout=timeout, **kwargs)
        return EchoWs()

    fake_ws = types.ModuleType("websocket")
    fake_ws.create_connection = fake_create_connection
    fake_ws.WebSocketException = type("WebSocketException", (Exception,), {})
    fake_ws.WebSocketTimeoutException = type("WebSocketTimeoutException", (Exception,), {})
    monkeypatch.setitem(sys.modules, "websocket", fake_ws)
    conn = cdp.ws_connect("ws://127.0.0.1:9222/x", 5.0)
    assert recorded["suppress_origin"] is True  # Chromium 111+ 拒绝带 Origin 的握手
    assert recorded["timeout"] == 5.0
    conn.close()


def test_http_json_bypasses_system_proxy(monkeypatch):
    recorded = {}

    class FakeResp:
        def read(self):
            return b'{"ok": 1}'

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    class FakeOpener:
        def __init__(self, handlers):
            recorded["handlers"] = handlers

        def open(self, url, timeout=None):
            recorded["url"] = url
            return FakeResp()

    # 补丁打在真实模块属性上：import urllib.request 绑定的是顶层包，
    # 替换 sys.modules["urllib.request"] 拦不到属性访问
    import urllib.request as real_request

    monkeypatch.setattr(real_request, "build_opener", lambda *h: FakeOpener(h))
    monkeypatch.setattr(real_request, "ProxyHandler", lambda mapping: ("ProxyHandler", mapping))
    assert cdp.http_json("http://127.0.0.1:9222/json/version", 3.0) == {"ok": 1}
    handlers = recorded["handlers"]
    assert any(h == ("ProxyHandler", {}) for h in handlers)  # 本机探测必须绕系统代理


def _channel(http_get=None, ws_factory=None, sleep=None) -> CdpChannel:
    return CdpChannel(
        9222,
        http_get=http_get or (lambda url, timeout: {}),
        ws_factory=ws_factory or (lambda url, timeout: CdpConnection(EchoWs())),
        sleep=sleep or (lambda s: None),
    )


def test_probe_parses_and_wraps_errors():
    assert _channel(http_get=lambda url, t: {"Browser": "Chrome/147"}).probe()["Browser"]
    with pytest.raises(CdpError, match="不可达"):
        _channel(http_get=lambda url, t: (_ for _ in ()).throw(OSError("refused"))).probe()


def test_targets_wraps_errors():
    with pytest.raises(CdpError):
        _channel(http_get=lambda url, t: (_ for _ in ()).throw(OSError("x"))).targets()


def test_pick_activity_target_filters_and_prefers():
    targets = [
        {"type": "page", "url": "doubao://launcher", "webSocketDebuggerUrl": "ws://a"},
        {"type": "iframe", "url": "https://www.doubao.com/x", "webSocketDebuggerUrl": "ws://b"},
        {"type": "page", "url": "https://other.com/", "webSocketDebuggerUrl": "ws://c"},
        {"type": "webview", "url": "https://www.doubao.com/pc/agent-explore?campaign=1",
         "webSocketDebuggerUrl": "ws://d"},
        {"type": "page", "url": "https://www.doubao.com/chat", "webSocketDebuggerUrl": "ws://e"},
    ]
    assert pick_activity_target(targets)["webSocketDebuggerUrl"] == "ws://d"  # 活动页优先
    assert pick_activity_target(targets[-1:])["webSocketDebuggerUrl"] == "ws://e"
    assert pick_activity_target([]) is None


def test_open_activity_creates_and_polls():
    """createTarget 走浏览器级 ws；轮询 /json/list 等页面挂上调试端点。"""
    sent = {}

    def http_get(url, timeout):
        if url.endswith("/json/version"):
            return {"webSocketDebuggerUrl": "ws://browser"}
        sent.setdefault("lists", []).append(url)
        if len(sent["lists"]) == 1:
            return []  # 第一轮：页面还没挂上 WS
        return [{"type": "page", "url": "https://www.doubao.com/pc/agent-explore",
                 "webSocketDebuggerUrl": "ws://page"}]

    browser_ws = EchoWs({"targetId": "t1"})
    page_ws = EchoWs()
    conns = iter([CdpConnection(browser_ws), CdpConnection(page_ws)])
    channel = _channel(http_get=http_get, ws_factory=lambda url, t: next(conns))
    slept: list[float] = []
    channel.sleep = lambda s: slept.append(s)  # type: ignore[method-assign]
    conn = channel.open_activity("https://www.doubao.com/pc/agent-explore")
    assert browser_ws.sent[0]["method"] == "Target.createTarget"
    assert browser_ws.sent[0]["params"]["url"] == "https://www.doubao.com/pc/agent-explore"
    assert conn is not None and slept  # 轮询确实发生过


def test_open_activity_timeout_raises():
    def http_get(url, timeout):
        if url.endswith("/json/version"):
            return {"webSocketDebuggerUrl": "ws://browser"}
        return []

    channel = _channel(http_get=http_get, ws_factory=lambda url, t: CdpConnection(EchoWs()))
    with pytest.raises(CdpError, match="超时"):
        channel.open_activity("https://www.doubao.com/pc/agent-explore", wait=0.05)


def test_cookies_and_evaluate_and_click():
    ws = EchoWs({"cookies": [{"name": "sessionid", "value": "s"}]})
    conn = CdpConnection(ws)
    channel = _channel()
    assert channel.cookies(conn)[0]["name"] == "sessionid"

    ws2 = EchoWs({"result": {"type": "object", "value": {"x": 3, "y": 4}}})
    assert channel.evaluate(CdpConnection(ws2), "() => 1") == {"x": 3, "y": 4}

    ws3 = EchoWs()
    ws3.stage({"id": 1, "error": {"message": "eval failed"}})
    with pytest.raises(CdpError, match="eval failed"):
        channel.evaluate(CdpConnection(ws3), "() => 1")

    ws4 = EchoWs()
    conn4 = CdpConnection(ws4)
    slept: list[float] = []
    channel4 = _channel(sleep=lambda s: slept.append(s))
    channel4.click(conn4, 10, 20)
    types_sent = [m["params"]["type"] for m in ws4.sent]
    assert types_sent == ["mouseMoved", "mousePressed", "mouseReleased"]  # 受信任三连
    assert ws4.sent[1]["params"]["clickCount"] == 1 and ws4.sent[2]["params"]["clickCount"] == 1
    assert 0.12 in [round(s, 2) for s in slept]  # 按下→抬起间隔真实发生过
