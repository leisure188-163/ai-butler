"""butler 网关进程（R4 G1 骨架 + G5 协议面，ADR-012）：进程可启停、健康可观测。

- 独立 FastAPI 进程；协议面（OpenAI/Anthropic compatible，G5）以
  ``auth.require_bearer`` 依赖挂载（proxy.router），鉴权 key 由启动时生成/读取
  （0600 落数据根）
- 进程内直调 butler_core（裁决 1）：lifespan 经组装根 build_engine 构造 kit
  （credential_pool / record_usage_sample），端只准经 bridge 触引擎（ADR-001）；
  ``kit_factory`` 可注入（测试用假 kit，不碰真数据根）
- /health 无需鉴权（仅绑 127.0.0.1，主控与本机排障用）；含主控可达性、
  key 指纹（非 key 本体）、uptime、路由表装载态（G3）、协议面与上游适配器
  装载态（G5）——「健康可观测」的出口
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

from butler_gateway import auth, config, proxy, routing
from butler_gateway.control import ControlClient
from butler_gateway.forwarder import Forwarder
from butler_gateway.limiter import AccountLimiter
from butler_gateway.upstream import registered_providers

_VERSION = "0.2.0"

#: 测试注入点：返回 httpx transport（或 None=走真网络）。生产恒为 None。
_transport_factory: Callable[[], httpx.AsyncBaseTransport | None] = lambda: None

#: 测试注入点：kit 工厂（None = 生产装配 build_engine(default_db_path())）。
_kit_factory: Callable[[], object] | None = None


def _build_kit() -> object:
    """生产 kit 装配（裁决 1 进程内直调 core；默认不启动任何定时 job）。"""
    factory = _kit_factory
    if factory is not None:
        return factory()
    from butler_engine.bridge import build_engine, default_db_path  # 端触引擎只经 bridge（ADR-001）

    return build_engine(default_db_path())


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
    app.state.limiter = AccountLimiter()
    app.state.kit = _build_kit()
    app.state.forwarder = Forwarder(
        routes=app.state.routes,
        accounts=app.state.kit.accounts,  # type: ignore[attr-defined]  # kit 形状由 build_engine 保证
        pool=app.state.kit.credential_pool,
        limiter=app.state.limiter,
        meter=app.state.kit.record_usage_sample,
    )
    yield
    await app.state.control.aclose()
    app.state.kit.close()  # 排空事件后关总线（关闭路径不丢账）


def create_app() -> FastAPI:
    app = FastAPI(title="butler-gateway", version=_VERSION, lifespan=_lifespan)
    app.include_router(proxy.router)

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
            "proxy": {
                "surfaces": list(proxy.PROTOCOL_SURFACES),
                "provider_adapters": list(registered_providers()),
                "limiter_in_use": app.state.limiter.in_use,
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
