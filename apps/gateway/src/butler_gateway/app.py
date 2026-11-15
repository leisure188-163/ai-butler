"""butler 网关进程（R4 G1 骨架，ADR-012）：进程可启停、健康可观测。

- 独立 FastAPI 进程；协议面（OpenAI/Anthropic compatible，G5）后续以
  ``auth.require_bearer`` 挂载，鉴权 key 由启动时生成/读取（0600 落数据根）
- /health 无需鉴权（仅绑 127.0.0.1，主控与本机排障用）；含主控可达性、
  key 指纹（非 key 本体）、uptime、路由表装载态（G3）——「健康可观测」的出口
- 路由表启动时从数据根 JSON 只读装载（裁决 6：规则 server 管、网关只读；
  server 管理面未落地前 = 文件源），transport 工厂可注入：测试用
  MockTransport 验证主控可达/不可达两态
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from butler_gateway import auth, config, routing
from butler_gateway.control import ControlClient

_VERSION = "0.1.0"

#: 测试注入点：返回 httpx transport（或 None=走真网络）。生产恒为 None。
_transport_factory: Callable[[], httpx.AsyncBaseTransport | None] = lambda: None


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    key_path = config.key_file()
    app.state.gateway_key = auth.load_or_create(key_path)
    app.state.key_file = key_path
    app.state.started_monotonic = time.monotonic()
    app.state.routes_path = config.routes_file()
    app.state.routes = routing.load_routes(app.state.routes_path)  # 非法显式报错（红线 5）
    app.state.control = ControlClient(
        config.server_url(), transport=_transport_factory()
    )
    yield
    await app.state.control.aclose()


def create_app() -> FastAPI:
    app = FastAPI(title="butler-gateway", version=_VERSION, lifespan=_lifespan)

    @app.get("/health")
    async def health() -> dict:
        probe = await app.state.control.probe()
        return {
            "status": "ok",
            "service": "butler-gateway",
            "version": _VERSION,
            "uptime_seconds": round(time.monotonic() - app.state.started_monotonic, 1),
            "bind": config.gateway_host(),
            "auth_key_file": str(app.state.key_file),
            "auth_key_fingerprint": auth.key_fingerprint(app.state.gateway_key),
            "routes": {
                "rules_file": str(app.state.routes_path),
                "rule_count": len(app.state.routes.rules),
                "models": [rule.model for rule in app.state.routes.rules],
                "account_count": len(app.state.routes.account_ids),
            },
            "control": {
                "server_url": probe.server_url,
                "reachable": probe.reachable,
                "latency_ms": probe.latency_ms,
                "checked_at": probe.checked_at,
                "error": probe.error,
            },
        }

    return app
