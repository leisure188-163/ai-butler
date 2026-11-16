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
- 路由热装载（R4-G6 演进）：server ``GET /api/v1/gateway/routes`` 契约为真相
  （后台节拍刷新 + TTL 闸），数据根 gateway-routes.json 为启动兜底（无 server
  环境 = 纯文件模式照常工作）；transport 工厂可注入：测试用 MockTransport
  验证主控可达/不可达两态
- 数据根纪律（2026-11-16）：网关必须与主控共用同一 ``BUTLER_DB``（路由账户
  名册 / 计量库 / 凭据池都在库里）；未设时启动告警并回落默认数据根——
  ``scripts\\start-gateway.ps1`` 已固化与主控同款覆盖
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from butler_gateway import auth, config, proxy, routing
from butler_gateway.control import ControlClient
from butler_gateway.forwarder import Forwarder
from butler_gateway.limiter import AccountLimiter
from butler_gateway.routes_source import RoutesSource
from butler_gateway.upstream import registered_providers

logger = logging.getLogger(__name__)

_VERSION = "0.3.0"

#: 测试注入点：返回 httpx transport（或 None=走真网络）。生产恒为 None。
_transport_factory: Callable[[], httpx.AsyncBaseTransport | None] = lambda: None

#: 测试注入点：kit 工厂（None = 生产装配 build_engine(default_db_path())）。
_kit_factory: Callable[[], object] | None = None

ROUTES_REFRESH_INTERVAL_SECONDS = 15.0  # 后台刷新节拍（RoutesSource 内部还有 TTL 闸）


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
    # 数据根一致性（2026-11-16）：网关与主控不同库 = 账户查不到 / 计量写进
    # 对方看不到的库（split-brain）。显式 BUTLER_DB 时静默对齐；未设时大声
    # 提示——默认根在本机还是虚拟化层吃 sqlite 伴生文件的目录
    db_override = os.environ.get("BUTLER_DB")
    if db_override:
        logger.info("网关数据根跟随 BUTLER_DB = %s（与主控同库）", db_override)
    else:
        logger.warning(
            "BUTLER_DB 未设置：网关 key/路由/计量库将落默认数据根 %s。"
            "若主控经 scripts/start-server.ps1 固化了项目内数据根，两进程会"
            "各用各库（账户/计量互相不可见）——请改用 scripts/start-gateway.ps1"
            " 或导出与主控一致的 BUTLER_DB",
            key_path.parent,
        )
    app.state.gateway_key = auth.load_or_create(key_path)
    app.state.key_file = key_path
    app.state.started_monotonic = time.monotonic()
    app.state.routes_path = config.routes_file()
    app.state.routes = routing.load_routes(app.state.routes_path)  # 非法显式报错（红线 5）
    app.state.control = ControlClient(
        config.server_url(), transport=_transport_factory()
    )
    # 路由热装载（R4-G6 演进）：server 契约为真相，文件为启动兜底
    app.state.routes_source = RoutesSource(
        fetch_from_server=app.state.control.fetch_routes,
        file_table=app.state.routes,
    )
    app.state.limiter = AccountLimiter()
    app.state.kit = _build_kit()
    app.state.forwarder = Forwarder(
        routes=app.state.routes_source.table(),
        accounts=app.state.kit.accounts,  # type: ignore[attr-defined]  # kit 形状由 build_engine 保证
        pool=app.state.kit.credential_pool,
        limiter=app.state.limiter,
        meter=app.state.kit.record_usage_sample,
    )
    refresh_task = asyncio.create_task(_refresh_routes_loop(app))
    yield
    refresh_task.cancel()
    await app.state.control.aclose()
    app.state.kit.close()  # 排空事件后关总线（关闭路径不丢账）


async def _refresh_routes_loop(app: FastAPI) -> None:
    """后台路由刷新：采纳 server 真相表并同步给 forwarder（取消即静默退出）。"""
    while True:
        await asyncio.sleep(ROUTES_REFRESH_INTERVAL_SECONDS)
        snapshot = await app.state.routes_source.refresh()
        app.state.forwarder.routes = snapshot.table


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
                "source": app.state.routes_source.snapshot.source,
                "rule_count": len(app.state.routes_source.table().rules),
                "models": [rule.model for rule in app.state.routes_source.table().rules],
                "account_count": len(app.state.routes_source.table().account_ids),
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
