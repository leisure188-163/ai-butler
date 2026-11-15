"""网关路由表模型（R4-G6，ADR-012 裁决 5/6）：模型→账户池静态映射，单源在此。

- 校验单源：server 管理面写入与网关进程装载共用本模块 from_dict——两端口径
  永不漂移（裁决 6：规则 server 管、网关只读）
- 语义：按账户顺序 = 优先级，失败转移由网关调用方按序重试（G5 forwarder）
- M1 只做精确模型名匹配；通配/余额感知等取证后增量（裁决 5 已预留）
- 校验显式报错（红线 5）：模型空/账户空/模型重复 → ValueError 逐条中文报错
"""

from __future__ import annotations

from dataclasses import dataclass


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

    def to_dict(self) -> dict:
        """序列化为声明式配置形状（与 from_dict 对称，文件落盘用）。"""
        return {
            "routes": [
                {"model": rule.model, "accounts": list(rule.accounts)}
                for rule in self.rules
            ]
        }

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
