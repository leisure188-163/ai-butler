"""web_ui 通用底座：调试端口归属校验（客户端应用内窗口不当浏览器，ADR-026）。"""

from __future__ import annotations

import pytest

from butler_connectors.web_ui import PortNotBrowser, require_browser_port


class _Channel:
    """最小通道桩：只提供 targets()/port（校验逻辑的全部输入面）。"""

    def __init__(self, targets: list[dict], port: int = 9222) -> None:
        self.port = port
        self._targets = targets

    def targets(self) -> list[dict]:
        return self._targets


def _page(url: str, *, kind: str = "page") -> dict:
    return {"type": kind, "url": url, "webSocketDebuggerUrl": "ws://debug"}


def test_browser_pages_pass():
    require_browser_port(
        _Channel([_page("https://ps.air-outer.com/console"), _page("chrome://newtab/")])
    )


def test_empty_port_passes():
    require_browser_port(_Channel([]))


def test_app_window_is_rejected():
    channel = _Channel(
        [
            _page("doubao://doubao-chat/chat/42"),
            _page("doubao://doubao-launcher/chat?viewId=101"),
        ]
    )
    with pytest.raises(PortNotBrowser) as err:
        require_browser_port(channel)
    assert err.value.port == 9222
    assert "doubao://" in str(err.value)


def test_mixed_browser_and_app_window_rejected():
    channel = _Channel(
        [_page("https://www.doubao.com/chat"), _page("doubao://doubao-chat/chat/42")]
    )
    with pytest.raises(PortNotBrowser):
        require_browser_port(channel)


def test_non_page_targets_are_ignored():
    require_browser_port(
        _Channel([_page("doubao://doubao-background", kind="service_worker")])
    )
