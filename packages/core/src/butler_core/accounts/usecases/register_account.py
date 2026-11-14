"""账户域用例（A2-11 §4）：注册账户 + 多账号枚举导入。

多账号（ADR-010）：(provider, account_key) 是身份锚点；同身份重复停靠是幂等
回放，同身份但展示名冲突显式拒绝（不静默改号，红线 5）。
"""

from __future__ import annotations

from dataclasses import dataclass

from butler_core.accounts.domain import (
    Account,
    AccountAlreadyExists,
    AccountDraft,
    account_identity,
)
from butler_core.accounts.ports import AccountRepository, SessionSourcePort
from butler_core.shared.time import now_utc


@dataclass
class RegisterAccount:
    accounts: AccountRepository
    source: SessionSourcePort | None = None

    def execute(
        self,
        provider: str,
        display_name: str,
        *,
        account_key: str = "default",
        account_id: str | None = None,
    ) -> Account:
        aid = account_id or account_identity(provider, account_key)
        existing = self.accounts.get(aid)
        if existing is not None:
            if existing.display_name != display_name:
                raise AccountAlreadyExists(
                    f"账户 {aid!r} 已存在且展示名冲突，显式拒绝（不静默改号）"
                )
            return existing  # 幂等回放：同一身份重复停靠
        account = Account(
            id=aid,
            provider=provider.strip(),
            display_name=display_name,
            created_at=now_utc(),
            account_key=account_key,
        )
        self.accounts.save(account)
        return account

    def import_from_source(self, draft: AccountDraft) -> list[Account]:
        """枚举本机多 profile（ADR-010 §3），逐账号入库。"""

        if self.source is None:
            return [self.execute(draft.provider, draft.display_name, account_key=draft.account_key)]
        registered: list[Account] = []
        for key, display in self.source.enumerate_accounts(draft.provider):
            registered.append(
                self.execute(draft.provider, display, account_key=key)
            )
        return registered
