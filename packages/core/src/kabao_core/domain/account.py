"""Account 聚合根（A2-01 §1）：身份 + 归属；Run/Event/凭据/用量都挂 account_id。

- M1 每 Provider 先落一个名册位（`:main`），多账户（同 Provider N 账号）M2 再扩
  ——id 规则集中本模块单源，扩规则只改这里
- provider 是 Connector id（trae_cn / qoder / …），下调为实现细节（A2-01 §1）
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from kabao_core.domain.errors import DomainError


class AccountInvalid(DomainError):
    pass


def main_account_id(provider: str) -> str:
    """该 Provider 默认名册位：``{provider}:main``（M1 单账户策略，M2 扩多账户）。"""
    if not provider.strip():
        raise AccountInvalid("provider（connector id）不能为空")
    return f"{provider.strip()}:main"


@dataclass(frozen=True)
class Account:
    """账号=业务唯一锚点。凭据挂钩在 vault（(account_id, kind) 规范引用）。"""

    id: str
    provider: str
    display_name: str
    created_at: datetime

    def __post_init__(self) -> None:
        if not self.id.strip() or not self.provider.strip():
            raise AccountInvalid("Account 需要非空 id 与 provider")
        if not self.display_name.strip():
            raise AccountInvalid("Account 需要非空 display_name（用户看到的船名）")
