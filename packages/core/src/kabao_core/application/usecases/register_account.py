"""账号名册用例（A2-01 §1）：Provider 下注册名册位，幂等停靠。

凭据不在这里——凭据经 Connector 自己的解锁协议直接进 vault
（kinds 由 manifest 申报，最小授权 A2-02 §5）。
（自 application/usecases.py 按用例边界分出——conventions/04 §2.3，2026-11-14。）
"""

from __future__ import annotations

from dataclasses import dataclass

from kabao_core.application.ports import AccountRepository
from kabao_core.domain.account import Account, main_account_id
from kabao_core.domain.run import now_utc


@dataclass
class RegisterAccount:
    """账号停靠（A2-01 §1）：Provider 下注册名册位，幂等（重复停同一位返回既有账号）。

    凭据不在这里——Connector 的接入流程（dock）仅负责身份落册，凭据经
    它自己的解锁协议直接进 vault（kinds 由 manifest 申报，最小授权 A2-02 §5）。
    """

    accounts: AccountRepository

    def execute(
        self, provider: str, display_name: str, *, account_id: str | None = None
    ) -> Account:
        aid = account_id or main_account_id(provider)
        existing = self.accounts.get(aid)
        if existing is not None:
            return existing  # 幂等：同Provider名册位已存在，不重复建
        account = Account(
            id=aid, provider=provider.strip(), display_name=display_name,
            created_at=now_utc(),
        )
        self.accounts.save(account)
        return account
