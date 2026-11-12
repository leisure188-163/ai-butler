"""主控 server（A1-02）：FastAPI 薄壳，唯一职责 = 暴露 core 用例 + 契约。

- 端只准经 bridge 触达引擎（规约 R4）；路由不写业务规则、不做状态语义映射
  （端零映射，红线 2）——响应里的 level/status/repair 文案全部由 core 产出
- DB 路径经 KABAO_DB 环境变量覆盖；默认 = 平台数据根 kabao.db（A4-01 §5）
- 连接器装配（ADR-003）：注册表装载 → 端口挂载 → 导入调度 + 用量采集 + 到期扫描；
  KABAO_SCHEDULE=0 显式关闭全部调度（测试/排障口）
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from server.routes.api import router as api_router


def _assemble_connectors(kit) -> None:
    """连接器家族装配（ADR-003）：端口 / 调度条目 / 到期扫描都在这里挂上。"""
    from datetime import timedelta

    from kabao_connectors.registry import load_registry
    from kabao_engine.bridge import ScheduleEntry

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
    if os.environ.get("KABAO_SCHEDULE", "1") != "0" and entries:
        kit.start_checkin_schedule(entries)
    if os.environ.get("KABAO_SCHEDULE", "1") != "0":
        kit.start_usage_scans()  # R2：每日用量采集（启动即补采第一帧，IntervalJob 语义）
        kit.start_health_scans()  # R3-2：每日体检轮询（Run 进台账，连败升级走既有链）
    kit.start_expiry_scans()


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    from kabao_engine.bridge import EngineKit, build_engine, default_db_path

    db_path = os.environ.get("KABAO_DB") or default_db_path()
    kit: EngineKit = build_engine(db_path)
    app.state.kit = kit
    _assemble_connectors(kit)
    yield
    kit.close()


def create_app() -> FastAPI:
    app = FastAPI(title="kabao", version="0.1.0", lifespan=_lifespan)
    app.add_middleware(
        CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
    )
    app.include_router(api_router, prefix="/api/v1")

    @app.get("/health")
    def health():
        return {"status": "ok"}

    return app


app = create_app()
