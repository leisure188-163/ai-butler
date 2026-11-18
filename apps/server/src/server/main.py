"""主控 server（A1-02）：FastAPI 薄壳，唯一职责 = 暴露 core 用例 + 契约。

- 端只准经 bridge 触达引擎（规约 R4）；路由不写业务规则、不做状态语义映射
  （端零映射，红线 2）——响应里的 level/status/repair 文案全部由 core 产出
- DB 路径经 BUTLER_DB 环境变量覆盖；默认 = 平台数据根 butler.db（A4-01 §5）
- 连接器装配（ADR-005）：注册表装载 → 端口挂载 → 导入调度 + 用量采集 + 到期扫描；
  BUTLER_SCHEDULE=0 显式关闭全部调度（测试/排障口）
- 浏览器边界（ADR-014）：CORS 收白名单 + OriginGuard 硬拦截——不带 Origin 的
  本地工具（curl/CLI/MCP/桌面壳）照旧直连，跨站页面一律 403
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from server.routes.api import router as api_router
from server.security import OriginGuard, allowed_origins


def _assemble_connectors(kit) -> None:
    """连接器家族装配（ADR-005）：端口 / 调度条目 / 到期扫描都在这里挂上。"""
    from datetime import timedelta

    from butler_connectors.paths import custom_connectors_root
    from butler_connectors.registry import load_registry

    # 内置包 + 用户自定义连接器目录（2026-11-18）：自定义平台与内置同构装载
    registry = load_registry(custom_root=custom_connectors_root())
    provisions = registry.provision_ports(vault=kit.vault, transport=None)
    kit.register_provision_ports(targets=provisions)
    # 探针端口随 register_health_ports 挂载（同一条 target 路由 + 每日轮询名册，
    # A2-03 §4）；target 撞车时显式拒绝（红线 5）
    kit.register_health_ports(
        targets=registry.health_ports(vault=kit.vault, transport=None)
    )
    kit.register_usage_ports(
        targets=registry.usage_ports(vault=kit.vault, transport=None)
    )
    # 会话扫描源（R5-S1，ADR-013）：逐家登记的连接器装配；未登记家 = None 跳过
    for conn_id in registry.ids():
        source = registry.session_source(conn_id)
        if source is not None:
            kit.register_session_source(source)
    app.state.registry = registry  # 端读 manifest/导入分发用（server 自持装配面）
    sync_platform_facts(kit, registry, provisions)
    # 调度条目：DB 真相源合成（用户覆盖优先于 manifest 缺省，2026-11-18）
    from server.routes.platforms import compose_schedule_entries

    entries = compose_schedule_entries(registry, kit)
    if os.environ.get("BUTLER_SCHEDULE", "1") != "0" and entries:
        kit.start_checkin_schedule(entries)
    if os.environ.get("BUTLER_SCHEDULE", "1") != "0":
        kit.start_usage_scans()  # R2：每日用量采集（启动即补采第一帧，IntervalJob 语义）
        kit.start_health_scans()  # R3-2：每日体检轮询（Run 进台账，连败升级走既有链）
    kit.start_expiry_scans()


def _read_client_version(port) -> str:
    """客户端版本探测钩子（plat_platform.client_version）：端口实例未实现/读不到
    均落空串（列语义 "" = 未知，名册如实显示未知，不静默造数据）。

    注意取 provision 端口实例（adapter），不是 manifest 描述对象。"""
    hook = getattr(port, "read_client_version", None)
    if not callable(hook):
        return ""
    try:
        return hook() or ""
    except Exception:
        return ""


def sync_platform_facts(kit, registry, provisions) -> None:
    """平台册同步（ADR-021/022）：manifest 事实落 plat_platform，DB 为真相源；
    退役/删掉的连接器不进 facts（自动落 deprecated 不删行，审计可溯）。"""
    from butler_core.platforms.domain import PlatformEntry
    from butler_core.shared.time import now_utc

    facts = []
    for conn in registry.platforms():
        m = conn.manifest
        if getattr(m, "retired", False):
            continue
        sched = m.schedule.get("provision.run")
        facts.append(
            PlatformEntry(
                platform_code=m.id,
                platform_name=m.display,
                created_at=now_utc(),
                platform_kind=m.kind,
                capabilities=tuple(sorted(m.capabilities)),
                credential_kinds=tuple(m.credential.kinds) if m.credential else (),
                schedule_times=tuple(sched.times) if sched else (),
                client_version=_read_client_version(provisions.get(m.id)),
            )
        )
    kit.sync_platforms.execute(tuple(facts))


def reload_connectors(app) -> None:
    """连接器热重载（自定义平台增删后）：重装端口 → 名册同步 → 调度重排。

    会话扫描源只准装配一次（ADR-013），这里不重装——自定义平台没有会话扫描源。
    已删平台的端口对象会残留在路由表里（无调度条目、名册已 deprecated，不会被
    排班；避免为此重建整条执行链的装配面）。
    """
    from butler_connectors.paths import custom_connectors_root
    from butler_connectors.registry import load_registry

    from server.routes.platforms import compose_schedule_entries

    kit = app.state.kit
    registry = load_registry(custom_root=custom_connectors_root())
    provisions = registry.provision_ports(vault=kit.vault, transport=None)
    kit.register_provision_ports(targets=provisions, replace=True)
    kit.register_health_ports(
        targets=registry.health_ports(vault=kit.vault, transport=None), replace=True
    )
    kit.register_usage_ports(
        targets=registry.usage_ports(vault=kit.vault, transport=None), replace=True
    )
    app.state.registry = registry
    sync_platform_facts(kit, registry, provisions)
    kit.update_checkin_schedule(compose_schedule_entries(registry, kit))


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    from butler_engine.bridge import EngineKit, build_engine, default_db_path

    db_path = os.environ.get("BUTLER_DB") or default_db_path()
    kit: EngineKit = build_engine(
        db_path,
        system_notifications=os.environ.get("BUTLER_SYSTEM_NOTIFY", "1") != "0",
    )
    app.state.kit = kit
    _assemble_connectors(kit)
    yield
    kit.close()


def create_app() -> FastAPI:
    app = FastAPI(title="butler", version="0.1.0", lifespan=_lifespan)
    # 浏览器边界（ADR-014）：CORS 只挡"读"，跨站"写"必须由 OriginGuard 在服务端拦。
    # add_middleware 为后加者在外层 → OriginGuard 最后加 = 最外层，未授权 Origin
    # 连预检都拿不到 CORS 放行。
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(allowed_origins()),
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(OriginGuard)
    app.include_router(api_router, prefix="/api/v1")

    @app.get("/health")
    def health():
        return {"status": "ok"}

    return app


app = create_app()
