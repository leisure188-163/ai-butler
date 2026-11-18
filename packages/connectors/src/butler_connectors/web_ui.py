"""网页界面会话读取（通用底座）：从本机 Chromium 调试页读站点自己的登录态。

本模块做三件事：
- 找到一个已登录的目标页面（按域名匹配，不新开标签、不改页面）；
- 读取页面前端自己维护的 ``localStorage.user`` 快照（id/checked_in 等非密字段）；
- 提供受信任点击/等待页面原语，供各站点 adapter 编排自己的登录按钮。

它不认识任何站点，也不读取 access token / cookie 值；站点语义（登录即签到、
按钮签到等）由各连接器 adapter 解释。这样网页连接器不必依赖 Chrome cookie
解密（mac v20 应用绑定加密不可解，A2-03 §7），也能复用本机已登录页面。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

from butler_connectors.cdp import CdpChannel, CdpConnection, CdpError, http_json, ws_connect


@dataclass(frozen=True)
class WebPageState:
    """页面可见的非密状态：站点用户 id/用户名 + 站点自定义签到标记。"""

    user_id: int
    username: str
    checked_in: bool
    last_login_time: int
    quota: int
    url: str


class WebPageUnavailable(CdpError):
    """目标页面不存在或调试端口不可达（不可归因为登录态失效）。"""


#: 普通浏览器页面可能出现的 URL scheme；其余 scheme = 客户端应用内窗口（如 doubao://）
_BROWSER_SCHEMES = frozenset(
    {
        "http", "https", "about", "chrome", "chrome-extension", "devtools",
        "file", "data", "blob", "view-source",
    }
)


class PortNotBrowser(CdpError):
    """调试端口上是客户端应用内窗口（私有 scheme 页面），不是可打开网页的浏览器。"""

    def __init__(self, port: int, schemes: tuple[str, ...]) -> None:
        self.port = port
        self.schemes = schemes
        super().__init__(
            f"调试端口 {port} 上是客户端应用内窗口（{', '.join(f'{s}://' for s in schemes)}），"
            "不是可打开网页的浏览器"
        )


def require_browser_port(channel: CdpChannel) -> None:
    """端口归属校验：页面 scheme 出现客户端私有协议 → 显式拒绝（绝不往里开页）。

    只看 target 形状（进程归属），不看站点登录态；页面为空 = 放行（空白/刚启动
    的浏览器由后续 open_page 按真实错误上报）。依据：Chrome 的页面 scheme 只有
    http(s)/chrome/file 等；doubao:// 一类是 Electron/客户端私有协议，出现即证明
    该端口属于某个客户端应用，不是可承载网页的连接器浏览器。
    """
    pages = [t for t in channel.targets() if t.get("type") in ("page", "webview")]
    foreign = sorted(
        {urlsplit(t.get("url") or "").scheme for t in pages} - _BROWSER_SCHEMES - {""}
    )
    if foreign:
        raise PortNotBrowser(channel.port, tuple(foreign))


def _find_target(port: int, domain: str, *, channel: CdpChannel | None = None) -> dict | None:
    """按域名找页面；不新开标签（未打开 = 用户没在用这个网页，如实上报）。"""
    ch = channel or CdpChannel(port, http_get=http_json, ws_factory=ws_connect)
    for target in ch.targets():
        if target.get("type") not in ("page", "webview"):
            continue
        if domain in (target.get("url") or "") and target.get("webSocketDebuggerUrl"):
            return target
    return None


def read_user_state(conn: CdpConnection, channel: CdpChannel) -> WebPageState | None:
    """读页面前端 user 快照；未登录（无 id）返回 None，不把空对象当登录。"""
    expression = """(() => {
      try {
        const raw = localStorage.getItem('user');
        if (!raw) return null;
        const u = JSON.parse(raw);
        if (!u || !u.id) return null;
        return {
          user_id: Number(u.id),
          username: String(u.username || ''),
          checked_in: Boolean(u.checked_in),
          last_login_time: Number(u.last_login_time || 0),
          quota: Number(u.quota || 0)
        };
      } catch (e) { return null; }
    })()"""
    value = channel.evaluate(conn, expression)
    if not isinstance(value, dict) or not value.get("user_id"):
        return None
    return WebPageState(
        user_id=int(value["user_id"]),
        username=str(value.get("username") or ""),
        checked_in=bool(value.get("checked_in")),
        last_login_time=int(value.get("last_login_time") or 0),
        quota=int(value.get("quota") or 0),
        url="",
    )


def find_page(port: int, domain: str, *, channel: CdpChannel | None = None) -> dict | None:
    """按域名找当前页面；供调用方在 attach 前拿到 target。"""
    return _find_target(port, domain, channel=channel)


def open_page(
    port: int,
    domain: str,
    url: str,
    *,
    wait: float = 15.0,
    channel: CdpChannel | None = None,
) -> dict:
    """页面未打开时自动建页；返回挂上调试端点的 target，不读 cookie/token。"""
    ch = channel or CdpChannel(port, http_get=http_json, ws_factory=ws_connect)
    try:
        return ch.open_target(url, wait=wait, domain=domain)
    except CdpError as exc:
        raise WebPageUnavailable(
            f"浏览器未打开 {domain} 页面，自动打开失败：{exc}"
        ) from exc


def wait_for_page(
    port: int,
    domain: str,
    *,
    path_prefix: str = "",
    timeout: float = 10.0,
    channel: CdpChannel | None = None,
) -> dict | None:
    """轮询等待目标页面出现；返回 target，超时返回 None（调用方如实报错）。"""
    ch = channel or CdpChannel(port, http_get=http_json, ws_factory=ws_connect)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for target in ch.targets():
            url = target.get("url") or ""
            if target.get("type") not in ("page", "webview"):
                continue
            if domain not in url or not target.get("webSocketDebuggerUrl"):
                continue
            if path_prefix and not urlsplit(url).path.startswith(path_prefix):
                continue
            return target
        ch.sleep(0.5)
    return None


def rewrite_host(url: str, host: str) -> str:
    """只替换 URL 的 host，保留 scheme/path/query/fragment（OAuth 回调前缀规则）。"""
    parts = urlsplit(url)
    return urlunsplit((parts.scheme or "https", host, parts.path, parts.query, parts.fragment))


def click_selector(channel: CdpChannel, conn: CdpConnection, selector: str) -> bool:
    """按 CSS 选择器取第一个可见控件，用 CDP 受信任鼠标事件点击（React 不认合成事件）。"""
    payload = json.dumps({"selector": selector}, ensure_ascii=False)
    expression = f"""(() => {{
      const cfg = {payload};
      const el = document.querySelector(cfg.selector);
      if (!el) return null;
      el.scrollIntoView({{block: 'center', inline: 'center'}});
      const r = el.getBoundingClientRect();
      if (r.width <= 0 || r.height <= 0) return null;
      return {{x: r.left + r.width / 2, y: r.top + r.height / 2}};
    }})()"""
    rect = channel.evaluate(conn, expression)
    if not isinstance(rect, dict):
        return False
    channel.click(conn, int(rect["x"]), int(rect["y"]))
    return True


def click_text(
    channel: CdpChannel,
    conn: CdpConnection,
    text: str,
    *,
    selector: str = "button,[role='menuitem'],a",
    exact: bool = False,
) -> bool:
    """按可见文本点击控件；用于站点菜单/登录按钮，找不到返回 False。"""
    payload = json.dumps({"selector": selector, "text": text, "exact": exact}, ensure_ascii=False)
    expression = f"""(() => {{
      const cfg = {payload};
      const nodes = [...document.querySelectorAll(cfg.selector)];
      const el = nodes.find(e => {{
        const value = (e.innerText || e.textContent || '').trim().replace(/\\s+/g, ' ');
        return cfg.exact ? value === cfg.text : value.includes(cfg.text);
      }});
      if (!el) return null;
      el.scrollIntoView({{block: 'center', inline: 'center'}});
      const r = el.getBoundingClientRect();
      if (r.width <= 0 || r.height <= 0) return null;
      return {{x: r.left + r.width / 2, y: r.top + r.height / 2}};
    }})()"""
    rect = channel.evaluate(conn, expression)
    if not isinstance(rect, dict):
        return False
    channel.click(conn, int(rect["x"]), int(rect["y"]))
    return True


def read_page(port: int, domain: str) -> WebPageState:
    """读当前登录态；页面不存在 → WebPageUnavailable（不新开标签）。"""
    target = _find_target(port, domain)
    if target is None:
        raise WebPageUnavailable(f"浏览器未打开 {domain} 页面（请先打开并登录该站点）")
    channel = CdpChannel(port, http_get=http_json, ws_factory=ws_connect)
    with channel.attach(target) as conn:
        state = read_user_state(conn, channel)
        if state is None:
            raise WebPageUnavailable(f"{domain} 页面未登录（localStorage.user 无有效用户）")
        return WebPageState(
            user_id=state.user_id,
            username=state.username,
            checked_in=state.checked_in,
            last_login_time=state.last_login_time,
            quota=state.quota,
            url=str(target.get("url") or ""),
        )


def state_digest(state: WebPageState | None, *, display: str) -> str:
    """证据摘要：只写非密字段，便于待办定位；不写 token/cookie。"""
    if state is None:
        return f"{display} 页面未登录"
    return (
        f"{display} 用户 {state.username or state.user_id}，"
        f"checked_in={str(state.checked_in).lower()}，"
        f"last_login_time={state.last_login_time}"
    )
