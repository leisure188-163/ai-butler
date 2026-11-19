"""平台与导入域 API（plat_platform 名册投影 + 导入分发）。"""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter(tags=["butler"])


class PlatformOut(BaseModel):
    """平台名册行：连接器能力矩阵 + 调度缺省（A2-02 §2 的端侧投影）。"""

    id: str
    platform_name: str  # 平台名：接入时来自 manifest，之后归用户（ADR-031，可改名）
    name_is_default: bool  # 名字仍是连接器申报名（前端据此决定要不要显示「恢复默认名」）
    kind: str  # 平台类型：web=网页版 / client=本机客户端（"" = 未申报）
    client_version: str  # 本机客户端版本（"" = 探不到/不适用）
    icon: str  # 平台图标（2026-11-19）：96px PNG 的 data URI；"" = 无图标（前端回落色点）
    capabilities: list[str]  # ActionKind.value 列表（core 词表）
    credential_kinds: list[str]
    schedule_times: list[str]  # HH:MM 生效时间（用户覆盖优先，见下）
    schedule_overridden: bool  # True = 用户改过（可"恢复默认"）
    active: bool  # 平台启用状态（false = 停用：不排班，仍可手动操作）
    account_id: str | None  # 首账号规范 id（兼容裸平台 id 调用），未导入 = None
    account_ids: list[str]  # 该平台下全部账户（ADR-003 多账号）


class ScheduleIn(BaseModel):
    """调度执行时间写入（2026-11-18）：null = 恢复跟随 manifest；[] = 该平台不排班。"""

    times: list[str] | None = None


class ImportOut(BaseModel):
    target: str
    accounts: list[str]
    issues: list[str]


class PlatformRemovedOut(BaseModel):
    """移出名册结果（2026-11-19）：只删平台事实行，账户/台账/凭据保留。"""

    platform_code: str
    removed: bool
    message: str


class PlatformCandidateOut(BaseModel):
    """未纳册的连接器平台（平台页「未导入的平台」清单，2026-11-19 用户裁决）。"""

    platform_code: str
    platform_name: str
    kind: str  # web=网页版 / client=本机客户端
    capabilities: list[str]
    account_ids: list[str]  # 名册外已有账户（>0 = 有账户待归位）


def _has_connector(registry, target: str) -> bool:
    """该 platform_code 是否有连接器实现（没实现 = 不可接入，不是服务器错误）。"""
    getter = getattr(registry, "get", None)
    if not callable(getter):
        return True  # 替身/极简注册表：交给 dock 自己判定
    try:
        getter(target)
        return True
    except KeyError:
        return False


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


def _manifest_display(registry, target: str) -> str | None:
    """连接器 manifest 申报的平台名（"恢复原名"用）；没有实现 → None。"""
    getter = getattr(registry, "get", None)
    if not callable(getter):
        return None
    try:
        return getter(target).manifest.display.strip() or None
    except KeyError:
        return None


def _platform_out(platform, ids: list[str], registry=None) -> PlatformOut:
    """平台册行投影（名册读端点与改名端点共用，避免三处各拼一遍）。

    name_is_default 只在运行时跟 manifest 比一次（DB 不存第二份名字）；
    连接器已下线（取不到 manifest）时按"非默认"处理，不误报可恢复。
    """
    display = _manifest_display(registry, platform.platform_code) if registry else None
    return PlatformOut(
        id=platform.platform_code,
        platform_name=platform.platform_name,
        name_is_default=display is None or display == platform.platform_name,
        kind=platform.platform_kind,
        client_version=platform.client_version,
        icon=platform.icon,
        capabilities=sorted(platform.capabilities),
        credential_kinds=list(platform.credential_kinds),
        schedule_times=list(
            platform.schedule_override
            if platform.schedule_override is not None
            else platform.schedule_times
        ),
        schedule_overridden=platform.schedule_override is not None,
        active=platform.is_active,
        account_id=ids[0] if ids else None,
        account_ids=ids,
    )


