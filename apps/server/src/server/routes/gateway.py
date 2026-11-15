"""网关路由规则管理面（R4-G6，ADR-012 裁决 6）：server 管、网关只读装载。

- GET  /gateway/routes = 当前路由表（文件缺失 = 空表合法初始态）
- PUT  /gateway/routes = 整表替换（声明式配置，无增量 PATCH）：校验单源在
  core RouteTable.from_dict（与网关装载同口径，永不漂移），非法显式 422
- 生效时机 = 网关进程重启后装载（M1 启动时装载一次；响应体注明，不撒谎）
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

router = APIRouter(tags=["butler"])


class RouteRuleIn(BaseModel):
    """一条路由规则入参：模型名 → 有序账户池（先 = 优先）。"""

    model: str = Field(min_length=1)
    accounts: list[str] = Field(min_length=1)


class GatewayRoutesIn(BaseModel):
    """整表替换入参（声明式配置）。"""

    routes: list[RouteRuleIn]


class RouteRuleOut(BaseModel):
    model: str
    accounts: list[str]


class GatewayRoutesOut(BaseModel):
    """路由表投影：takes_effect 如实注明生效时机（M1 = 网关重启装载）。"""

    routes: list[RouteRuleOut]
    takes_effect: str


def _to_out(routes) -> GatewayRoutesOut:
    return GatewayRoutesOut(
        routes=[RouteRuleOut(model=r.model, accounts=list(r.accounts)) for r in routes.rules],
        takes_effect="网关进程重启后装载生效（M1 启动时装载一次）",
    )


@router.get("/gateway/routes", response_model=GatewayRoutesOut)
def get_gateway_routes(request: Request) -> GatewayRoutesOut:
    """当前网关路由表（只读投影）。"""
    try:
        table = request.app.state.kit.manage_gateway_routes.current()
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return _to_out(table)


@router.put("/gateway/routes", response_model=GatewayRoutesOut)
def put_gateway_routes(body: GatewayRoutesIn, request: Request) -> GatewayRoutesOut:
    """整表替换路由规则：先校验后落盘，非法显式 422（不静默丢规则）。"""
    data = {"routes": [rule.model_dump() for rule in body.routes]}
    try:
        table = request.app.state.kit.manage_gateway_routes.replace(data)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"路由配置落盘失败：{exc}") from exc
    return _to_out(table)
