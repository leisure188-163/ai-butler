"""自定义平台域 API（2026-11-18）：内置清单之外的平台由用户自建。

设计要点（与「纯登记式新建」的区别）：自定义平台不是一行数据库记录，而是
**一份落到自定义连接器目录的声明式连接器**——manifest + 五段式声明 YAML，
由同一个 DeclarativeProvisionPort 执行。所以它真的会被调度到点、真的会发请求。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(tags=["butler"])


class CustomPlatformOut(BaseModel):
    """自定义平台目录行（只有 code/display，详情走 GET /platforms 名册）。"""

    code: str
    display: str


class RequestDraftIn(BaseModel):
    method: str = "POST"
    url: str
    body: dict = {}


class StatusDraftIn(BaseModel):
    request: RequestDraftIn
    checked_in_path: str = ""
    code_path: str = "code"
    expect_ok: str = "0"


class ClaimDraftIn(BaseModel):
    request: RequestDraftIn
    code_path: str = "code"
    expect_ok: str = "0"
    retry_on_codes: list[str] = []


class CustomPlatformIn(BaseModel):
    """自定义平台草稿：网页版 + Chrome 登录态（browser_cookie 形态）。"""

    code: str
    display: str
    domain: str
    cookies: list[str]
    status: StatusDraftIn
    claim: ClaimDraftIn
    business_codes: dict[str, str] | None = None
    schedule_times: list[str] = []


class CustomPlatformSaved(BaseModel):
    code: str
    display: str
    schedule_times: list[str]
    message: str


class CustomPlatformDeleted(BaseModel):
    code: str
    deleted: bool
    message: str


def _custom_root():
    from butler_connectors.paths import custom_connectors_root

    return custom_connectors_root()


def _fail(status_code: int, detail: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail=detail)


@router.get("/platforms/custom", response_model=list[CustomPlatformOut])
def list_custom_platforms() -> list[CustomPlatformOut]:
    """自定义连接器目录里已登记的平台（前端据此标「自定义」徽章）。"""
    from butler_connectors.custom import list_custom_platforms as scan

    return [CustomPlatformOut(**row) for row in scan(_custom_root())]


@router.post("/platforms/custom", response_model=CustomPlatformSaved)
def create_custom_platform(request: Request, payload: CustomPlatformIn) -> CustomPlatformSaved:
    """新建/更新自定义平台：校验 → 落盘 → 热重载（端口 + 名册 + 调度）。"""
    from butler_connectors.custom import CustomPlatformDraft, save_custom_platform
    from butler_connectors.manifest import ManifestInvalid
    from server.main import reload_connectors

    from server.routes.platforms import _has_connector

    registry = getattr(request.app.state, "registry", None)
    if registry is not None and _has_connector(registry, payload.code):
        # 内置能力优先：撞车不许覆盖（否则同名平台两份实现，路由含糊）
        raise _fail(409, f"平台编码 {payload.code!r} 已被内置连接器占用，请换一个编码")

    try:
        # exclude_none：前端没填的可选字段（如 business_codes）交给草稿的缺省值，
        # 不能把 None 硬塞进 dict 字段（否则合法请求被 schema 误杀）
        draft = CustomPlatformDraft.model_validate(payload.model_dump(exclude_none=True))
    except ManifestInvalid as e:
        raise _fail(422, str(e)) from e
    except ValueError as e:  # pydantic 校验错误 → 可读 422
        raise _fail(422, f"自定义平台声明不完整：{e}") from e

    try:
        save_custom_platform(draft, _custom_root())
    except ManifestInvalid as e:
        raise _fail(422, str(e)) from e

    reload_connectors(request.app)
    return CustomPlatformSaved(
        code=draft.code,
        display=draft.display,
        schedule_times=list(draft.schedule_times),
        message="自定义平台已保存并热加载；在名册里「接入」后会从本机 Chrome 抓取登录态",
    )


@router.delete("/platforms/custom/{code}", response_model=CustomPlatformDeleted)
def delete_custom_platform(request: Request, code: str) -> CustomPlatformDeleted:
    """删除自定义平台：删目录 → 热重载（名册自动落 deprecated，不再排班）。"""
    from butler_connectors.custom import delete_custom_platform as drop
    from butler_connectors.manifest import ManifestInvalid
    from server.main import reload_connectors

    from server.routes.platforms import _has_connector

    registry = getattr(request.app.state, "registry", None)
    if registry is not None and _has_connector(registry, code) and not _is_custom(code):
        raise _fail(409, f"{code!r} 是内置平台，只能停用不能删除")
    try:
        removed = drop(code, _custom_root())
    except ManifestInvalid as e:
        raise _fail(422, str(e)) from e
    if not removed:
        raise _fail(404, f"自定义平台 {code!r} 不存在")
    reload_connectors(request.app)
    return CustomPlatformDeleted(
        code=code, deleted=True, message="已删除；该平台不再排班，历史台账保留"
    )


def _is_custom(code: str) -> bool:
    """该 code 是否来自自定义目录（内置与自定义同 id 在装载期已被拒绝，故目录存在即自定义）。"""
    return (_custom_root() / code).is_dir()
