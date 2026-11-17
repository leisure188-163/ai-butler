"""平台与导入域 API（plat_platform 名册投影 + 导入分发）。"""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter(tags=["butler"])


class PlatformOut(BaseModel):
    """平台名册行：连接器能力矩阵 + 调度缺省（A2-02 §2 的端侧投影）。"""

    id: str
    display: str
    kind: str  # 平台类型：web=网页版 / client=本机客户端（"" = 未申报）
    client_version: str  # 本机客户端版本（"" = 探不到/不适用）
    capabilities: list[str]  # ActionKind.value 列表（core 词表）
    credential_kinds: list[str]
    schedule_times: list[str]  # HH:MM 生效时间（用户覆盖优先，见下）
    schedule_overridden: bool  # True = 用户改过（可"恢复默认"）
    account_id: str | None  # 首账号规范 id（兼容裸平台 id 调用），未导入 = None
    account_ids: list[str]  # 该平台下全部账户（ADR-003 多账号）


class ScheduleIn(BaseModel):
    """调度执行时间写入（2026-11-18）：null = 恢复跟随 manifest；[] = 该平台不排班。"""

    times: list[str] | None = None


class ImportOut(BaseModel):
    target: str
    accounts: list[str]
    issues: list[str]


def _import_one(registry, kit, target: str) -> ImportOut:
    """单家导入 + 顺带采集（dock 内部扫描异常已被注册表转成 issues，编排层不重复设防）。"""
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
    """平台名册（ADR-021/022）：读 plat_platform 名册表（DB 为真相源）+ 台账并账。

    启动时组合根已把 manifest 事实同步进名册（退役自动落 deprecated）；
    这里只做 DB 投影 + 账户并账，不再穿连接器包拼装（端零映射）。
    """
    kit = request.app.state.kit
    docked: dict[str, list[str]] = {}
    for account in kit.accounts.list_all():
        docked.setdefault(account.platform_code, []).append(account.id)
    out: list[PlatformOut] = []
    for platform in kit.platforms.list_all():
        if platform.deprecated_at is not None or not platform.is_active:
            continue
        ids = sorted(docked.get(platform.platform_code, []))
        out.append(
            PlatformOut(
                id=platform.platform_code,
                display=platform.platform_name,
                kind=platform.platform_kind,
                client_version=platform.client_version,
                capabilities=sorted(platform.capabilities),
                credential_kinds=list(platform.credential_kinds),
                schedule_times=list(
                    platform.schedule_override
                    if platform.schedule_override is not None
                    else platform.schedule_times
                ),
                schedule_overridden=platform.schedule_override is not None,
                account_id=ids[0] if ids else None,
                account_ids=ids,
            )
        )
    return out


def compose_schedule_entries(registry, kit) -> list:
    """调度条目合成（DB 真相源）：用户覆盖优先于 manifest 缺省；空时间=不排班。

    启动与"改调度后热更新"共用本函数，保证两条路径语义一致。
    """
    from datetime import timedelta

    from butler_engine.bridge import ScheduleEntry

    overrides = {p.platform_code: p for p in kit.platforms.list_all()}
    out = []
    for raw in registry.schedule_entries():
        target = raw["target"]
        row = overrides.get(target)
        times = list(raw["times"])
        if row is not None and row.schedule_override is not None:
            times = list(row.schedule_override)
        if not times:
            continue  # 用户显式不排班
        out.append(
            ScheduleEntry(
                target=target,
                times=tuple(times),
                refresh_at=raw["refresh_at"],
                budget=timedelta(seconds=raw["budget_seconds"]),
            )
        )
    return out


@router.put("/platforms/{platform_code}/schedule", response_model=PlatformOut)
def set_platform_schedule(platform_code: str, body: ScheduleIn, request: Request):
    """改调度执行时间（平台管理页）：落 DB 覆盖 + 调度器热替换，即刻生效。

    校验：HH:MM（core PlatformEntry 同源规则）、去重升序；平台不存在 = 404。
    """
    import re

    from fastapi import HTTPException

    kit = request.app.state.kit
    registry = request.app.state.registry
    times = body.times
    if times is not None:
        times = sorted(set(t.strip() for t in times if t.strip()))
        bad = [t for t in times if not re.match(r"^([01]\d|2[0-3]):[0-5]\d$", t)]
        if bad:
            raise HTTPException(status_code=400, detail=f"时间格式须为 HH:MM：{bad}")
    updated = kit.platforms.set_schedule_override(platform_code, tuple(times) if times is not None else None)
    if updated is None:
        raise HTTPException(status_code=404, detail=f"平台不存在：{platform_code}")
    kit.update_checkin_schedule(compose_schedule_entries(registry, kit))
    docked = [a.id for a in kit.accounts.list_all() if a.platform_code == platform_code]
    return PlatformOut(
        id=updated.platform_code,
        display=updated.platform_name,
        kind=updated.platform_kind,
        client_version=updated.client_version,
        capabilities=sorted(updated.capabilities),
        credential_kinds=list(updated.credential_kinds),
        schedule_times=list(
            updated.schedule_override
            if updated.schedule_override is not None
            else updated.schedule_times
        ),
        schedule_overridden=updated.schedule_override is not None,
        account_id=docked[0] if docked else None,
        account_ids=sorted(docked),
    )


@router.post("/platforms/{target}/import", response_model=ImportOut)
def import_platform(target: str, request: Request) -> ImportOut:
    """导入（接入扫描）：扫本机客户端 → 账户注册 → 凭据入库。

    单家失败不拖累全家族：结果如实分列（accounts/issues），不静默。
    dock 顺带采集（R2-F）：新账户立即产雷达第一帧；采集失败进 issues，
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
    docked = {a.platform_code for a in kit.accounts.list_all()}
    # 选谁导入 = 名册表裁决（ADR-021/022）：活跃且未退役、未导入的平台；
    # retired 连接器启动同步时已落 deprecated，不进名册，天然被排除。
    targets = sorted(
        p.platform_code
        for p in kit.platforms.list_all()
        if p.is_active and p.deprecated_at is None and p.platform_code not in docked
    )  # 按 platform_code 排序：批量结果顺序确定，不随名册插入序漂移
    return [_import_one(registry, kit, target) for target in targets]
