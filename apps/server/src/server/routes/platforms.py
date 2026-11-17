"""应用与导入域 API（连接器能力名册 + 停靠接入）。"""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter(tags=["butler"])


class PlatformOut(BaseModel):
    """应用名册行：连接器能力矩阵 + 调度缺省（A2-02 §2 的端侧投影）。"""

    id: str
    display: str
    capabilities: list[str]  # ActionKind.value 列表（core 词表）
    credential_kinds: list[str]
    schedule_times: list[str]  # HH:MM 触发时间
    account_id: str | None  # 首账号规范 id（兼容裸应用 id 调用），未导入 = None
    account_ids: list[str]  # 该应用下全部账户（ADR-003 多账号）


class ImportOut(BaseModel):
    target: str
    accounts: list[str]
    issues: list[str]


def _import_one(registry, kit, target: str) -> ImportOut:
    """单家停靠 + 顺带采集（dock 内部扫描异常已被注册表转成 issues，编排层不重复设防）。"""
    from butler_connectors.registry import DockContext

    [outcome] = registry.dock(
        DockContext(vault=kit.vault, register=kit.register_account), target=target
    )
    # 纯签到连接器（manifest.usage=false，如 agentrouter）没有额度可采；
    # 不能把“没有 usage 通道”当成 import 失败噪声。
    usage_enabled = True
    lookup = getattr(registry, "get", None)
    if callable(lookup):
        usage_enabled = bool(getattr(lookup(target).manifest, "usage", True))
    if usage_enabled:
        for account_id in outcome.accounts:
            collected = kit.collect_usage.execute(target, account_id)
            if collected.error:
                outcome.issues.append(f"用量采集：{collected.error}")
    return ImportOut(target=outcome.target, accounts=outcome.accounts, issues=outcome.issues)


@router.get("/platforms", response_model=list[PlatformOut])
def list_platforms(request: Request) -> list[PlatformOut]:
    """应用名册：连接器能力矩阵（manifest 投影，端零映射）。"""
    registry = request.app.state.registry
    kit = request.app.state.kit
    docked: dict[str, list[str]] = {}
    for account in kit.accounts.list_all():
        docked.setdefault(account.platform, []).append(account.id)
    out: list[PlatformOut] = []
    for platform in registry.platforms():
        if getattr(platform.manifest, "retired", False):
            continue
        schedule = platform.manifest.schedule.get("provision.run")
        ids = sorted(docked.get(platform.manifest.id, []))
        out.append(
            PlatformOut(
                id=platform.manifest.id,
                display=platform.display,
                capabilities=sorted(platform.manifest.capabilities),
                credential_kinds=list(platform.manifest.credential.kinds)
                if platform.manifest.credential
                else [],
                schedule_times=list(schedule.times) if schedule else [],
                account_id=ids[0] if ids else None,
                account_ids=ids,
            )
        )
    return out


@router.post("/platforms/{target}/import", response_model=ImportOut)
def import_platform(target: str, request: Request) -> ImportOut:
    """导入（接入扫描）：扫本机客户端 → 注册卡位 → 凭据入库。

    单家失败不拖累全家族：结果如实分列（accounts/issues），不静默。
    dock 顺带采集（R2-F）：新泊位立即产雷达第一帧；采集失败进 issues，
    绝不打断导入本身（CollectUsage 已把端口异常收进 outcome.error）。
    """
    return _import_one(request.app.state.registry, request.app.state.kit, target)


@router.post("/platforms/import-all", response_model=list[ImportOut])
def import_all_platforms(request: Request) -> list[ImportOut]:
    """一键导入：全部未泊位连接器逐家接入（结果如实分列，单家失败已在 dock 内收进 issues）。

    选谁不选谁是编排语义，归 server（A1-02 编排层）；端零入参。
    """
    registry = request.app.state.registry
    kit = request.app.state.kit
    docked = {a.platform for a in kit.accounts.list_all()}
    return [
        _import_one(registry, kit, platform.manifest.id)
        for platform in registry.platforms()
        if platform.manifest.id not in docked and not getattr(platform.manifest, "retired", False)
    ]
