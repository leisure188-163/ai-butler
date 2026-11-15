"""声明式路由表（ADR-012 裁决 5/6）：模型 → 账户池静态映射，网关只读。

- 路由 = 数据（JSON 文件 / 将来 server 契约下发），M1 语义：按账户顺序 =
  优先级，失败转移由调用方按序重试（G5 协议面循 candidate 落地）
- 校验显式报错（红线 5）：模型空/账户空/模型重复 → 拒绝装载
- M1 只做精确模型名匹配；通配/余额感知等取证后增量（裁决 5 已预留）
- server 管理面（规则 CRUD 契约）未落地前，规则源 = 数据根 JSON 文件
  （gateway-routes.json）；文件缺失 = 空表（合法初始态），文件非法 = 显式报错
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RouteRule:
    """一条路由规则：模型名 → 有序账户池（先 = 优先）。"""

    model: str
    accounts: tuple[str, ...]


@dataclass(frozen=True)
class RouteTable:
    """只读路由表。route() 返回优先级有序的候选账户（未知模型 = 空候选）。"""

    rules: tuple[RouteRule, ...]

    def route(self, model: str) -> tuple[str, ...]:
        for rule in self.rules:
            if rule.model == model:
                return rule.accounts
        return ()

    @property
    def account_ids(self) -> frozenset[str]:
        return frozenset(a for rule in self.rules for a in rule.accounts)

    @classmethod
    def from_dict(cls, data: dict) -> "RouteTable":
        """解析并校验声明式规则（显式报错，绝不静默丢规则）。"""
        raw = data.get("routes")
        if not isinstance(raw, list):
            raise ValueError("路由配置缺 routes 数组——显式报错，不静默当空表")
        rules: list[RouteRule] = []
        seen: set[str] = set()
        for item in raw:
            if not isinstance(item, dict):
                raise ValueError(f"路由规则须为对象: {item!r}")
            accounts_raw = item.get("accounts")
            if not isinstance(accounts_raw, list):
                raise ValueError(f"路由规则 accounts 须为数组: {item!r}")
            model = str(item.get("model", "")).strip()
            accounts = tuple(str(a).strip() for a in accounts_raw)
            if not model or not accounts or any(not a for a in accounts):
                raise ValueError(f"路由规则字段非法: {item!r}（model/accounts 不得为空）")
            if model in seen:
                raise ValueError(f"模型 {model!r} 重复路由规则——歧义配置，显式拒绝")
            seen.add(model)
            rules.append(RouteRule(model=model, accounts=accounts))
        return cls(rules=tuple(rules))


def load_routes(path: Path) -> RouteTable:
    """从 JSON 文件装载路由表；缺失 = 空表（合法初始态），非法 = 显式报错。"""
    if not path.exists():
        return RouteTable(rules=())
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise ValueError(f"路由配置文件解析失败: {path}——{exc}") from exc
    try:
        return RouteTable.from_dict(data)
    except ValueError as exc:
        raise ValueError(f"路由配置文件校验失败: {path}——{exc}") from exc