@router.get("/platforms", response_model=list[PlatformOut])
def list_platforms(request: Request) -> list[PlatformOut]:
    """平台名册（ADR-021/022）：读 plat_platform 名册表（DB 为真相源）+ 台账并账。

    启动时组合根已把 manifest 事实同步进名册（退役自动落 deprecated）；
    这里只做 DB 投影 + 账户并账，不再穿连接器包拼装（端零映射）。
    """
    kit = request.app.state.kit
    registry = request.app.state.registry
    docked: dict[str, list[str]] = {}
    for account in kit.accounts.list_all():
        docked.setdefault(account.platform_code, []).append(account.id)
    out: list[PlatformOut] = []
    for platform in kit.platforms.list_all():
        if platform.deprecated_at is not None:
            continue  # 退役平台不出现；停用（is_active=false）要显示，否则用户无法再启用
        out.append(
            _platform_out(platform, sorted(docked.get(platform.platform_code, [])), registry)
        )
    return out


@router.post("/platforms/resync", response_model=list[PlatformOut])
def resync_platforms(request: Request) -> list[PlatformOut]:
    """同步平台（运行期补偿入口，ADR-031）：重扫连接器 → manifest 事实落名册 → 重排调度。

    为什么需要它：名册只在**后端启动**和连接器热重载时自动同步，运行期没有任何
    入口。于是「平台表被清空」「连接器升级改了 manifest」只能靠重启后端恢复——
    而「接入」是导账户、不建名册（表空时「接入全部」候选为 0，一个也不接）。

    语义与启动同步完全一致，不复刻第二套：新连接器首插落名、已存在行不被覆盖
    （名字归用户，ADR-031）；已下线连接器落 deprecated 不删行。

    返回同步后的名册（前端可直接用它替换列表，不必二次 GET）。
    """
    from server.main import sync_platform_facts  # 延迟 import：main 会 import 本模块

    kit = request.app.state.kit
    registry = request.app.state.registry
    provisions = getattr(request.app.state, "provisions", None)
    sync_platform_facts(kit, registry, provisions)
    kit.update_checkin_schedule(compose_schedule_entries(registry, kit))
    return list_platforms(request)


@router.get("/platforms/unimported", response_model=list[PlatformCandidateOut])
def list_unimported_platforms(request: Request) -> list[PlatformCandidateOut]:
    """未纳册的连接器平台（2026-11-19 用户裁决）：自动同步只纳本机客户端，
    网页版等被策略跳过的连接器留在这份清单里，由用户手动「导入」。

    判据 = 连接器存在（未退役）且名册里没有活跃行；account_ids 如实带上
    名册外的既有账户（>0 = 有账户待归位，导入后自动重新挂上）。端零加工。
    """
    kit = request.app.state.kit
    registry = request.app.state.registry
    roster = {p.platform_code for p in kit.platforms.list_all() if p.deprecated_at is None}
    docked: dict[str, list[str]] = {}
    for account in kit.accounts.list_all():
        docked.setdefault(account.platform_code, []).append(account.id)
    out: list[PlatformCandidateOut] = []
    for conn in registry.platforms():
        m = conn.manifest
        if getattr(m, "retired", False) or m.id in roster:
            continue
        out.append(
            PlatformCandidateOut(
                platform_code=m.id,
                platform_name=m.display,
                kind=m.kind,
                capabilities=sorted(m.capabilities),
                account_ids=sorted(docked.get(m.id, [])),
            )
        )
    return sorted(out, key=lambda c: c.platform_code)


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
        if row is not None and not row.is_active:
            continue  # 平台已停用：不排班（手动领取仍可）
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


class PlatformPatchIn(BaseModel):
    """平台信息编辑（2026-11-18）：开放四项——平台名称、启用状态、调度执行时间、图标。

    `model_fields_set` 区分"没传"与"传了 null"：times=null 恢复默认，times=[] 不排班。
    `platform_name` 为空串 = 恢复连接器申报的名称（ADR-031）。
    `icon`（2026-11-19）为 png data URI：空串 = 清空图标（回落身份色点），不传 = 不动。
    """

    platform_name: str | None = None  # 平台名（空串 = 恢复 manifest 名）
    active: bool | None = None  # 启用状态
    times: list[str] | None = None  # 调度执行时间
    icon: str | None = None  # 平台图标（png data URI，空串 = 清空）


_HHMM_RE = r"^([01]\d|2[0-3]):[0-5]\d$"


def _normalize_times(times: list[str]) -> list[str]:
    """去空白、去重、升序；非法格式显式 400（不自作丢弃）。"""
    from fastapi import HTTPException

    import re

    cleaned = sorted({t.strip() for t in times if t.strip()})
    bad = [t for t in cleaned if not re.match(_HHMM_RE, t)]
    if bad:
        raise HTTPException(status_code=400, detail=f"时间格式须为 HH:MM：{bad}")
    return cleaned


