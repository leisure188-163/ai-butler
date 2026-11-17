"""主控 server 的浏览器边界（ADR-014）：CORS 收窄 + Origin 硬拦截。

为什么两道都要（两个都很容易漏，漏了就是可被任意网页驱动的本地服务）：

- **CORS 只约束浏览器"能不能读响应"，不阻止请求送达**——恶意页面用简单请求
  （POST 表单型/无预检）照样能打到 127.0.0.1:8000，触发签到、改网关路由表、
  读账户台账；CORS 只是让它看不到回包。
- **localhost 不受混合内容拦截**：HTTPS 页面访问 http://127.0.0.1 被视为
  potentially trustworthy origin，所以"用户只会打开自己信任的页面"不成立。
  → 唯一可靠的位置是服务端：带 Origin 且不在白名单 = 403，请求不进路由。

白名单口径（本机单用户定位不变，A1-02 §8：不设 JWT / 用户体系）：

1. 静态白名单 = web 开发服务器（Vite 5173 的 localhost/127.0.0.1 两形态）；
   `BUTLER_ALLOWED_ORIGINS` 逗号分隔追加（装载期求值，改后需重启 server）。
2. **同源放行**：Origin 的 netloc 与请求 Host 完全一致且 Host 是本机回环
   （127.0.0.1 / localhost / ::1）→ 放行。桌面壳直连 `http://127.0.0.1:8000`、
   server 自身托管静态页、改端口运行，都靠这条自洽，不用逐个写死端口。
   **限定回环**是关键：DNS rebinding 场景下 Host 与 Origin 都是攻击者域名，
   不做回环限定就会把 rebinding 一并放进来。
3. 不带 Origin 的请求一律放行 —— curl / CLI / MCP / 网关控制面都不带 Origin，
   它们不是浏览器攻击面。
"""

from __future__ import annotations

import os
from urllib.parse import urlsplit

from starlette.datastructures import Headers
from starlette.responses import JSONResponse

#: 浏览器可访问的静态来源（web 开发服务器；生产走 vite /api 代理 = 同源或带
#: 5173 Origin 转发，两种形态都在此列）
DEFAULT_ALLOWED_ORIGINS = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
)

#: 追加白名单的环境变量（逗号分隔；装载期求值）
ALLOWED_ORIGINS_ENV = "BUTLER_ALLOWED_ORIGINS"

#: 同源放行只认本机回环（DNS rebinding 的 Host 是攻击者域名，必须被挡在外面）
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
_LOOPBACK_HOSTS_WITH_PORT = ("127.0.0.1", "localhost")


def allowed_origins() -> tuple[str, ...]:
    """静态白名单 = 默认 + `BUTLER_ALLOWED_ORIGINS` 追加（去重保序）。"""
    extra = [
        item.strip().rstrip("/")
        for item in os.environ.get(ALLOWED_ORIGINS_ENV, "").split(",")
        if item.strip()
    ]
    return tuple(dict.fromkeys([*DEFAULT_ALLOWED_ORIGINS, *extra]))


def _netloc(url: str) -> str:
    """取 netloc 小写形态；非法 URL 返回空串（调用方据此判不通过）。"""
    try:
        return urlsplit(url).netloc.lower()
    except ValueError:  # 极端畸形输入（头部注入尝试）
        return ""


def _hostname(netloc: str) -> str:
    """netloc → hostname（去端口；IPv6 由 urlsplit 走 `//` 前缀解析）。"""
    if not netloc:
        return ""
    try:
        return (urlsplit(f"//{netloc}").hostname or "").lower()
    except ValueError:
        return ""


def origin_allowed(origin: str, host_header: str | None) -> bool:
    """Origin 是否放行（白名单命中 或 回环同源）。host_header = 请求 Host 头。"""
    netloc = _netloc(origin)
    if not netloc:  # 畸形 Origin：不猜，直接拒
        return False
    if origin.rstrip("/") in allowed_origins():
        return True
    host = (host_header or "").strip().lower()
    if not host or _hostname(host) not in _LOOPBACK_HOSTS:
        return False
    return netloc == host  # 只认完全一致的 netloc（含端口），不做宽松比对


class OriginGuard:
    """ASGI 中间件：跨站页面（携带未授权 Origin）一律 403，请求不进路由。

    纯 ASGI 实现（不用 BaseHTTPMiddleware）——请求体不被中转，流式端点无副作用；
    挂载顺序 = 最外层（main.create_app 最后 add），CORS 也不会替它放行预检。
    """

    def __init__(self, platform) -> None:
        self.platform = platform

    async def __call__(self, scope, receive, send) -> None:
        if scope.get("type") != "http":
            await self.platform(scope, receive, send)
            return
        headers = Headers(scope=scope)
        origin = headers.get("origin")
        if origin is None or origin_allowed(origin, headers.get("host")):
            await self.platform(scope, receive, send)
            return
        # 不回显 Origin（不把攻击者输入写回响应体）
        response = JSONResponse(
            {
                "detail": (
                    "跨站页面禁止访问本地主控服务（Origin 未在允许名单中，"
                    "ADR-014；本地工具请直连，不带 Origin 头）"
                )
            },
            status_code=403,
        )
        await response(scope, receive, send)
