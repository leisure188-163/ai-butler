"""删除账户用例（2026-11-19 用户裁决）：账户行与关联凭据一并删除，不留脏数据。

语义：
- 账户行不存在 → 返回 `None`（端侧 404），不做任何凭据清理（防误删同名凭据）；
- 先清凭据、再删账户行：凭据清理失败则账户行保留（显式报错，不假称删成功）；
- 返回本次清掉的凭据条数，供端侧确认文案与审计。
"""

from __future__ import annotations

from dataclasses import dataclass

from butler_core.accounts.ports import AccountRepository, VaultPort


@dataclass
class DeleteAccount:
    accounts: AccountRepository
    vault: VaultPort

    def execute(self, account_id: str) -> int | None:
        """返回删除的凭据条数；账户不存在 = None。"""
        if self.accounts.get(account_id) is None:
            return None
        purged = self.vault.purge(account_id)
        self.accounts.remove(account_id)
        return purged