@router.patch("/platforms/{platform_code}", response_model=PlatformOut)
def patch_platform(platform_code: str, body: PlatformPatchIn, request: Request):
    """编辑平台（平台名称 / 启用状态 / 调度时间）：落 DB + 调度热替换，即刻生效。

    **平台编码（platform_code）不可改**：它被账户、台账、调度条目、CLI 目标引用，
    改名等于拆迁（ADR-031）。能力、凭据类型、客户端版本仍来自连接器探测。
    """
    from fastapi import HTTPException

    kit = request.app.state.kit
    registry = request.app.state.registry
    fields = body.model_fields_set
    new_name: str | None = None
    active: bool | None = None
    if "platform_name" in fields and body.platform_name is not None:
        new_name = body.platform_name.strip()
        if not new_name:
            # 空串 = 恢复连接器申报的名称（不保留第二列，运行时向 manifest 取）
            new_name = _manifest_display(registry, platform_code)
            if new_name is None:
                raise HTTPException(
                    status_code=400,
                    detail="该平台没有连接器实现，无法恢复原名——请直接填写平台名称",
                )
        elif len(new_name) > 40:
            raise HTTPException(status_code=400, detail="平台名称过长（≤40）")
    if "active" in fields:
        active = body.active
    new_icon: str | None = None
    if "icon" in fields and body.icon is not None:
        new_icon = body.icon.strip()
        if new_icon and not new_icon.startswith("data:image/png;base64,"):
            # 只收 png data URI：前端上传前统一用 canvas 转码，端上不再兼容第二套格式
            raise HTTPException(
                status_code=400, detail="图标须为 png data URI（data:image/png;base64,…）"
            )
        if len(new_icon) > 200_000:
            raise HTTPException(status_code=400, detail="图标过大（上限约 200KB）")
    updated = kit.platforms.update_profile(
        platform_code, platform_name=new_name, is_active=active, icon=new_icon
    )
    if updated is None:
        raise HTTPException(status_code=404, detail=f"平台不存在：{platform_code}")
    if "times" in fields:
        times = _normalize_times(body.times) if body.times is not None else None
        updated = kit.platforms.set_schedule_override(
            platform_code, tuple(times) if times is not None else None
        )
        if updated is None:
            raise HTTPException(status_code=404, detail=f"平台不存在：{platform_code}")
    kit.update_checkin_schedule(compose_schedule_entries(registry, kit))
    docked = sorted(a.id for a in kit.accounts.list_all() if a.platform_code == platform_code)
    return _platform_out(updated, docked, registry)


@router.put("/platforms/{platform_code}/schedule", response_model=PlatformOut)
def set_platform_schedule(platform_code: str, body: ScheduleIn, request: Request):
    """改调度执行时间（平台管理页）：落 DB 覆盖 + 调度器热替换，即刻生效。

    校验：HH:MM（core PlatformEntry 同源规则）、去重升序；平台不存在 = 404。
    """
    from fastapi import HTTPException

    kit = request.app.state.kit
    registry = request.app.state.registry
    times = _normalize_times(body.times) if body.times is not None else None
    updated = kit.platforms.set_schedule_override(platform_code, tuple(times) if times is not None else None)
    if updated is None:
        raise HTTPException(status_code=404, detail=f"平台不存在：{platform_code}")
    kit.update_checkin_schedule(compose_schedule_entries(registry, kit))
    docked = sorted(a.id for a in kit.accounts.list_all() if a.platform_code == platform_code)
    return _platform_out(updated, docked, registry)


@router.post("/platforms/{target}/import", response_model=ImportOut)
def import_platform(target: str, request: Request) -> ImportOut:
    """导入（接入扫描）：扫本机客户端 → 账户注册 → 凭据入库。

    单家失败不拖累全家族：结果如实分列（accounts/issues），不静默。
    dock 顺带采集（R2-F）：新账户立即产雷达第一帧；采集失败进 issues，
    绝不打断导入本身（CollectUsage 已把端口异常收进 outcome.error）。

    未知 platform_code（名册里没有连接器实现）显式 422，不再让 KeyError 冒成 500：
    新手点「接入」看到的必须是「为什么接不进」，不是服务器错误。
    """
    from fastapi import HTTPException

    registry = request.app.state.registry
    if not _has_connector(registry, target):
        raise HTTPException(
            status_code=422,
            detail=f"该平台没有连接器实现，无法接入：{target}",
        )
    return _import_one(registry, request.app.state.kit, target)


