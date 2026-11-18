"""CDP 通用原语（ADR-007）：Chromium/Electron 客户端界面通道的共享底座。

- 原语不认识任何产品：probe / targets / pick / attach / open_activity /
  cookies / evaluate / click——产品专属编排在各连接器 adapter（A2-02 §3）
- 平台依赖工厂注入（A2-02 §8）：测试不起浏览器，假 http_get / 假 ws 即可离线
- Chromium 111+ 拒绝带 Origin 头的 CDP 握手——ws_connect 必带 suppress_origin=True
- 127.0.0.1 探测必须绕系统代理（PROTOCOL doubao_cn §2：代理开着时 urllib 会把
  调试端口请求发给代理，直连失败）
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

#: (url, timeout_s) → 解析后的 JSON
HttpGet = Callable[[str, float], Any]
#: (ws_url, timeout_s) → 连接
WsFactory = Callable[[str, float], "CdpConnection"]
Sleep = Callable[[float], None]

_ACTIVITY_PREFERS = ("campaign", "agent-explore", "incentive")

#: key() 支持的按键 → Windows virtual key code（Input.dispatchKeyEvent 必填）
_KEY_VIRTUAL_CODES = {"ArrowDown": 40, "ArrowUp": 38, "ArrowRight": 39, "Enter": 13, "Escape": 27}


class CdpError(RuntimeError):
    """CDP 链路故障：端口不可达 / WS 握手失败 / 方法报错 / 响应超时。"""


class CdpConnection:
    """一条页面/浏览器级调试会话：call 按 id 匹配响应，事件帧跳过。"""

    def __init__(self, ws: Any) -> None:
        self._ws = ws
        self._id = 0

    def call(self, method: str, params: dict | None = None, *, wait: float = 8.0) -> dict:
        self._id += 1
        self._ws.send(json.dumps({"id": self._id, "method": method, "params": params or {}}))
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            try:
                msg = json.loads(self._ws.recv())
            except TimeoutError as exc:  # 传输层超时 = 与等待到期同语义
                raise CdpError(f"CDP 调用超时（{wait}s）：{method}") from exc
            except Exception as exc:  # 断连等归链路故障（调用方按 CdpError 处理）
                raise CdpError(f"CDP 会话收帧失败: {exc}") from exc
            if msg.get("id") != self._id:
                continue  # 事件帧：跳过
            if "error" in msg:
                raise CdpError(str(msg["error"].get("message") or msg["error"]))
            return msg.get("result") or {}
        raise CdpError(f"CDP 调用超时（{wait}s）：{method}")

    def close(self) -> None:
        try:
            self._ws.close()
        except Exception:
            pass  # 关闭失败不影响结果（旧系统同语义）

    def __enter__(self) -> "CdpConnection":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def http_json(url: str, timeout: float) -> Any:
    """默认 HTTP 原语：urllib + 空 ProxyHandler（本机端口绕系统代理）。"""
    import urllib.request

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(url, timeout=timeout) as resp:
        return json.loads(resp.read() or b"null")


def ws_connect(url: str, timeout: float) -> CdpConnection:
    """默认 WS 原语：websocket-client + suppress_origin（Chromium 111+ 必带）。"""
    import websocket  # 惰性：import 期不强依赖，运行期缺失显式爆

    return CdpConnection(
        websocket.create_connection(url, timeout=timeout, suppress_origin=True)
    )


def pick_activity_target(targets: list[dict], *, domain: str = "doubao.com") -> dict | None:
    """活动页选择（PROTOCOL doubao_cn §6）：域匹配不限 type；doubao:// 内部页
    天然被域过滤排除；url 含 campaign/agent-explore/incentive 优先。"""
    pages = [
        t
        for t in targets
        if t.get("type") in ("page", "webview")
        and domain in (t.get("url") or "")
        and t.get("webSocketDebuggerUrl")
    ]
    for key in _ACTIVITY_PREFERS:
        for t in pages:
            if key in (t.get("url") or ""):
                return t
    return pages[0] if pages else None


class CdpChannel:
    """一台客户端的 CDP 通道（端口已绑定的原语束，A2-02 §8 注入面）。"""

    def __init__(
        self,
        port: int,
        *,
        http_get: HttpGet = http_json,
        ws_factory: WsFactory = ws_connect,
        sleep: Sleep = time.sleep,
    ) -> None:
        self.port = port
        self._http_get = http_get
        self._ws_factory = ws_factory
        self.sleep = sleep

    def _get(self, path: str, timeout: float) -> Any:
        return self._http_get(f"http://127.0.0.1:{self.port}{path}", timeout)

    def probe(self) -> dict:
        """调试端口可达性（不按 Browser 字段验身份——PROTOCOL §1.1）。"""
        try:
            version = self._get("/json/version", 3.0)
        except Exception as exc:
            raise CdpError(f"调试端口 {self.port} 不可达: {exc}") from exc
        if not isinstance(version, dict):
            raise CdpError(f"调试端口 {self.port} /json/version 形状不符")
        return version

    def targets(self) -> list[dict]:
        try:
            data = self._get("/json/list", 3.0)
        except Exception as exc:
            raise CdpError(f"读取调试端口页面列表失败: {exc}") from exc
        return data if isinstance(data, list) else []

    def attach(self, target: dict) -> CdpConnection:
        return self._ws_factory(target["webSocketDebuggerUrl"], 10.0)

    def open_target(
        self,
        url: str,
        *,
        wait: float = 15.0,
        domain: str | None = None,
        pick: Callable[[list[dict]], dict | None] | None = None,
    ) -> dict:
        """经浏览器级 ws 打开页面，并轮询到该页挂上调试端点。

        ``open_activity`` 保留原有的活动页优先选择；网页连接器（例如 AgentRouter）
        需要按自己的域名打开控制台，因此这里把“建页 + 轮询 + 选择”拆成通用原语。
        """
        version = self.probe()
        browser_url = version.get("webSocketDebuggerUrl")
        if not browser_url:
            raise CdpError("/json/version 缺 webSocketDebuggerUrl")
        with self._ws_factory(browser_url, 10.0) as browser:
            browser.call("Target.createTarget", {"url": url})
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            self.sleep(2.0)
            targets = self.targets()
            if pick is not None:
                target = pick(targets)
            else:
                target = next(
                    (
                        t
                        for t in targets
                        if t.get("type") in ("page", "webview")
                        and t.get("webSocketDebuggerUrl")
                        and (domain is None or domain in (t.get("url") or ""))
                    ),
                    None,
                )
            if target is not None:
                return target
        raise CdpError(f"页面打开超时（{wait}s）：{url}")

    def open_activity(self, url: str, *, wait: float = 15.0) -> CdpConnection:
        """活动页没开时经浏览器级 ws Target.createTarget 打开并轮询就绪。

        HTTP /json/new 建的 about:blank 会被客户端吞掉（PROTOCOL §1.1 实证）；
        页面挂上 WS 调试端点需要几秒，轮询 /json/list 直到可选。
        """
        target = self.open_target(url, wait=wait, pick=pick_activity_target)
        return self.attach(target)

    def close_target(self, target_id: str) -> None:
        """浏览器级关闭 target（Target.closeTarget）。用途：账户切换后旧活动页
        可能残留旧账户 Cookie——重开前先关净（附着旧页 = 签错账户风险）。
        target 已不存在（竞态消亡）= 关净语义已达成，不报错（与 localenv
        taskkill exit=128 宽容同事实同语义）；其余链路故障如实上抛。"""
        version = self.probe()
        browser_url = version.get("webSocketDebuggerUrl")
        if not browser_url:
            raise CdpError("/json/version 缺 webSocketDebuggerUrl")
        with self._ws_factory(browser_url, 10.0) as browser:
            try:
                browser.call("Target.closeTarget", {"targetId": target_id})
            except CdpError as exc:
                if "No target with" not in str(exc):
                    raise

    def cookies(self, conn: CdpConnection, url: str = "https://www.doubao.com") -> list[dict]:
        result = conn.call("Network.getCookies", {"urls": [url]})
        return list((result or {}).get("cookies") or [])

    def storage_cookies(self, domain: str | None = None) -> list[dict]:
        """浏览器级 Cookie 读取（Storage.getCookies）：不依附页面、不新建页面。

        用途：只读额度/流水需要会话 Cookie，而**读数据不得产生界面动作**——旧路径
        经活动页 Network.getCookies，活动页缺失时会 ``open_activity`` 在客户端里
        新开页面（客户端窗口被拉到前台，ADR-028）。Cookie 是浏览器级状态，与当前
        开着哪些页面无关；``domain`` 只做域过滤（含子域，前缀点忽略）。
        """
        version = self.probe()
        browser_url = version.get("webSocketDebuggerUrl")
        if not browser_url:
            raise CdpError("/json/version 缺 webSocketDebuggerUrl")
        with self._ws_factory(browser_url, 10.0) as browser:
            result = browser.call("Storage.getCookies", {}, wait=10.0)
        cookies = list((result or {}).get("cookies") or [])
        if domain is not None:
            cookies = [
                c
                for c in cookies
                if str(c.get("domain") or "").lstrip(".").endswith(domain)
            ]
        return cookies

    def evaluate(
        self,
        conn: CdpConnection,
        expression: str,
        *,
        wait: float = 20.0,
        await_promise: bool = False,
    ) -> Any:
        """页面 JS 求值；``await_promise=True`` 时等待 Promise 落定再取值
        （async 表达式不传 awaitPromise 会被 returnByValue 序列化成 {}——
        2026-11-16 doubao 取证 spike 实证）。"""
        params: dict[str, Any] = {"expression": expression, "returnByValue": True}
        if await_promise:
            params["awaitPromise"] = True
        result = conn.call("Runtime.evaluate", params, wait=wait)
        detail = (result or {}).get("exceptionDetails")
        if detail:
            raise CdpError(str(detail.get("exception", {}).get("description") or detail))
        return ((result or {}).get("result") or {}).get("value")

    def click(self, conn: CdpConnection, x: int, y: int) -> None:
        """受信任点击三连（PROTOCOL §6 ④）：前端校验 isTrusted 时合成事件会被忽略。"""
        conn.call("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y, "button": "none"})
        self.sleep(0.2)
        conn.call(
            "Input.dispatchMouseEvent",
            {"type": "mousePressed", "x": x, "y": y, "button": "left", "clickCount": 1, "buttons": 1},
        )
        self.sleep(0.12)
        conn.call(
            "Input.dispatchMouseEvent",
            {"type": "mouseReleased", "x": x, "y": y, "button": "left", "clickCount": 1, "buttons": 0},
        )

    def key(self, conn: CdpConnection, code: str) -> None:
        """受信任按键 down+up（Input.dispatchKeyEvent）。

        Radix menuitem 对完整信任指针三连不响应（2026-11-17 真机实证：点在
        [role=menuitem] 精确中心仍不触发 select）——键盘导航 + Enter 是弹层
        菜单项的可靠激活路径（PROTOCOL §9）。
        """
        vk = _KEY_VIRTUAL_CODES[code]
        conn.call(
            "Input.dispatchKeyEvent",
            {"type": "rawKeyDown", "windowsVirtualKeyCode": vk, "code": code, "key": code},
        )
        self.sleep(0.05)
        conn.call(
            "Input.dispatchKeyEvent",
            {"type": "keyUp", "windowsVirtualKeyCode": vk, "code": code, "key": code},
        )
