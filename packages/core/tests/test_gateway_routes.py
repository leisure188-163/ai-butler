"""网关路由表模型与管理用例测试（R4-G6）：校验显式报错 + 整表替换语义。"""

from __future__ import annotations

import pytest

from butler_core.execution.gateway_routes import RouteRule, RouteTable
from butler_core.execution.usecases.manage_gateway_routes import ManageGatewayRoutes


class FakeStore:
    def __init__(self) -> None:
        self.saved: list[RouteTable] = []

    def load(self) -> RouteTable:
        return self.saved[-1] if self.saved else RouteTable(rules=())

    def save(self, table: RouteTable) -> None:
        self.saved.append(table)


# ── 模型校验（单源：server 写入与网关装载共用）──

def test_from_dict_合法表_解析往返() -> None:
    table = RouteTable.from_dict(
        {"routes": [{"model": "gpt-x", "accounts": ["trae_cn:main", "trae_cn:second"]}]}
    )
    assert table.route("gpt-x") == ("trae_cn:main", "trae_cn:second")
    assert table.route("unknown") == ()  # 未知模型 = 空候选
    assert RouteTable.from_dict(table.to_dict()) == table  # 对称往返


def test_from_dict_缺routes数组_显式报错() -> None:
    with pytest.raises(ValueError, match="缺 routes 数组"):
        RouteTable.from_dict({})


def test_from_dict_模型重复_显式拒绝() -> None:
    with pytest.raises(ValueError, match="重复路由规则"):
        RouteTable.from_dict(
            {"routes": [
                {"model": "m", "accounts": ["a:main"]},
                {"model": "m", "accounts": ["b:main"]},
            ]}
        )


def test_from_dict_空model或空accounts_显式报错() -> None:
    with pytest.raises(ValueError, match="不得为空"):
        RouteTable.from_dict({"routes": [{"model": "  ", "accounts": ["a:main"]}]})
    with pytest.raises(ValueError, match="不得为空"):
        RouteTable.from_dict({"routes": [{"model": "m", "accounts": []}]})


def test_account_ids_全集() -> None:
    table = RouteTable(rules=(
        RouteRule(model="m1", accounts=("a:main", "b:main")),
        RouteRule(model="m2", accounts=("a:main",)),
    ))
    assert table.account_ids == frozenset({"a:main", "b:main"})


# ── 管理用例 ──

def test_replace_先校验后落盘_非法不触store() -> None:
    store = FakeStore()
    uc = ManageGatewayRoutes(store=store)
    with pytest.raises(ValueError, match="重复路由规则"):
        uc.replace({"routes": [{"model": "m", "accounts": ["a:main"]},
                               {"model": "m", "accounts": ["b:main"]}]})
    assert store.saved == []  # 校验失败绝不落盘


def test_replace_current_往返() -> None:
    store = FakeStore()
    uc = ManageGatewayRoutes(store=store)
    saved = uc.replace({"routes": [{"model": "gpt-x", "accounts": ["trae_cn:main"]}]})
    assert uc.current() == saved
    assert store.saved == [saved]


def test_current_缺失_空表合法初始态() -> None:
    uc = ManageGatewayRoutes(store=FakeStore())
    assert uc.current().rules == ()