@router.post("/platforms/{target}/adopt", response_model=ImportOut)
def adopt_platform(target: str, request: Request) -> ImportOut:
    """人工导入单个连接器（2026-11-19）：纳册 + 立即接入，一步完成。

    自动同步只纳本机客户端；网页版等被策略跳过的连接器由用户在「未导入的
    平台」里手动导入。纳册复用 platform_fact 同一投影（不另拼一套）；缺失判定
    传连接器宇宙，保证不会把其它平台误落 deprecated。
    """
    from fastapi import HTTPException

    from server.main import platform_fact  # 延迟 import：main 会 import 本模块

    registry = request.app.state.registry
    kit = request.app.state.kit
    try:
        conn = registry.get(target)
    except KeyError:
        raise HTTPException(status_code=422, detail=f"没有这个连接器：{target}") from None
    if getattr(conn.manifest, "retired", False):
        raise HTTPException(status_code=422, detail=f"连接器已退役，无法导入：{target}")
    provisions = getattr(request.app.state, "provisions", None)
    if provisions is None:
        provisions = registry.provision_ports(vault=kit.vault, transport=None)
        request.app.state.provisions = provisions
    fact = platform_fact(conn, provisions)
    universe = frozenset(
        c.manifest.id
        for c in registry.platforms()
        if not getattr(c.manifest, "retired", False)
    )
    kit.sync_platforms.execute((fact,), known_codes=universe)
    kit.update_checkin_schedule(compose_schedule_entries(registry, kit))
    return _import_one(registry, kit, target)


@router.delete("/platforms/{platform_code}", response_model=PlatformRemovedOut)
def remove_platform(platform_code: str, request: Request) -> PlatformRemovedOut:
    """删除平台（2026-11-19 用户裁决，内部称「移出名册」）：误导入 / 不再用的平台可退回「未导入的平台」。

    只删 `plat_platform` 事实行——账户、领取台账、凭据一律保留；重新导入时
    按 platform_code 自动归位。自定义平台请走 `DELETE /platforms/custom/{code}`
    （那条会连连接器目录一起删）。
    """
    from fastapi import HTTPException

    from butler_connectors.paths import custom_connectors_root

    kit = request.app.state.kit
    if (custom_connectors_root() / platform_code).is_dir():
        raise HTTPException(
            status_code=409,
            detail="自定义平台请用「删除自定义平台」（会同时删除连接器目录）",
        )
    if not kit.remove_platform.execute(platform_code):
        raise HTTPException(status_code=404, detail=f"名册里没有这个平台：{platform_code}")
    registry = request.app.state.registry
    kit.update_checkin_schedule(compose_schedule_entries(registry, kit))
    return PlatformRemovedOut(
        platform_code=platform_code,
        removed=True,
        message="已删除平台；账户与历史台账保留，可在「未导入的平台」重新导入",
    )


@router.post("/platforms/import-all", response_model=list[ImportOut])
def import_all_platforms(request: Request) -> list[ImportOut]:
    """一键导入：全部未泊位连接器逐家接入（结果如实分列，单家失败已在 dock 内收进 issues）。

    选谁不选谁是编排语义，归 server（A1-02 编排层）；端零入参。
    """
    registry = request.app.state.registry
    kit = request.app.state.kit
    docked = {a.platform_code for a in kit.accounts.list_all()}
    # 选谁导入 = 名册表裁决（ADR-021/022）：活跃、未退役、未导入的**本机客户端**；
    # 网页版（kind=web）不自动接——它们留在「未导入的平台」里由用户手动导入
    # （2026-11-19 用户裁决）。retired 连接器启动同步时已落 deprecated，不进名册。
    targets = sorted(
        p.platform_code
        for p in kit.platforms.list_all()
        if p.is_active
        and p.deprecated_at is None
        and p.platform_kind != "web"
        and p.platform_code not in docked
    )  # 按 platform_code 排序：批量结果顺序确定，不随名册插入序漂移
    out: list[ImportOut] = []
    for target in targets:
        if not _has_connector(registry, target):
            # 名册里存在但没有连接器实现（手工登记/已下线）：如实出账，不拖累其它平台
            out.append(
                ImportOut(
                    target=target,
                    accounts=[],
                    issues=["没有连接器实现，已跳过"],
                )
            )
            continue
        out.append(_import_one(registry, kit, target))
    return out
