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

    from butler_connectors.registry import load_registry
    from butler_engine.bridge import ScheduleEntry

    registry = load_registry()
    kit.register_provision_ports(
        targets=registry.provision_ports(vault=kit.vault, transport=None)
    )
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
    entries = [
        ScheduleEntry(
            target=entry["target"],
            times=tuple(entry["times"]),
            refresh_at=entry["refresh_at"],
            budget=timedelta(seconds=entry["budget_seconds"]),
        )
        for entry in registry.schedule_entries()
    ]
    app.state.registry = registry  # 端读 manifest/导入分发用（server 自持装配面）
    if os.environ.get("BUTLER_SCHEDULE", "1") != "0" and entries:
        kit.start_checkin_schedule(entries)
    if os.environ.get("BUTLER_SCHEDULE", "1") != "0":
        kit.start_usage_scans()  # R2：每日用量采集（启动即补采第一帧，IntervalJob 语义）
        kit.start_health_scans()  # R3-2：每日体检轮询（Run 进台账，连败升级走既有链）
    kit.start_expiry_scans()


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    from butler_engine.bridge import EngineKit, build_engine, default_db_path

    db_path = os.environ.get("BUTLER_DB") or default_db_path()
    kit: EngineKit = build_engine(db_path)
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
