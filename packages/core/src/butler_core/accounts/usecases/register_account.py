"""账户域用例（A2-04 §4）：注册账户 + 多账号枚举导入。

多账号（ADR-003）：(platform, account_code) 是身份锚点；同身份重复停靠是幂等
回放（返回既有账户，不覆盖、不改号）；显式传入的 account_id 与身份编址不一致
则拒绝（形状冲突，红线 5）。
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
        platform: str,
        account_name: str,
        *,
        account_code: str = "main",
        account_id: str | None = None,
    ) -> Account:
        computed = account_identity(platform, account_code)
        if account_id is not None and account_id != computed:
            raise AccountAlreadyExists(
                f"account_id {account_id!r} 与 (platform, account_code) 编址 {computed!r} 冲突"
            )
        aid = computed
        existing = self.accounts.get(aid)
        if existing is not None:
            return existing  # 幂等回放：同一身份重复停靠，不覆盖不改号
        account = Account(
            id=aid,
            platform_code=platform.strip(),
            account_name=account_name,
            created_at=now_utc(),
            account_code=account_code,
        )
        self.accounts.save(account)
        return account

    def import_from_source(self, draft: AccountDraft) -> list[Account]:
        """枚举本机多 profile（ADR-003 §3），逐账号入库。"""

        if self.source is None:
            return [self.execute(draft.platform_code, draft.account_name, account_code=draft.account_code)]
        registered: list[Account] = []
        for key, display in self.source.enumerate_accounts(draft.platform_code):
            registered.append(
                self.execute(draft.platform_code, display, account_code=key)
            )
        return registered
